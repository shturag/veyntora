"""The infrastructure config file (ADR 0034).

Veyntora needs six services before it can read anything from PostgreSQL, so their settings
live in a file on the `config` volume, not in the database:

- addresses and user names, in plain JSON;
- passwords in OpenBao, at kv/veyntora/infra/<name>; the file names the version in use, so
  restoring an earlier file brings back the passwords it was saved with;
- the three OpenBao tokens, each encrypted for the services that may hold it (keys.py).

Every save is a new version; earlier ones are kept in history/ and can be restored. The
launcher in each container restarts its service when the version changes.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from veyntora_api.infra import keys

CONFIG_DIR_ENV = "VEY_CONFIG_DIR"
DEFAULT_DIR = Path("/var/lib/veyntora")
_HISTORY_KEEP = 20

Service = Literal["postgres", "valkey", "s3", "openbao", "openfga", "keycloak"]
SERVICES: tuple[Service, ...] = ("postgres", "valkey", "s3", "openbao", "openfga", "keycloak")

Host = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")]
Port = Annotated[int, Field(ge=1, le=65535)]
Name = Annotated[str, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_.-]+$")]


def _http_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?(/[^\s]*)?", value):
        raise ValueError("must be an http:// or https:// address")
    return value


HttpUrl = Annotated[str, Field(max_length=1024), AfterValidator(_http_url)]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @property
    def address(self) -> str:
        raise NotImplementedError


class Postgres(Section):
    host: Host
    port: Port = 5432
    database: Name = "veyntora"
    # The services use the runtime role (rows only); migrations run as the owner.
    user: Name = "veyntora_runtime"
    owner_user: Name = "veyntora"
    aegra_database: Name = "aegra"
    aegra_user: Name = "aegra"
    ssl: bool = False

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"


class Valkey(Section):
    host: Host
    port: Port = 6379
    username: Annotated[str, Field(max_length=63, pattern=r"^[A-Za-z0-9_.-]*$")] = ""
    db: Annotated[int, Field(ge=0, le=15)] = 0
    graphs_db: Annotated[int, Field(ge=0, le=15)] = 2
    tls: bool = False

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


class S3(Section):
    endpoint: HttpUrl
    region: Annotated[str, Field(min_length=1, max_length=32)] = "eu-central-1"
    bucket: Name = "veyntora"
    audit_bucket: Name = "veyntora-audit"
    access_key: Annotated[str, Field(min_length=1, max_length=128)]

    @property
    def address(self) -> str:
        return self.endpoint


class OpenBao(Section):
    url: HttpUrl
    kv_mount: Name = "kv"

    @property
    def address(self) -> str:
        return self.url


class OpenFga(Section):
    url: HttpUrl
    store_name: Name = "veyntora"

    @property
    def address(self) -> str:
        return self.url


class Keycloak(Section):
    # The issuer as browsers reach it; the internal base as the containers do (optional).
    issuer: HttpUrl
    internal_base: str = ""
    client_id: Name = "veyntora"
    sync_client_id: Name = "veyntora-sync"

    @field_validator("internal_base")
    @classmethod
    def _base(cls, v: str) -> str:
        return _http_url(v) if v.strip() else ""

    @property
    def address(self) -> str:
        return self.issuer

    @property
    def backchannel(self) -> str:
        return self.internal_base or self.issuer


SECTIONS: dict[Service, type[Section]] = {
    "postgres": Postgres,
    "valkey": Valkey,
    "s3": S3,
    "openbao": OpenBao,
    "openfga": OpenFga,
    "keycloak": Keycloak,
}

# The passwords each service has; stored in OpenBao at kv/veyntora/infra/<service>-<name>.
SECRETS: dict[Service, tuple[str, ...]] = {
    "postgres": ("password", "owner_password", "aegra_password"),
    "valkey": ("password",),
    "s3": ("secret_key",),
    "openbao": (),
    "openfga": (),
    "keycloak": ("client_secret", "sync_client_secret"),
}
# Generated at setup, never typed: signs API -> graph server tokens (ADR 0020).
INTERNAL_TOKEN = "internal-token"  # noqa: S105 - a name, not a value


def secret_name(service: Service, field: str) -> str:
    return f"{service}-{field.replace('_', '-')}"


def secret_path(name: str) -> str:
    return f"veyntora/infra/{name}"


class SecretMeta(BaseModel):
    version: int
    last4: str | None


class Tokens(BaseModel):
    """The OpenBao tokens, each encrypted for its holders (keys.py)."""

    infra: str
    api: str
    runtime: str
    # Last 4 characters, for the Infrastructure page.
    last4: dict[str, str] = Field(default_factory=dict)


class InfraConfig(BaseModel):
    format: Literal[1] = 1
    version: int = 1
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    saved_by: str = ""
    changed: list[Service] = Field(default_factory=list)
    postgres: Postgres
    valkey: Valkey
    s3: S3
    openbao: OpenBao
    openfga: OpenFga
    keycloak: Keycloak
    secrets: dict[str, SecretMeta] = Field(default_factory=dict)
    tokens: Tokens

    def section(self, service: Service) -> Section:
        section: Section = getattr(self, service)
        return section

    def summary(self) -> dict[str, Any]:
        """Everything but the tokens: what the history and the audit log show."""
        return self.model_dump(mode="json", exclude={"tokens"})


class Bootstrapped(BaseModel):
    """What migrate last did with a config version (it writes this file)."""

    version: str
    ok: bool
    error: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Store:
    """The config volume: infra.json, its history, migrate's marker and the setup code."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.environ.get(CONFIG_DIR_ENV) or DEFAULT_DIR)

    @property
    def current(self) -> Path:
        return self.root / "infra.json"

    @property
    def history(self) -> Path:
        return self.root / "history"

    @property
    def marker(self) -> Path:
        return self.root / "bootstrapped.json"

    @property
    def setup_code(self) -> Path:
        return self.root / "setup-code"

    @property
    def set_up_flag(self) -> Path:
        """Written once the API first ran set up: from then on the Setup page only offers
        going back to an earlier version, and changes are made in the console."""
        return self.root / "set-up"

    def is_set_up(self) -> bool:
        return self.set_up_flag.exists()

    def mark_set_up(self) -> None:
        if not self.is_set_up():
            _write(self.set_up_flag, datetime.now(UTC).isoformat())

    def load(self) -> InfraConfig | None:
        try:
            return InfraConfig.model_validate_json(self.current.read_text())
        except FileNotFoundError:
            return None

    def version_tag(self) -> str | None:
        """The current version as the launchers compare it, or None when not set up."""
        cfg = self.load()
        return f"file:{cfg.version}" if cfg else None

    def save(self, cfg: InfraConfig) -> InfraConfig:
        """Write `cfg` as the next version and keep it in the history."""
        previous = self.load()
        cfg = cfg.model_copy(
            update={
                "version": (previous.version + 1) if previous else 1,
                "saved_at": datetime.now(UTC),
            }
        )
        self.history.mkdir(parents=True, exist_ok=True)
        text = cfg.model_dump_json(indent=2)
        _write(self.history / f"infra.{cfg.version}.json", text)
        _write(self.current, text)
        for old in sorted(self.history.glob("infra.*.json"), key=_version_of)[:-_HISTORY_KEEP]:
            old.unlink(missing_ok=True)
        return cfg

    def versions(self) -> list[InfraConfig]:
        """Earlier versions, newest first."""
        out = []
        for path in sorted(self.history.glob("infra.*.json"), key=_version_of, reverse=True):
            try:
                out.append(InfraConfig.model_validate_json(path.read_text()))
            except ValueError:
                continue
        return out

    def get_version(self, version: int) -> InfraConfig | None:
        path = self.history / f"infra.{version}.json"
        return InfraConfig.model_validate_json(path.read_text()) if path.exists() else None

    def read_marker(self) -> Bootstrapped | None:
        try:
            return Bootstrapped.model_validate_json(self.marker.read_text())
        except (FileNotFoundError, ValueError):
            return None

    def write_marker(self, marker: Bootstrapped) -> None:
        _write(self.marker, marker.model_dump_json())


