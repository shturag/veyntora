"""Starts a Veyntora service with the infrastructure it is set up with (ADR 0034).

    veyntora-api launch <role> -- <command...>

Every container runs its service through this. It reads the config file, fetches the
connection passwords from OpenBao with the infra token, gives the service only the
OpenBao token its role may hold, and restarts the service when an admin saves a new
version. Without a config file, settings from the environment are used as they are
(CI, Helm).

- owner (migrate): runs `bootstrap` once per version and records the outcome;
- api: until a version is bootstrapped, serves the Setup page instead of the API;
- the others wait until the version they would start with is bootstrapped.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import structlog

from veyntora_api.db.schema import SCHEMA_HEAD
from veyntora_api.infra import config as c
from veyntora_api.infra import keys, vault

log = structlog.get_logger()

_TICK_S = 2.0
_RENEW_EVERY_S = 12 * 3600
_RETRY_S = 10.0
# Settings that, from the environment, make up the infrastructure (env mode).
_ENV_INFRA = (
    "VEY_DATABASE_URL",
    "VEY_REDIS_URL",
    "VEY_S3_ENDPOINT",
    "VEY_OPENFGA_URL",
    "VEY_OPENBAO_URL",
    "VEY_OIDC_ISSUER",
)
SETUP_STATE_ENV = "VEY_SETUP_STATE"
SETUP_ERROR_ENV = "VEY_SETUP_ERROR"


def _where(url: str) -> str:
    """An address without its user and password."""
    return re.sub(r"(://)[^/@\s]*@", r"\1", url)


def env_tag() -> str | None:
    """Env mode: a version that changes when the environment's infrastructure does."""
    if not os.environ.get("VEY_DATABASE_URL"):
        return None
    # Which services, not who signs in: the owner (migrate) and the runtime services use
    # different database users, and must still agree on the version.
    digest = hashlib.sha256("\0".join(_where(os.environ.get(k, "")) for k in _ENV_INFRA).encode())
    return "env:" + digest.hexdigest()[:16]


def current_tag(store: c.Store) -> str | None:
    """The version the services run: the infrastructure's, plus the database schema this code
    needs, so an update that brings a migration bootstraps again."""
    tag = store.version_tag() or env_tag()
    return f"{tag}+{SCHEMA_HEAD}" if tag else None


def scrub(text: str) -> str:
    """One line for the Setup page: no URL credentials, no long tokens."""
    import re  # noqa: PLC0415

    text = re.sub(r"://[^/\s:@]*:[^@\s]*@", "://***@", text)
    text = re.sub(r"\b[A-Za-z0-9._~+/=-]{24,}\b", "***", text)
    return text.strip()[:300]


@dataclass(frozen=True)
class Plan:
    """What the role should run now, for which version."""

    mode: str  # "service" | "setup" | "wait" | "bootstrap" | "idle"
    tag: str | None


