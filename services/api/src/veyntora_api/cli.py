"""Operational commands.

veyntora-api serve       run the API (uvicorn)
veyntora-api bootstrap   migrate the database, create the OpenFGA store/model and bootstrap
                         tuples, create the S3 bucket, sync Keycloak and grant the bootstrap
                         admin group. Idempotent; runs as the compose `migrate` job and as the
                         Helm/Argo CD pre-sync hook.
veyntora-api sync-identities   one full Keycloak -> Veyntora sync
veyntora-api openapi <file>    write the OpenAPI document
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import aioboto3
import httpx
import sqlalchemy as sa
import structlog
import uvicorn
from alembic import command
from alembic.config import Config

from veyntora_api.auth.identity import full_sync
from veyntora_api.auth.keycloak_admin import KeycloakAdmin
from veyntora_api.authz.fga import PLATFORM, Authz, Tuple, bootstrap_tuples, ensure_store_and_model
from veyntora_api.core.logging import configure_logging
from veyntora_api.db.models.identity import Group
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.settings import Settings, get_settings

log = structlog.get_logger()


def migrate() -> None:
    ini = get_settings().alembic_ini
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    command.upgrade(cfg, "head")


async def _ensure_bucket(s: Settings) -> None:
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key.get_secret_value(),
        aws_secret_access_key=s.s3_secret_key.get_secret_value(),
    ) as client:
        try:
            await client.head_bucket(Bucket=s.s3_bucket)
        except client.exceptions.ClientError:
            await client.create_bucket(Bucket=s.s3_bucket)
            log.info("bootstrap.bucket_created", bucket=s.s3_bucket)


async def sync_identities(s: Settings, authz: Authz) -> None:
    async with httpx.AsyncClient(timeout=15.0) as http, get_sessionmaker()() as db:
        kc = KeycloakAdmin.from_issuer(
            s.oidc_backchannel_base,
            s.keycloak_sync_client_id,
            s.keycloak_sync_client_secret.get_secret_value(),
            http,
        )
        report, delta = await full_sync(db, kc)
        await db.commit()
        await delta.apply(authz)
        log.info(
            "identity_sync.done",
            users=report.users_seen,
            groups=report.groups_seen,
            suspended=report.users_suspended,
        )


async def bootstrap(s: Settings) -> None:
    store_id, model_id = await ensure_store_and_model(
        s.openfga_url, s.openfga_store_name, s.openfga_model_path
    )
    log.info("bootstrap.openfga", store_id=store_id, model_id=model_id)
    authz = await Authz.connect(s.openfga_url, s.openfga_store_name)
    try:
        mapping = json.loads(s.openfga_model_path.with_name("bootstrap.json").read_text())
        await authz.write(bootstrap_tuples(mapping))

        async with get_sessionmaker()() as db:
            if await db.get(PlatformSettings, 1) is None:
                db.add(PlatformSettings(id=1))
                await db.commit()

        await _ensure_bucket(s)
        # Keycloak can briefly fail right after a database restart; retry with backoff.
        for attempt in range(1, 6):
            try:
                await sync_identities(s, authz)
                break
            except httpx.HTTPError as exc:
                if attempt == 5:
                    raise
                log.warning("bootstrap.identity_sync_retry", attempt=attempt, error=str(exc))
                await asyncio.sleep(2 * attempt)

        async with get_sessionmaker()() as db:
            admin_group = (
                await db.execute(
                    sa.select(Group).where(Group.keycloak_path == s.bootstrap_admin_group)
                )
            ).scalar_one_or_none()
        if admin_group is None:
            log.warning("bootstrap.admin_group_missing", path=s.bootstrap_admin_group)
        else:
            await authz.write([Tuple(f"group:{admin_group.id}#member", "platform_admin", PLATFORM)])
            log.info("bootstrap.admin_group_granted", path=s.bootstrap_admin_group)
    finally:
        await authz.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="veyntora-api")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("bootstrap")
    sub.add_parser("migrate")
    sub.add_parser("sync-identities")
    openapi = sub.add_parser("openapi")
    openapi.add_argument("output", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment != "local")
    if args.cmd == "serve":
        uvicorn.run(
            "veyntora_api.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            proxy_headers=True,
            forwarded_allow_ips="*",
            log_config=None,
        )
    elif args.cmd == "migrate":
        migrate()
    elif args.cmd == "bootstrap":
        migrate()
        asyncio.run(bootstrap(settings))
    elif args.cmd == "sync-identities":

        async def run() -> None:
            authz = await Authz.connect(settings.openfga_url, settings.openfga_store_name)
            try:
                await sync_identities(settings, authz)
            finally:
                await authz.close()

        asyncio.run(run())
    elif args.cmd == "openapi":
        from veyntora_api.main import create_app  # noqa: PLC0415 - avoid app import for other cmds

        spec = create_app(settings).openapi()
        args.output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
