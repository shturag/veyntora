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
import getpass
import json
import os
import sys
from pathlib import Path
from uuid import UUID

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
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.core.logging import configure_logging
from veyntora_api.db.models.governance import ActorType
from veyntora_api.db.models.identity import Group
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.people.service import refresh_groups
from veyntora_api.secrets.openbao import SecretWriter
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
        # Rule groups follow the attributes that just arrived.
        delta.extend(await refresh_groups(db))
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


def _cli_ctx() -> RequestContext:
    who = os.environ.get("USER") or os.environ.get("HOSTNAME") or "operator"
    return RequestContext(actor=Actor(ActorType.SYSTEM, f"cli:{who}", f"CLI ({who})"))


async def providers_cmd(s: Settings, args: argparse.Namespace) -> None:
    from pydantic import SecretStr  # noqa: PLC0415

    from veyntora_api.db.models.providers import ProviderInstance  # noqa: PLC0415
    from veyntora_api.providers.service import ProviderInput, create_provider  # noqa: PLC0415
    from veyntora_api.routers.admin_providers import TEST_QUEUE_KEY  # noqa: PLC0415

    async with get_sessionmaker()() as db:
        if args.action == "list":
            rows = (
                await db.execute(sa.select(ProviderInstance).order_by(ProviderInstance.name))
            ).scalars()
            for r in rows:
                key = (
                    f"key …{r.secret_last4}"
                    if r.secret_last4
                    else ("key set" if r.secret_ref else "no key")
                )
                sys.stdout.write(
                    f"{r.id}  {r.capability.value:<12} {r.adapter:<18} {r.hosting.value:<11} "
                    f"{r.health_status.value:<8} {key:<12} {r.name}\n"
                )
            return
        if args.action == "test":
            from redis.asyncio import Redis  # noqa: PLC0415

            redis = Redis.from_url(s.redis_url, decode_responses=True)
            row = await db.get(ProviderInstance, args.id)
            if row is None:
                raise SystemExit("provider not found")
            before = row.health_checked_at
            await redis.rpush(TEST_QUEUE_KEY, str(row.id))
            await redis.aclose()
            for _ in range(60):
                await asyncio.sleep(1)
                await db.refresh(row)
                if row.health_checked_at != before:
                    sys.stdout.write(
                        f"{row.health_status.value}: {row.health_detail or 'all checks passed'}\n"
                    )
                    return
            raise SystemExit("no worker picked up the test within 60 s")
        secret: SecretStr | None = None
        if args.secret_stdin:
            secret = SecretStr(sys.stdin.readline().strip())
        elif args.ask_secret:
            secret = SecretStr(getpass.getpass("API key (input hidden): ").strip())
        data = ProviderInput(
            capability=args.capability,
            adapter=args.adapter,
            name=args.name,
            endpoint=args.endpoint,
            model=args.model,
            hosting=args.hosting,
            region=args.region,
            options=json.loads(args.options or "{}"),
            secret=secret,
        )
        writer = (
            SecretWriter.from_token_file(s.openbao_url, s.openbao_token_file, s.openbao_kv_mount)
            if secret is not None
            else None
        )
        try:
            row = await create_provider(db, _cli_ctx(), writer, data)
            await db.commit()
        finally:
            if writer is not None:
                await writer.close()
        sys.stdout.write(f"created {row.id} ({row.capability.value}/{row.adapter})\n")


def _parser() -> argparse.ArgumentParser:
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
    prov = sub.add_parser("providers")
    psub = prov.add_subparsers(dest="action", required=True)
    psub.add_parser("list")
    ptest = psub.add_parser("test")
    ptest.add_argument("id", type=UUID)
    padd = psub.add_parser("add")
    padd.add_argument("--capability", required=True)
    padd.add_argument("--adapter", required=True)
    padd.add_argument("--name", required=True)
    padd.add_argument("--hosting", required=True, choices=["self_hosted", "external"])
    padd.add_argument("--endpoint")
    padd.add_argument("--model")
    padd.add_argument("--region")
    padd.add_argument("--options", help="JSON object")
    key = padd.add_mutually_exclusive_group()
    key.add_argument("--ask-secret", action="store_true", help="prompt for the key (hidden)")
    key.add_argument("--secret-stdin", action="store_true", help="read the key from stdin")
    return parser


def main() -> None:
    args = _parser().parse_args()

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
    elif args.cmd == "providers":
        asyncio.run(providers_cmd(settings, args))
    elif args.cmd == "openapi":
        from veyntora_api.main import create_app  # noqa: PLC0415 - avoid app import for other cmds

        spec = create_app(settings).openapi()
        args.output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
