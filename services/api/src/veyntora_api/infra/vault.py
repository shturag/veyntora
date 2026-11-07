"""OpenBao for the infrastructure config (ADR 0034): reading the connection passwords with
the infra token, and setting Veyntora up in an OpenBao with an admin's token.

The admin token is used for one request and never stored: it creates the three policies
and one token for each (what deploy/compose/openbao/init.sh does for a new OpenBao).
"""

from __future__ import annotations

import asyncio
from importlib import resources

import httpx

from veyntora_api.infra.config import secret_path

POLICIES = {
    "veyntora-api": "api.hcl",
    "veyntora-runtime": "runtime.hcl",
    "veyntora-infra-read": "infra.hcl",
}
TOKEN_PERIOD = "768h"  # noqa: S105 - a duration


class VaultError(RuntimeError):
    pass


def _client(url: str, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=url.rstrip("/") + "/v1", headers={"X-Vault-Token": token}, timeout=5.0
    )


async def read_passwords(
    url: str, token: str, mount: str, versions: dict[str, int]
) -> dict[str, str]:
    """The passwords named in `versions`, each at the version the config was saved with."""
    async with _client(url, token) as http:

        async def one(name: str, version: int) -> tuple[str, str]:
            res = await http.get(
                f"/{mount}/data/{secret_path(name)}", params={"version": str(version)}
            )
            if res.status_code != 200:
                raise VaultError(f"OpenBao did not return {name} (HTTP {res.status_code})")
            value = ((res.json().get("data") or {}).get("data") or {}).get("value")
            if not isinstance(value, str):
                raise VaultError(f"{name} has no value in OpenBao")
            return name, value

        pairs = await asyncio.gather(*(one(n, v) for n, v in versions.items()))
    return dict(pairs)


async def renew(url: str, token: str) -> None:
    """Tokens are periodic: each renewal keeps them for another period."""
    async with _client(url, token) as http:
        res = await http.post("/auth/token/renew-self", json={})
    if res.status_code != 200:
        raise VaultError(f"OpenBao token renewal failed (HTTP {res.status_code})")


async def check_token(url: str, token: str) -> str:
    """Whether OpenBao is reachable, unsealed and accepts `token`. Returns its display name."""
    async with _client(url, token) as http:
        health = await http.get("/sys/health", params={"standbyok": "true"})
        if health.status_code == 503:
            raise VaultError("OpenBao is sealed")
        if health.status_code == 501:
            raise VaultError("OpenBao is not initialised")
        res = await http.get("/auth/token/lookup-self")
    if res.status_code != 200:
        raise VaultError("OpenBao refused the token")
    return str((res.json().get("data") or {}).get("display_name") or "token")


async def check_admin(url: str, token: str, mount: str) -> None:
    """The admin token can create Veyntora's policies and tokens."""
    await check_token(url, token)
    paths = [f"sys/policies/acl/{p}" for p in POLICIES] + ["auth/token/create-orphan"]
    async with _client(url, token) as http:
        res = await http.post("/sys/capabilities-self", json={"paths": paths})
        if res.status_code != 200:
            raise VaultError(f"OpenBao capability check failed (HTTP {res.status_code})")
        caps = res.json()
        mounts = await http.get("/sys/mounts")
    missing = [
        p
        for p in paths
        if not {"root", "update", "create", "sudo"}
        & set(caps.get(p) or caps.get("data", {}).get(p) or [])
    ]
    if missing:
        raise VaultError("the token may not set up Veyntora: no access to " + ", ".join(missing))
    if mounts.status_code == 200:
        listed = mounts.json().get("data") or mounts.json()
        engine = listed.get(f"{mount}/")
        if engine is None:
            raise VaultError(f"OpenBao has no secrets engine at {mount}/ (enable KV v2 there)")
        if (engine.get("options") or {}).get("version") != "2":
            raise VaultError(f"{mount}/ is not a KV version 2 engine")


async def provision(url: str, admin_token: str, mount: str) -> dict[str, str]:
    """Write the policies and issue the infra, API and runtime tokens."""
    await check_admin(url, admin_token, mount)
    pkg = resources.files("veyntora_api.infra") / "policies"
    async with _client(url, admin_token) as http:
        for name, file in POLICIES.items():
            text = (pkg / file).read_text().replace('"kv/', f'"{mount}/')
            res = await http.put(f"/sys/policies/acl/{name}", json={"policy": text})
            if res.status_code not in (200, 204):
                raise VaultError(f"OpenBao refused policy {name} (HTTP {res.status_code})")
        # Transit, as init.sh sets it up: the runtime services decrypt with it.
        mounts = (await http.get("/sys/mounts")).json()
        if "transit/" not in (mounts.get("data") or mounts):
            await http.post("/sys/mounts/transit", json={"type": "transit"})
        if (await http.get("/transit/keys/veyntora")).status_code == 404:
            await http.post("/transit/keys/veyntora", json={})

        async def token(policy: str) -> str:
            res = await http.post(
                "/auth/token/create-orphan",
                json={"policies": [policy], "period": TOKEN_PERIOD, "display_name": policy},
            )
            if res.status_code != 200:
                raise VaultError(f"OpenBao did not issue a token for {policy}")
            return str(res.json()["auth"]["client_token"])

        return {
            "infra": await token("veyntora-infra-read"),
            "api": await token("veyntora-api"),
            "runtime": await token("veyntora-runtime"),
        }
