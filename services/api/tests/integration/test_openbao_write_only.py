"""Against the running stack: the API's OpenBao token can write secrets but never read them.

Run with `make test-integration` (it extracts the API and runtime tokens from the compose
volumes). Skipped when the tokens are not provided.
"""

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from veyntora_api.secrets.openbao import SecretWriter
from veyntora_providers.secrets import OpenBaoReader, SecretUnavailableError

BAO = os.environ.get("VEY_IT_OPENBAO_URL", "http://localhost:8200")
API_TOKEN = os.environ.get("VEY_IT_OPENBAO_API_TOKEN", "")
RUNTIME_TOKEN = os.environ.get("VEY_IT_OPENBAO_RUNTIME_TOKEN", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not API_TOKEN or not RUNTIME_TOKEN, reason="OpenBao tokens not provided"),
]


async def test_api_token_writes_but_cannot_read_back() -> None:
    path = f"providers/{uuid4()}"
    writer = SecretWriter(BAO, API_TOKEN)
    try:
        ref = await writer.put(path, "sk-integration-0123456789abcdef")
        assert ref.last4 == "cdef"

        async with httpx.AsyncClient(base_url=f"{BAO}/v1") as http:
            as_api = await http.get(f"/kv/data/{path}", headers={"X-Vault-Token": API_TOKEN})
            assert as_api.status_code == 403, "the API must not be able to read secrets"
            meta = await http.get(f"/kv/metadata/{path}", headers={"X-Vault-Token": API_TOKEN})
            assert meta.status_code == 403

            as_runtime = await http.get(
                f"/kv/data/{path}", headers={"X-Vault-Token": RUNTIME_TOKEN}
            )
            assert as_runtime.status_code == 200
            assert as_runtime.json()["data"]["data"]["value"] == "sk-integration-0123456789abcdef"

            denied = await http.post(
                f"/kv/data/{path}",
                headers={"X-Vault-Token": RUNTIME_TOKEN},
                json={"data": {"value": "overwrite"}},
            )
            assert denied.status_code == 403, "runtime services must not write secrets"
    finally:
        await writer.delete(path)
        await writer.close()


async def test_api_token_cannot_touch_system_paths() -> None:
    async with httpx.AsyncClient(base_url=f"{BAO}/v1") as http:
        for method, url in (
            ("GET", "/sys/policies/acl"),
            ("GET", "/sys/mounts"),
            ("POST", "/auth/token/create"),
        ):
            res = await http.request(method, url, headers={"X-Vault-Token": API_TOKEN}, json={})
            assert res.status_code == 403, url


async def test_replaced_key_stays_readable_by_version_until_destroyed(tmp_path: Path) -> None:
    path = f"users/{uuid4()}/{uuid4()}"
    writer = SecretWriter(BAO, API_TOKEN)
    token = tmp_path / "runtime.token"
    token.write_text(RUNTIME_TOKEN)
    reader = OpenBaoReader(BAO, token)
    try:
        await writer.put(path, "sk-old-0123456789abcdef")
        new = await writer.put(path, "sk-new-0123456789abcdef")
        previous = new.previous()
        assert new.version == 2 and previous == f"kv/{path}?version=1"
        assert await reader.read(new.ref) == "sk-new-0123456789abcdef"
        assert await reader.read(previous) == "sk-old-0123456789abcdef"
        await writer.destroy_version(previous)
        with pytest.raises(SecretUnavailableError):
            await OpenBaoReader(BAO, token).read(previous)  # a fresh reader: no cache
    finally:
        await writer.delete(path)
        await writer.close()
