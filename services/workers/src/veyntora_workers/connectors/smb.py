"""File shares (SMB 2/3, Windows or Samba) with their NTFS permissions.

- Files of the chosen folders are listed; modification time and size tell changed files
  apart. The account needs read access to the files and their permissions.
- Who may read a file comes from its DACL (inherited entries included): SIDs with an
  allow entry for reading, minus SIDs with a deny entry for reading. SIDs map to Veyntora
  groups through the source's SID map (groups, or well-known SIDs such as S-1-1-0
  Everyone); anything else is dropped (fail closed) and listed on the source. Members of
  a mapped Windows group must be in the matching Veyntora group, kept in step by
  Keycloak's directory sync.

smbprotocol is synchronous; calls run in a worker thread.
"""

from __future__ import annotations

import asyncio
import posixpath
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import smbclient
from smbclient._io import SMBRawIO
from smbprotocol.file_info import InfoType
from smbprotocol.open import SMB2QueryInfoRequest, SMB2QueryInfoResponse
from smbprotocol.security_descriptor import AceType, SMB2CreateSDBuffer
from veyntora_api.knowledge.connectors import SmbSettings

from veyntora_workers.connectors.listing import Entry, Listing

READ_CONTROL = 0x00020000
DACL_SECURITY_INFORMATION = 0x00000004
# FILE_READ_DATA, GENERIC_ALL, GENERIC_READ
READ_BITS = 0x00000001 | 0x10000000 | 0x80000000


def readers_of(aces: list[tuple[str, str, int]]) -> set[str]:
    """SIDs allowed to read: (type, sid, mask) entries; deny wins over allow."""
    allowed = {sid for kind, sid, mask in aces if kind == "allow" and mask & READ_BITS}
    denied = {sid for kind, sid, mask in aces if kind == "deny" and mask & READ_BITS}
    return allowed - denied


class SmbReader:
    def __init__(self, cfg: SmbSettings, password: str, *, max_bytes: int) -> None:
        self.cfg = cfg
        self.max_bytes = max_bytes
        self._kw: dict[str, Any] = {
            "username": cfg.username,
            "password": password,
            "port": cfg.port,
            "connection_timeout": 15,
        }
        self.listed_all = False
        self._unmapped: set[str] = set()

    @property
    def root(self) -> str:
        return rf"\\{self.cfg.server}\{self.cfg.share}"

    def _unc(self, rel: str) -> str:
        return self.root + ("\\" + rel.replace("/", "\\") if rel else "")

    async def close(self) -> None:
        await asyncio.to_thread(smbclient.delete_session, self.cfg.server, port=self.cfg.port)

    async def check(self) -> str:
        names = await asyncio.to_thread(smbclient.listdir, self.root, **self._kw)
        return f"Share {self.cfg.share} is readable; {len(names)} entries at the top."

    def _walk(self) -> list[tuple[str, int, float]]:
        out: list[tuple[str, int, float]] = []
        for start in self.cfg.include_paths or [""]:
            rel_start = start.strip("/\\").replace("\\", "/")
            for folder, _, files in smbclient.walk(self._unc(rel_start), **self._kw):
                rel_folder = folder[len(self.root) :].strip("\\").replace("\\", "/")
                for name in files:
                    rel = posixpath.join(rel_folder, name) if rel_folder else name
                    st = smbclient.stat(self._unc(rel), **self._kw)
                    out.append((rel, int(st.st_size), float(st.st_mtime)))
        return out

    def _aces(self, rel: str) -> list[tuple[str, str, int]]:
        with SMBRawIO(self._unc(rel), mode="r", desired_access=READ_CONTROL, **self._kw) as raw:
            fd = raw.fd
            req = SMB2QueryInfoRequest()
            req["info_type"] = InfoType.SMB2_0_INFO_SECURITY
            req["output_buffer_length"] = 65535
            req["additional_information"] = DACL_SECURITY_INFORMATION
            req["file_id"] = fd.file_id
            request = fd.connection.send(
                req, sid=fd.tree_connect.session.session_id, tid=fd.tree_connect.tree_connect_id
            )
            response = fd.connection.receive(request)
        info = SMB2QueryInfoResponse()
        info.unpack(response["data"].get_value())
        sd = SMB2CreateSDBuffer()
        sd.unpack(info["buffer"].get_value())
        dacl = sd.get_dacl()
        out = []
        for ace in dacl["aces"].get_value() if dacl else []:
            kind = ace["ace_type"].get_value()
            label = (
                "allow"
                if kind == AceType.ACCESS_ALLOWED_ACE_TYPE
                else "deny"
                if kind == AceType.ACCESS_DENIED_ACE_TYPE
                else "other"
            )
            out.append((label, str(ace["sid"].get_value()), int(ace["mask"].get_value())))
        return out

    def acl_for(self, sids: set[str]) -> dict[str, list[str]]:
        groups = sorted({str(self.cfg.sid_map[s]) for s in sids if s in self.cfg.sid_map})
        self._unmapped |= {f"SID {s}" for s in sids if s not in self.cfg.sid_map}
        return {"users": [], "groups": groups}

    async def entries(self) -> AsyncIterator[Entry]:
        for rel, size, mtime in await asyncio.to_thread(self._walk):
            sids = readers_of(await asyncio.to_thread(self._aces, rel))
            yield Entry(
                external_id=rel,
                path=rel,
                name=posixpath.basename(rel),
                url=None,
                version=f"{int(mtime)}-{size}",
                size=size,
                modified=datetime.fromtimestamp(mtime, UTC),
                acl=self.acl_for(sids),
            )
        self.listed_all = True

    def _read(self, rel: str) -> bytes:
        with smbclient.open_file(self._unc(rel), mode="rb", **self._kw) as f:
            data: bytes = f.read(self.max_bytes + 1)
        return data

    async def download(self, entry: Entry) -> bytes:
        return await asyncio.to_thread(self._read, entry.external_id)

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(),
            download=self.download,
            complete=lambda: self.listed_all,
            unmapped=lambda: self._unmapped,
        )
