"""The infrastructure set up in the browser (ADR 0034): the config file and its keys, what
each service is started with, the launcher's decisions and the Setup page's API."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from veyntora_api.db.schema import SCHEMA_HEAD
from veyntora_api.infra import config as c
from veyntora_api.infra import keys, launcher, service
from veyntora_api.infra.checks import CheckResult
from veyntora_api.infra.setup_app import create_setup_app
from veyntora_api.secrets.openbao import SecretRef, SecretWriter
from veyntora_api.settings import get_settings

PASSWORDS = {
    "postgres-password": "runtime p@ss/word",
    "postgres-owner-password": "owner-secret-0123456789",
    "postgres-aegra-password": "aegra-secret-0123456789",
    "valkey-password": "valkey:secret",
    "s3-secret-key": "s3-secret-0123456789abcdef",
    "keycloak-client-secret": "kc-client-0123456789abcdef",
    "keycloak-sync-client-secret": "kc-sync-0123456789abcdef",
    c.INTERNAL_TOKEN: "internal-0123456789abcdef0123456789",
}
TOKENS = {
    "infra": "hvs.infra-token-0001",
    "api": "hvs.api-token-00002",
    "runtime": "hvs.rt-token-000003",
}


@pytest.fixture(autouse=True)
def config_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    generated = keys.generate()
    for name, value in generated.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(c.CONFIG_DIR_ENV, str(tmp_path / "config"))
    for name in launcher._ENV_INFRA:
        monkeypatch.delenv(name, raising=False)
    return generated


def sections() -> dict[str, Any]:
    return {
        "postgres": {"host": "db.internal", "port": 5433},
        "valkey": {"host": "cache.internal", "port": 6380},
        "s3": {"endpoint": "http://s3.internal:8333/", "access_key": "veyntora"},
        "openbao": {"url": "http://bao.internal:8200"},
        "openfga": {"url": "http://fga.internal:8080"},
        "keycloak": {
            "issuer": "http://localhost:8180/realms/veyntora",
            "internal_base": "http://kc.internal:8080/realms/veyntora",
        },
    }


def a_config(**overrides: Any) -> c.InfraConfig:
    data = sections() | overrides
    return c.InfraConfig(
        **{s: c.SECTIONS[s].model_validate(data[s]) for s in c.SERVICES},
        secrets={n: c.SecretMeta(version=1, last4=v[-4:]) for n, v in PASSWORDS.items()},
        tokens=c.encrypt_tokens(TOKENS["infra"], TOKENS["api"], TOKENS["runtime"]),
    )


# --- keys ---------------------------------------------------------------------------------


def test_each_token_opens_only_with_its_holders_key(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = a_config()
    raw = cfg.tokens.model_dump_json()
    assert all(t not in raw for t in TOKENS.values())
    assert c.infra_token(cfg) == TOKENS["infra"]
    assert c.role_token(cfg, "api") == TOKENS["api"]
    assert c.role_token(cfg, "runtime") == TOKENS["runtime"]
    assert c.role_token(cfg, "scheduler") is None

    # The API seals the runtime token but cannot open it: it has no private key.
    monkeypatch.delenv(keys.RUNTIME_PRIVATE)
    with pytest.raises(keys.ConfigKeyError, match=keys.RUNTIME_PRIVATE):
        c.role_token(cfg, "runtime")
    # The runtime services cannot open the API token without the API's key.
    monkeypatch.setenv(keys.API, keys.generate()[keys.API])
    with pytest.raises(keys.ConfigKeyError, match="does not open"):
        c.role_token(cfg, "api")


# --- the file -----------------------------------------------------------------------------


def test_saving_keeps_versions_owner_only_and_restorable() -> None:
    store = c.Store()
    first = store.save(a_config())
    second = store.save(first.model_copy(update={"valkey": c.Valkey(host="cache2", port=6379)}))
    assert (first.version, second.version) == (1, 2)
    assert store.load() == second
    assert stat.S_IMODE(store.current.stat().st_mode) == 0o600
    assert [v.version for v in store.versions()] == [2, 1]
    assert store.version_tag() == "file:2"
    text = store.current.read_text()
    assert all(p not in text for p in PASSWORDS.values())  # passwords live in OpenBao

    restored = service.restore(second, store, 1, saved_by="Ada")
    assert restored.version == 3
    assert restored.valkey == first.valkey
    assert restored.changed == ["valkey"]
    with pytest.raises(service.InfraError, match="no longer kept"):
        service.restore(restored, store, 99, saved_by="Ada")


def test_settings_are_checked() -> None:
    with pytest.raises(ValueError, match="http"):
        c.S3(endpoint="s3.internal:8333", access_key="k")
    with pytest.raises(ValueError, match="pattern"):
        c.Postgres(host="db; rm -rf /")
    assert c.S3(endpoint="http://s3:8333/", access_key="k").endpoint == "http://s3:8333"


# --- what each role runs with ------------------------------------------------------------


def test_service_env_by_role() -> None:
    cfg = a_config(postgres={"host": "db.internal", "port": 5433, "ssl": True})
    api = c.service_env(cfg, "api", PASSWORDS)
    # Passwords are URL-quoted; the runtime role connects for the services.
    assert api["VEY_DATABASE_URL"] == (
        "postgresql+asyncpg://veyntora_runtime:runtime%20p%40ss%2Fword@db.internal:5433/veyntora"
        "?ssl=require"
    )
    assert api["VEY_REDIS_URL"] == "redis://:valkey%3Asecret@cache.internal:6380/0"
    assert api["VEY_OIDC_INTERNAL_BASE"] == "http://kc.internal:8080/realms/veyntora"
    assert "DATABASE_URL" not in api

    owner = c.service_env(cfg, "owner", PASSWORDS)
    assert owner["VEY_DATABASE_URL"].startswith("postgresql+asyncpg://veyntora:owner-secret")

    graphs = c.service_env(cfg, "graphs", PASSWORDS)
    assert graphs["DATABASE_URL"] == (
        "postgresql://aegra:aegra-secret-0123456789@db.internal:5433/aegra?sslmode=require"
    )
    assert graphs["REDIS_URL"].endswith("/2")


def test_only_the_api_keeps_config_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEY_PUBLIC_BASE_URL", "http://localhost:3000")
    api = launcher.Launcher("api", ["true"]).base_env()
    assert {keys.SHARED, keys.API, keys.RUNTIME_PUBLIC} <= set(api)
    assert keys.RUNTIME_PRIVATE not in api
    for role in ("owner", "runtime", "graphs", "scheduler"):
        env = launcher.Launcher(role, ["true"]).base_env()  # type: ignore[arg-type]
        assert not set(keys.ALL) & set(env), role
        assert env["VEY_PUBLIC_BASE_URL"] == "http://localhost:3000"


# --- the launcher ------------------------------------------------------------------------


def test_launcher_plans() -> None:
    store = c.Store()
    plan = {r: launcher.Launcher(r, ["true"], store).plan() for r in c.ROLE_TOKEN}  # type: ignore[arg-type]
    assert plan["api"] == launcher.Plan("setup", None)
    assert plan["owner"].mode == plan["runtime"].mode == "wait"

    store.save(a_config())
    plan = {r: launcher.Launcher(r, ["true"], store).plan() for r in c.ROLE_TOKEN}  # type: ignore[arg-type]
    assert plan["api"] == launcher.Plan("setup", f"file:1+{SCHEMA_HEAD}")  # "starting"
    assert plan["owner"] == launcher.Plan("bootstrap", f"file:1+{SCHEMA_HEAD}")
    assert plan["graphs"].mode == "wait"

    store.write_marker(c.Bootstrapped(version=f"file:1+{SCHEMA_HEAD}", ok=True))
    plan = {r: launcher.Launcher(r, ["true"], store).plan() for r in c.ROLE_TOKEN}  # type: ignore[arg-type]
    assert plan["owner"].mode == "idle"
    assert plan["api"] == plan["runtime"] == launcher.Plan("service", f"file:1+{SCHEMA_HEAD}")

    # A new version: everything waits for migrate again.
    store.save(a_config())
    assert launcher.Launcher("runtime", ["true"], store).plan() == launcher.Plan(
        "wait", f"file:2+{SCHEMA_HEAD}"
    )


def test_env_mode_needs_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEY_DATABASE_URL", "postgresql+asyncpg://u:p@db/veyntora")
    tag = launcher.env_tag()
    assert tag and tag.startswith("env:")
    assert launcher.Launcher("owner", ["true"]).plan() == launcher.Plan(
        "bootstrap", f"{tag}+{SCHEMA_HEAD}"
    )
    monkeypatch.setenv("VEY_REDIS_URL", "redis://cache:6379/0")
    assert launcher.env_tag() != tag
    # The owner (migrate) and the runtime services sign in as different database users and
    # must agree on the version, or the services wait for a bootstrap that never comes.
    tag = launcher.env_tag()
    monkeypatch.setenv("VEY_DATABASE_URL", "postgresql+asyncpg://owner:secret@db/veyntora")
    assert launcher.env_tag() == tag
    monkeypatch.setenv("VEY_DATABASE_URL", "postgresql+asyncpg://u:p@other-db/veyntora")
    assert launcher.env_tag() != tag


def test_owner_records_what_bootstrap_did(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEY_DATABASE_URL", "postgresql+asyncpg://u:p@db/veyntora")
    store = c.Store()
    fail = launcher.Launcher(
        "owner",
        [
            sys.executable,
            "-c",
            "print('error: redis://:hunter2@cache refused'); raise SystemExit(3)",
        ],
        store,
    )
    monkeypatch.setattr(launcher, "_RETRY_S", 0.0)
    while (marker := store.read_marker()) is None:
        assert fail.tick() is None
    assert not marker.ok
    assert "hunter2" not in marker.error
    assert "refused" in marker.error

    ok = launcher.Launcher("owner", [sys.executable, "-c", "pass"], store)
    while not ((m := store.read_marker()) and m.ok):
        assert ok.tick() is None
    assert ok.plan().mode == "idle"


def test_file_mode_starts_with_passwords_from_openbao(monkeypatch: pytest.MonkeyPatch) -> None:
    store = c.Store()
    store.save(a_config())
    store.write_marker(c.Bootstrapped(version=f"file:1+{SCHEMA_HEAD}", ok=True))
    asked: dict[str, Any] = {}

    async def read(url: str, token: str, mount: str, versions: dict[str, int]) -> dict[str, str]:
        asked.update(url=url, token=token, versions=versions)
        return PASSWORDS

    async def renew(url: str, token: str) -> None:
        return None

    monkeypatch.setattr(launcher.vault, "read_passwords", read)
    monkeypatch.setattr(launcher.vault, "renew", renew)
    run = launcher.Launcher("runtime", ["true"], store)
    env = run.env_for(run.plan())
    assert asked["token"] == TOKENS["infra"]
    assert asked["versions"]["postgres-password"] == 1
    assert Path(env["VEY_OPENBAO_TOKEN_FILE"]).read_text() == TOKENS["runtime"]
    assert stat.S_IMODE(Path(env["VEY_OPENBAO_TOKEN_FILE"]).stat().st_mode) == 0o600
    assert not set(keys.ALL) & set(env)


def test_scrub() -> None:
    line = "OperationalError: postgresql://veyntora:s3cr3t@db:5432 hvs.CAESIJ0123456789abcdefghij"
    out = launcher.scrub(line)
    assert "s3cr3t" not in out
    assert "hvs.CAESIJ0123456789abcdefghij" not in out


# --- the Setup page's API -----------------------------------------------------------------


def _setup_body(code: str) -> dict[str, Any]:
    return sections() | {
        "code": code,
        "secrets": {k: v for k, v in PASSWORDS.items() if k != c.INTERNAL_TOKEN},
        "openbao_admin_token": "hvs.root-token-0000",
    }


class Writer:
    stored: ClassVar[dict[str, str]] = {}

    def __init__(self, url: str, token: str, mount: str = "kv") -> None:
        self.token = token

    async def put(self, path: str, value: str, expires_at: object = None) -> SecretRef:
        SecretWriter._check(self, path)  # type: ignore[arg-type]
        Writer.stored[path] = value
        return SecretRef(ref=f"kv/{path}", last4=value[-4:], expires_at=None, version=4)

    async def close(self) -> None:
        return None


def test_setup_needs_the_code_and_saves_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    store = c.Store()
    client = TestClient(create_setup_app(store))
    code = store.setup_code.read_text()
    assert client.get("/v1/setup").json()["state"] == "setup"
    assert client.get("/v1/me").status_code == 503

    assert client.post("/v1/setup/code", json={"code": "wrong"}).status_code == 403
    assert client.post("/v1/setup/code", json={"code": code.upper()}).status_code == 204

    async def failing(*_a: Any, **_k: Any) -> dict[str, service.CheckOut]:
        out = {s: service.CheckOut(ok=True, detail="fine") for s in c.SERVICES}
        out["valkey"] = service.CheckOut(ok=False, detail="Valkey refused the password")
        return out

    monkeypatch.setattr(service, "check_all", failing)
    res = client.post("/v1/setup", json=_setup_body(code))
    assert res.json()["results"] == {
        "valkey": {"ok": False, "detail": "Valkey refused the password"}
    }
    assert store.load() is None

    async def passing(*_a: Any, **_k: Any) -> dict[str, service.CheckOut]:
        return {s: service.CheckOut(ok=True, detail="fine") for s in c.SERVICES}

    async def provision(url: str, admin: str, mount: str) -> dict[str, str]:
        assert admin == "hvs.root-token-0000"
        return TOKENS

    monkeypatch.setattr(service, "check_all", passing)
    monkeypatch.setattr(service.vault, "provision", provision)
    monkeypatch.setattr(service, "SecretWriter", Writer)
    res = client.post("/v1/setup", json=_setup_body(code))
    assert res.json() == {"state": "starting", "results": None}

    cfg = store.load()
    assert cfg is not None and cfg.version == 1
    text = store.current.read_text()
    for secret in [*PASSWORDS.values(), *TOKENS.values(), "hvs.root-token-0000"]:
        assert secret not in text
    assert Writer.stored["veyntora/infra/postgres-password"] == PASSWORDS["postgres-password"]
    assert len(Writer.stored[f"veyntora/infra/{c.INTERNAL_TOKEN}"]) >= 48
    assert cfg.secrets["s3-secret-key"] == c.SecretMeta(version=4, last4="cdef")
    assert client.get("/v1/setup").json()["state"] == "starting"

    store.write_marker(
        c.Bootstrapped(version=f"file:1+{SCHEMA_HEAD}", ok=False, error="realm missing")
    )
    state = client.get("/v1/setup").json()
    assert (state["state"], state["error"]) == ("failed", "realm missing")
    assert state["saved"]["postgres"]["host"] == "db.internal"
    assert "password" not in json.dumps(state["saved"])

    store.write_marker(c.Bootstrapped(version=f"file:1+{SCHEMA_HEAD}", ok=True))
    assert client.get("/v1/setup").json()["state"] == "ready"
    # Once the API ran set up, the Setup page no longer takes settings.
    store.mark_set_up()
    assert client.post("/v1/setup", json=_setup_body(code)).status_code == 409


def test_after_a_failed_change_the_setup_page_goes_back(monkeypatch: pytest.MonkeyPatch) -> None:
    store = c.Store()
    store.save(a_config())
    store.mark_set_up()
    store.save(a_config(valkey={"host": "wrong-cache"}))
    store.write_marker(
        c.Bootstrapped(version=f"file:2+{SCHEMA_HEAD}", ok=False, error="Valkey refused")
    )
    client = TestClient(create_setup_app(store))
    code = store.setup_code.read_text()
    state = client.get("/v1/setup").json()
    assert (state["state"], state["saved"]) == ("failed", None)
    assert [v["version"] for v in state["earlier"]] == [1]

    res = client.post("/v1/setup/restore", json={"code": code, "version": 1})
    assert res.json()["state"] == "starting"
    cfg = store.load()
    assert cfg is not None and (cfg.version, cfg.valkey.host) == (3, "cache.internal")
    assert client.get("/v1/setup").json()["state"] == "starting"
    assert client.post("/v1/setup/restore", json={"code": code, "version": 1}).status_code == 409


def test_wrong_codes_replace_the_code() -> None:
    store = c.Store()
    client = TestClient(create_setup_app(store))
    first = store.setup_code.read_text()
    for _ in range(10):
        client.post("/v1/setup/code", json={"code": "nope"})
    assert store.setup_code.read_text() != first
    assert client.post("/v1/setup/code", json={"code": first}).status_code == 403


def test_setup_asks_for_every_password() -> None:
    with pytest.raises(service.InfraError, match="postgres-owner-password"):
        service.check_secret_names({"postgres-password": "x"}, complete=True)
    with pytest.raises(service.InfraError, match="unknown"):
        service.check_secret_names({"root": "x"}, complete=False)
    # A Valkey without a password is allowed.
    given = {k: v for k, v in PASSWORDS.items() if k not in (c.INTERNAL_TOKEN, "valkey-password")}
    service.check_secret_names(given, complete=True)


async def test_a_change_is_saved_only_after_its_test(monkeypatch: pytest.MonkeyPatch) -> None:
    store = c.Store()
    cfg = store.save(a_config())

    async def current(_cfg: c.InfraConfig) -> dict[str, str]:
        return PASSWORDS

    seen: dict[str, str] = {}

    async def run(section: c.Section, passwords: dict[str, str], **_k: Any) -> CheckResult:
        seen.update(passwords)
        ok = getattr(section, "host", "") != "unreachable"
        return CheckResult(ok, "fine" if ok else "cannot reach Valkey")

    monkeypatch.setattr(service, "current_passwords", current)
    monkeypatch.setattr(service.checks, "run", run)
    writer = Writer("http://bao", "api")
    bad = service.TestIn(service="valkey", settings={"host": "unreachable"})
    with pytest.raises(service.InfraError, match="cannot reach"):
        await service.change(cfg, store, writer, bad, saved_by="Ada")  # type: ignore[arg-type]
    assert store.load() == cfg

    good = service.TestIn.model_validate(
        {
            "service": "valkey",
            "settings": {"host": "cache2"},
            "secrets": {"valkey-password": "new-one-0123456789"},
        }
    )
    saved = await service.change(cfg, store, writer, good, saved_by="Ada")  # type: ignore[arg-type]
    assert seen["valkey-password"] == "new-one-0123456789"  # tested with the new password
    assert (saved.version, saved.valkey.host, saved.saved_by) == (2, "cache2", "Ada")
    assert saved.secrets["valkey-password"] == c.SecretMeta(version=4, last4="6789")
    assert saved.secrets["postgres-password"] == cfg.secrets["postgres-password"]


def test_schema_head_is_the_newest_migration() -> None:
    ini = get_settings().alembic_ini
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_current_head() == SCHEMA_HEAD, (
        "a new migration: set SCHEMA_HEAD in veyntora_api/db/schema.py"
    )


def test_an_update_with_a_migration_bootstraps_again() -> None:
    store = c.Store()
    store.save(a_config())
    # Bootstrapped by the previous release, before its newest migration existed.
    store.write_marker(c.Bootstrapped(version="file:1+0001", ok=True))
    assert launcher.Launcher("owner", ["true"], store).plan().mode == "bootstrap"
    assert launcher.Launcher("runtime", ["true"], store).plan().mode == "wait"