def _version_of(path: Path) -> int:
    match = re.search(r"\.(\d+)\.json$", path.name)
    return int(match.group(1)) if match else 0


def _write(path: Path, text: str) -> None:
    """Atomic, owner-only: readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    tmp.replace(path)


# --- What each service is started with ------------------------------------------------

Role = Literal["api", "owner", "runtime", "graphs", "scheduler"]
# Which OpenBao token each role holds. The scheduler only enqueues tasks: none.
ROLE_TOKEN: dict[Role, Literal["api", "runtime"] | None] = {
    "api": "api",
    "owner": "api",
    "runtime": "runtime",
    "graphs": "runtime",
    "scheduler": None,
}
# The config keys a role keeps after its launcher started it. Only the API saves the
# config (Infrastructure page), so only it keeps keys, and never the runtime private key.
ROLE_KEYS: dict[Role, tuple[str, ...]] = {
    "api": (keys.SHARED, keys.API, keys.RUNTIME_PUBLIC),
    "owner": (),
    "runtime": (),
    "graphs": (),
    "scheduler": (),
}


def encrypt_tokens(infra: str, api: str, runtime: str) -> Tokens:
    from veyntora_api.secrets.openbao import last4  # noqa: PLC0415

    return Tokens(
        infra=keys.encrypt(keys.SHARED, infra),
        api=keys.encrypt(keys.API, api),
        runtime=keys.seal(runtime),
        last4={
            k: v
            for k, v in (("infra", last4(infra)), ("api", last4(api)), ("runtime", last4(runtime)))
            if v
        },
    )


def infra_token(cfg: InfraConfig) -> str:
    return keys.decrypt(keys.SHARED, cfg.tokens.infra)


def role_token(cfg: InfraConfig, role: Role) -> str | None:
    kind = ROLE_TOKEN[role]
    if kind == "api":
        return keys.decrypt(keys.API, cfg.tokens.api)
    if kind == "runtime":
        return keys.unseal(cfg.tokens.runtime)
    return None


def _pg_url(pg: Postgres, user: str, password: str, database: str, driver: str) -> str:
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}"
    url = f"{driver}://{auth}@{pg.host}:{pg.port}/{database}"
    if pg.ssl:
        url += "?ssl=require" if "asyncpg" in driver else "?sslmode=require"
    return url


def _redis_url(v: Valkey, password: str, db: int) -> str:
    scheme = "rediss" if v.tls else "redis"
    auth = (
        f"{quote(v.username, safe='')}:{quote(password, safe='')}@"
        if (password or v.username)
        else ""
    )
    return f"{scheme}://{auth}{v.host}:{v.port}/{db}"


def service_env(cfg: InfraConfig, role: Role, passwords: dict[str, str]) -> dict[str, str]:
    """The VEY_* settings a role runs with. `passwords` by secret name (secret_name())."""
    pg, kc = cfg.postgres, cfg.keycloak
    db_user, db_password = (
        (pg.owner_user, passwords["postgres-owner-password"])
        if role == "owner"
        else (pg.user, passwords["postgres-password"])
    )
    env = {
        "VEY_DATABASE_URL": _pg_url(pg, db_user, db_password, pg.database, "postgresql+asyncpg"),
        "VEY_REDIS_URL": _redis_url(
            cfg.valkey, passwords.get("valkey-password", ""), cfg.valkey.db
        ),
        "VEY_S3_ENDPOINT": cfg.s3.endpoint,
        "VEY_S3_REGION": cfg.s3.region,
        "VEY_S3_BUCKET": cfg.s3.bucket,
        "VEY_AUDIT_ARCHIVE_BUCKET": cfg.s3.audit_bucket,
        "VEY_S3_ACCESS_KEY": cfg.s3.access_key,
        "VEY_S3_SECRET_KEY": passwords["s3-secret-key"],
        "VEY_OPENFGA_URL": cfg.openfga.url,
        "VEY_OPENFGA_STORE_NAME": cfg.openfga.store_name,
        "VEY_OPENBAO_URL": cfg.openbao.url,
        "VEY_OPENBAO_KV_MOUNT": cfg.openbao.kv_mount,
        "VEY_OIDC_ISSUER": kc.issuer,
        "VEY_OIDC_INTERNAL_BASE": kc.internal_base,
        "VEY_OIDC_CLIENT_ID": kc.client_id,
        "VEY_OIDC_CLIENT_SECRET": passwords["keycloak-client-secret"],
        "VEY_KEYCLOAK_SYNC_CLIENT_ID": kc.sync_client_id,
        "VEY_KEYCLOAK_SYNC_CLIENT_SECRET": passwords["keycloak-sync-client-secret"],
        "VEY_INTERNAL_TOKEN_SECRET": passwords[INTERNAL_TOKEN],
    }
    if role == "graphs":
        # The graph server's own database (threads, checkpoints) and Valkey database.
        env["DATABASE_URL"] = _pg_url(
            pg, pg.aegra_user, passwords["postgres-aegra-password"], pg.aegra_database, "postgresql"
        )
        env["REDIS_URL"] = _redis_url(
            cfg.valkey, passwords.get("valkey-password", ""), cfg.valkey.graphs_db
        )
    return env


def all_secret_names() -> list[str]:
    return [secret_name(s, f) for s in SERVICES for f in SECRETS[s]] + [INTERNAL_TOKEN]
