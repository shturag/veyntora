from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VEY_", env_file=".env", extra="ignore")

    environment: Literal["local", "dev", "staging", "prod", "test"] = "local"
    log_level: str = "INFO"

    # Public URL of the web app; the API is reachable under {public_base_url}/api.
    public_base_url: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://veyntora:veyntora@localhost:5432/veyntora"
    # Workers run each task in a fresh event loop, so pooled connections must not outlive it.
    db_null_pool: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # Keycloak. `oidc_issuer` is the public issuer that appears in tokens; the internal
    # base URL is what this service uses for back-channel calls (token, JWKS, admin API).
    oidc_issuer: str = "http://localhost:8080/realms/veyntora"
    oidc_internal_base: str | None = None
    oidc_client_id: str = "veyntora"
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_audience: str = "veyntora-api"
    oidc_scopes: str = "openid profile email"
    keycloak_sync_client_id: str = "veyntora-sync"
    keycloak_sync_client_secret: SecretStr = SecretStr("")

    session_cookie: str = "vey_session"
    session_idle_seconds: int = 8 * 3600

    openfga_url: str = "http://localhost:8082"
    openfga_store_name: str = "veyntora"
    openfga_model_path: Path = Path("deploy/openfga/model.json")
    # Keycloak group path whose members become platform admins at bootstrap.
    bootstrap_admin_group: str = "/platform-admins"

    openbao_url: str = "http://localhost:8200"
    openbao_token_file: Path = Path("deploy/compose/.state/openbao/api.token")
    openbao_kv_mount: str = "kv"

    s3_endpoint: str = "http://localhost:8333"
    s3_region: str = "eu-central-1"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "veyntora"

    # Uploads: virus scan with clamd (host:port). Scanning is required unless switched off
    # explicitly; documents then show "not scanned" in the admin console.
    clamav_address: str = ""
    scan_required: bool = True
    upload_max_bytes: int = 50 * 1024 * 1024

    # Health targets for the status page. Empty means the component is not deployed.
    qdrant_url: str = "http://localhost:6333"
    litellm_url: str = "http://localhost:4000"
    graphs_url: str = "http://localhost:2026"
    docling_url: str = "http://localhost:5001"
    tei_embed_url: str = ""
    tei_rerank_url: str = ""
    langfuse_url: str = "http://localhost:3001"
    # Project keys for traces (graphs). Empty keys switch tracing off.
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")

    alembic_ini: Path = Path(__file__).resolve().parents[2] / "alembic.ini"

    status_timeout_seconds: float = 2.0
    cors_origins: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oidc_backchannel_base(self) -> str:
        return (self.oidc_internal_base or self.oidc_issuer).rstrip("/")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