class Launcher:
    def __init__(self, role: c.Role, command: list[str], store: c.Store | None = None) -> None:
        self.role = role
        self.command = command
        self.store = store or c.Store()
        self.child: subprocess.Popen[bytes] | None = None
        self.running: Plan | None = None
        self.stopping = False
        self.token_dir = Path(tempfile.mkdtemp(prefix="veyntora-"))
        self.last_renew = time.monotonic()
        self.tail: deque[str] = deque(maxlen=30)
        # Why the service could not be started for a version (OpenBao unreachable, ...).
        self.error: tuple[str | None, str] | None = None
        self.error_at = 0.0

    # --- deciding ---------------------------------------------------------------------

    def plan(self) -> Plan:
        """Cheap: the config file and migrate's marker only."""
        tag = current_tag(self.store)
        marker = self.store.read_marker()
        bootstrapped = bool(marker and marker.ok and marker.version == tag)
        if tag is None:
            return Plan("setup" if self.role == "api" else "wait", None)
        failed = bool(self.error and self.error[0] == tag)
        if self.role == "owner":
            return Plan("idle" if bootstrapped else "wait" if failed else "bootstrap", tag)
        if not bootstrapped or failed:
            return Plan("setup" if self.role == "api" else "wait", tag)
        return Plan("service", tag)

    def base_env(self) -> dict[str, str]:
        keep = set(c.ROLE_KEYS[self.role])
        return {k: v for k, v in os.environ.items() if k not in keys.ALL or k in keep}

    def env_for(self, plan: Plan) -> dict[str, str]:
        if plan.mode == "setup":
            state = {SETUP_STATE_ENV: "setup" if plan.tag is None else "starting"}
            if self.error and self.error[0] == plan.tag:
                state[SETUP_ERROR_ENV] = self.error[1]
            return self.base_env() | state
        cfg = self.store.load()
        if cfg is None:
            return self.base_env()  # env mode: the environment is the configuration
        infra = c.infra_token(cfg)
        versions = {name: meta.version for name, meta in cfg.secrets.items()}
        passwords = asyncio.run(
            vault.read_passwords(cfg.openbao.url, infra, cfg.openbao.kv_mount, versions)
        )
        env = self.base_env() | c.service_env(cfg, self.role, passwords)
        token = c.role_token(cfg, self.role)
        if token:
            path = self.token_dir / "openbao.token"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(token)
            env["VEY_OPENBAO_TOKEN_FILE"] = str(path)
        self.renew(cfg, infra, token)
        return env

    def renew(self, cfg: c.InfraConfig, *tokens: str | None) -> None:
        for token in tokens:
            if token:
                try:
                    asyncio.run(vault.renew(cfg.openbao.url, token))
                except (vault.VaultError, OSError) as exc:
                    log.warning("launch.token_renewal_failed", error=str(exc))
        self.last_renew = time.monotonic()

    # --- running ----------------------------------------------------------------------

    def start(self, plan: Plan) -> None:
        try:
            env = self.env_for(plan)
        except (vault.VaultError, keys.ConfigKeyError, OSError, ValueError) as exc:
            # Retried after a pause; the API shows it on the Setup page meanwhile.
            self.error = (plan.tag, scrub(f"{type(exc).__name__}: {exc}"))
            log.error("launch.not_ready", role=self.role, error=self.error[1])
            return
        command = ["veyntora-api", "serve-setup"] if plan.mode == "setup" else self.command
        capture = plan.mode == "bootstrap"
        log.info("launch.start", role=self.role, mode=plan.mode, version=plan.tag)
        self.child = subprocess.Popen(  # noqa: S603 - our own command line
            command,
            env=env,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
        if capture:
            self.tail.clear()
            threading.Thread(target=self._echo, daemon=True).start()
        self.running = plan

    def _echo(self) -> None:
        if self.child is None or self.child.stdout is None:
            return
        for raw in self.child.stdout:
            line = raw.decode(errors="replace")
            sys.stdout.write(line)
            sys.stdout.flush()
            self.tail.append(line.rstrip())

    def stop_child(self) -> int:
        if self.child is None:
            return 0
        if self.child.poll() is None:
            self.child.send_signal(signal.SIGTERM)
            try:
                self.child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
        code = self.child.returncode
        self.child = None
        self.running = None
        return code

    def bootstrap_error(self) -> str:
        lines = [x for x in self.tail if x]
        errors = [x for x in lines if "error" in x.lower()]
        return scrub((errors or lines or ["bootstrap failed"])[-1])

    def tick(self) -> int | None:
        """One round; returns an exit code when the launcher should stop."""
        if self.error and time.monotonic() - self.error_at > _RETRY_S:
            self.error = None  # try again
        plan = self.plan()
        if self.running and self.running != plan:
            log.info("launch.restart", role=self.role, mode=plan.mode, version=plan.tag)
            self.stop_child()
        if self.child is None and plan.mode in ("service", "setup", "bootstrap"):
            had_error = self.error
            self.start(plan)
            if self.error is not had_error:
                self.error_at = time.monotonic()
        if self.child is not None and (code := self.child.poll()) is not None:
            ran = self.running
            self.child = None
            self.running = None
            if ran is None or ran.mode != "bootstrap":
                return code
            ok = code == 0
            error = "" if ok else self.bootstrap_error()
            self.store.write_marker(c.Bootstrapped(version=cast(str, ran.tag), ok=ok, error=error))
            log.info("launch.bootstrapped", ok=ok, version=ran.tag)
            if not ok:
                self._sleep(_RETRY_S)
            return None
        if (
            self.child is not None
            and plan.tag
            and plan.tag.startswith("file:")
            and time.monotonic() - self.last_renew > _RENEW_EVERY_S
            and (cfg := self.store.load())
        ):
            self.renew(cfg, c.infra_token(cfg), c.role_token(cfg, self.role))
        return None

    def loop(self) -> int:
        def on_signal(signum: int, _frame: object) -> None:
            self.stopping = True
            if self.child and self.child.poll() is None:
                self.child.send_signal(signum)

        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
        while not self.stopping:
            if (code := self.tick()) is not None:
                return code
            self._sleep(_TICK_S)
        return self.stop_child()

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self.stopping and time.monotonic() < end:
            time.sleep(0.2)


def healthy(*, bootstrapped: bool = False, url: str | None = None) -> bool:
    """Container health: migrate is healthy once the current version is bootstrapped; a
    service is healthy while it still waits for that (nothing to serve yet) or when `url`
    answers."""
    store = c.Store()
    marker = store.read_marker()
    done = bool(marker and marker.ok and marker.version == current_tag(store))
    if bootstrapped:
        return done
    if not done or not url:
        return True
    import urllib.request  # noqa: PLC0415

    try:
        with urllib.request.urlopen(url, timeout=3) as res:  # noqa: S310 - fixed local URL
            return bool(res.status == 200)
    except OSError:
        return False


def main(role: str, command: list[str]) -> int:
    if role not in c.ROLE_TOKEN:
        raise SystemExit(f"unknown role {role!r}; one of {', '.join(c.ROLE_TOKEN)}")
    if not command:
        raise SystemExit("no command to launch")
    return Launcher(role, command).loop()
