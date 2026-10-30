"""Virus scan through clamd's INSTREAM command over TCP.

Protocol: send `zINSTREAM\0`, then chunks of <4-byte big-endian length><data>, then a
zero-length chunk; clamd answers `stream: OK`, `stream: <signature> FOUND` or `... ERROR`.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

_CHUNK = 64 * 1024


class ScannerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    detail: str


def _split(address: str) -> tuple[str, int]:
    host, _, port = address.rpartition(":")
    if not host or not port.isdigit():
        raise ScannerUnavailableError(f"clamd address must be host:port, not {address!r}")
    return host, int(port)


async def _command(address: str, payload: bytes, wait_s: float) -> str:
    host, port = _split(address)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), wait_s)
    except (OSError, TimeoutError) as exc:
        raise ScannerUnavailableError(f"cannot reach the virus scanner: {exc}") from exc
    try:
        writer.write(payload)
        await writer.drain()
        reply = await asyncio.wait_for(reader.readuntil(b"\0"), wait_s)
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
        raise ScannerUnavailableError(f"virus scanner did not answer: {exc}") from exc
    finally:
        writer.close()
        await writer.wait_closed()
    return reply.rstrip(b"\0").decode("utf-8", "replace").strip()


async def ping(address: str, wait_s: float = 3.0) -> bool:
    try:
        return await _command(address, b"zPING\0", wait_s) == "PONG"
    except ScannerUnavailableError:
        return False


async def scan_bytes(address: str, data: bytes, wait_s: float = 120.0) -> ScanResult:
    parts = [b"zINSTREAM\0"]
    for i in range(0, len(data), _CHUNK):
        chunk = data[i : i + _CHUNK]
        parts.append(struct.pack(">I", len(chunk)) + chunk)
    parts.append(struct.pack(">I", 0))
    reply = await _command(address, b"".join(parts), wait_s)
    body = reply.removeprefix("stream:").strip()
    if body == "OK":
        return ScanResult(True, "OK")
    if body.endswith("FOUND"):
        return ScanResult(False, body.removesuffix("FOUND").strip())
    # Size limits and other errors: the file was not scanned, so it is not clean.
    raise ScannerUnavailableError(f"virus scanner error: {body}")
