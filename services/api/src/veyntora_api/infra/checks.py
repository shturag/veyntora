""" "Test connection" for the six services (Setup page, Admin -> Infrastructure).

Each check signs in the way Veyntora will, so a wrong password or a missing right is found
before anything is saved. Details say what is wrong, never a password.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aioboto3
import asyncpg
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import SecretStr
from redis.asyncio import Redis
from redis.exceptions import RedisError

from veyntora_api.auth.identity_check import check_identity
from veyntora_api.infra import config as c
from veyntora_api.infra.vault import VaultError, check_admin, check_token
from veyntora_api.settings import Settings

_LIMIT_S = 8.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    ok: bool
    detail: str


class CheckFailedError(RuntimeError):
    pass


async def _pg(pg: c.Postgres, user: str, password: str, database: str) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(
            host=pg.host,
            port=pg.port,
            user=user,
            password=password,
            database=database,
            ssl="require" if pg.ssl else False,
            timeout=5,
        )
    except asyncpg.InvalidPasswordError as exc:
        raise CheckFailedError(f"PostgreSQL refused the password for {user}") from exc
    except asyncpg.InvalidCatalogNameError as exc:
        raise CheckFailedError(f"PostgreSQL has no database {database}") from exc
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        raise CheckFailedError(
            f"cannot reach PostgreSQL at {pg.host}:{pg.port} as {user} ({type(exc).__name__})"
        ) from exc


async def postgres(pg: c.Postgres, pw: dict[str, str]) -> str:
    conn = await _pg(pg, pg.owner_user, pw["postgres-owner-password"], pg.database)
    try:
        version = await conn.fetchval("SHOW server_version_num")
        can_create = await conn.fetchval(
            "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
        )
    finally:
        await conn.close()
    if int(version) < 160000:
        raise CheckFailedError("Veyntora needs PostgreSQL 16 or later")
    if not can_create:
        raise CheckFailedError(f"{pg.owner_user} may not create tables in {pg.database}")
    conn = await _pg(pg, pg.user, pw["postgres-password"], pg.database)
    await conn.close()
    conn = await _pg(pg, pg.aegra_user, pw["postgres-aegra-password"], pg.aegra_database)
    await conn.close()
    return f"signed in as {pg.owner_user}, {pg.user} and {pg.aegra_user}"


async def valkey(v: c.Valkey, pw: dict[str, str]) -> str:
    client = Redis(
        host=v.host,
        port=v.port,
        username=v.username or None,
        password=pw.get("valkey-password") or None,
        db=v.db,
        ssl=v.tls,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    try:
        await client.ping()
        info = await client.info("server")
    except RedisError as exc:
        text = str(exc).lower()
        if "auth" in text or "password" in text or "noperm" in text:
            raise CheckFailedError("Valkey refused the user name or password") from exc
        raise CheckFailedError(
            f"cannot reach Valkey at {v.host}:{v.port} ({type(exc).__name__})"
        ) from exc
    finally:
        await client.aclose()
    name = "Valkey" if "valkey_version" in info else "Redis"
    return f"{name} {info.get('valkey_version') or info.get('redis_version', '')} answered".strip()


async def s3(s: c.S3, pw: dict[str, str]) -> str:
    session = aioboto3.Session()
    notes = []
    try:
        async with session.client(
            "s3",
            endpoint_url=s.endpoint,
            region_name=s.region,
            aws_access_key_id=s.access_key,
            aws_secret_access_key=pw["s3-secret-key"],
        ) as client:
            for bucket in (s.bucket, s.audit_bucket):
                try:
                    await client.head_bucket(Bucket=bucket)
                except ClientError as exc:
                    code = str(exc.response.get("Error", {}).get("Code", ""))
                    if code in ("404", "NoSuchBucket", "NotFound"):
                        notes.append(f"{bucket} will be created")
                        continue
                    if code in (
                        "403",
                        "AccessDenied",
                        "InvalidAccessKeyId",
                        "SignatureDoesNotMatch",
                    ):
                        raise CheckFailedError(
                            f"S3 refused the keys for bucket {bucket} ({code})"
                        ) from exc
                    raise
    except (BotoCoreError, OSError) as exc:
        raise CheckFailedError(f"cannot reach S3 at {s.endpoint} ({type(exc).__name__})") from exc
    except ClientError as exc:
        raise CheckFailedError(f"S3 answered with an error ({type(exc).__name__})") from exc
    return "buckets reachable" + (f"; {', '.join(notes)}" if notes else "")


async def openfga(f: c.OpenFga, http: httpx.AsyncClient) -> str:
    try:
        res = await http.get(f"{f.url}/healthz")
        if res.status_code != 200:
            raise CheckFailedError(f"OpenFGA is not healthy (HTTP {res.status_code})")
        stores = await http.get(f"{f.url}/stores")
    except httpx.HTTPError as exc:
        raise CheckFailedError(f"cannot reach OpenFGA at {f.url} ({type(exc).__name__})") from exc
    if stores.status_code in (401, 403):
        raise CheckFailedError("OpenFGA asks for credentials; Veyntora connects without")
    names = [s.get("name") for s in (stores.json().get("stores") or [])]
    return (
        f"store {f.store_name} found"
        if f.store_name in names
        else f"store {f.store_name} will be created"
    )


async def openbao(
    b: c.OpenBao, *, admin_token: str | None = None, tokens: dict[str, str] | None = None
) -> str:
    """With an admin token: it may set Veyntora up. With issued tokens: they still work."""
    try:
        if admin_token:
            await check_admin(b.url, admin_token, b.kv_mount)
            return "the token may create Veyntora's policies and tokens (it is not stored)"
        for name, token in (tokens or {}).items():
            try:
                await check_token(b.url, token)
            except VaultError as exc:
                raise CheckFailedError(f"{name} token: {exc}") from exc
    except VaultError as exc:
        raise CheckFailedError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise CheckFailedError(f"cannot reach OpenBao at {b.url} ({type(exc).__name__})") from exc
    return "Veyntora's tokens are accepted"


async def keycloak(k: c.Keycloak, pw: dict[str, str], http: httpx.AsyncClient) -> str:
    settings = Settings(
        oidc_issuer=k.issuer,
        oidc_internal_base=k.internal_base or None,
        oidc_client_id=k.client_id,
        oidc_client_secret=SecretStr(pw["keycloak-client-secret"]),
        keycloak_sync_client_id=k.sync_client_id,
        keycloak_sync_client_secret=SecretStr(pw["keycloak-sync-client-secret"]),
    )
    try:
        problems = await check_identity(settings, http)
        if not problems:
            # The sign-in client's secret: a made-up code must fail as "invalid_grant" (the
            # client was accepted), not "invalid_client".
            res = await http.post(
                f"{k.backchannel}/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "veyntora-setup-check",
                    "redirect_uri": "http://localhost/",
                    "client_id": k.client_id,
                    "client_secret": pw["keycloak-client-secret"],
                },
            )
            if res.status_code == 401 or "invalid_client" in res.text:
                problems.append(f"Keycloak refused the secret of client {k.client_id}")
    except httpx.HTTPError as exc:
        raise CheckFailedError(
            f"cannot reach Keycloak at {k.backchannel} ({type(exc).__name__})"
        ) from exc
    if problems:
        raise CheckFailedError("; ".join(problems))
    return f"realm found; clients {k.client_id} and {k.sync_client_id} accepted"


async def run(
    section: c.Section,
    passwords: dict[str, str],
    *,
    admin_token: str | None = None,
    tokens: dict[str, str] | None = None,
) -> CheckResult:
    async def go() -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0)) as http:
            match section:
                case c.Postgres():
                    return await postgres(section, passwords)
                case c.Valkey():
                    return await valkey(section, passwords)
                case c.S3():
                    return await s3(section, passwords)
                case c.OpenFga():
                    return await openfga(section, http)
                case c.OpenBao():
                    return await openbao(section, admin_token=admin_token, tokens=tokens)
                case c.Keycloak():
                    return await keycloak(section, passwords, http)
            raise CheckFailedError("unknown service")

    try:
        return CheckResult(True, await asyncio.wait_for(go(), _LIMIT_S))
    except CheckFailedError as exc:
        return CheckResult(False, str(exc))
    except TimeoutError:
        return CheckResult(False, f"no answer within {_LIMIT_S:.0f} s")
    except KeyError as exc:
        return CheckResult(False, f"missing {exc.args[0]}")
