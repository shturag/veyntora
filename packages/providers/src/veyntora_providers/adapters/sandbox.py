"""Code interpreter: Veyntora's own sandbox container (`services/sandbox`, ADR 0030).

It runs on an internal network without internet access; the default endpoint is the one
in the local stack. A key is optional: when the sandbox has SANDBOX_TOKEN set, store the
same value here.
"""

from __future__ import annotations

import base64
import time

import httpx

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    Capability,
    CodeFile,
    CodeResult,
    HealthResult,
    KeyRejectedError,
)
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

DEFAULT_ENDPOINT = "http://sandbox:8090"


class SandboxError(RuntimeError):
    """The sandbox refused the request; carries the status only."""


class Sandbox:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        self._config = config
        self._secrets = secrets
        self._base = (config.endpoint or DEFAULT_ENDPOINT).rstrip("/")

    async def run(self, code: str) -> CodeResult:
        ref = self._config.secret_ref
        key = await self._secrets.read(ref) if ref else None
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as http:
            res = await http.post(f"{self._base}/run", json={"code": code}, headers=headers)
        if res.status_code in (401, 403):
            raise KeyRejectedError(f"the sandbox refused the request (HTTP {res.status_code})")
        if res.status_code != 200:
            raise SandboxError(f"the sandbox refused the code (HTTP {res.status_code})")
        data = res.json()
        return CodeResult(
            stdout=str(data.get("stdout") or ""),
            stderr=str(data.get("stderr") or ""),
            exit_code=data.get("exit_code"),
            timed_out=bool(data.get("timed_out")),
            files=tuple(
                CodeFile(str(f["name"]), str(f["mime"]), base64.b64decode(f["base64"]))
                for f in data.get("files") or []
            ),
        )

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            out = await self.run("print(6 * 7)")
            if out.stdout.strip() != "42":
                raise SandboxError("the sandbox did not run a test calculation")
        except (httpx.HTTPError, SandboxError, KeyRejectedError) as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, str(exc)[:200])
        return HealthResult(True, (time.perf_counter() - start) * 1000)


@register(Capability.CODE_INTERPRETER, "sandbox")
def _sandbox(config: ProviderInstanceConfig, secrets: SecretReader) -> Sandbox:
    return Sandbox(config, secrets)
