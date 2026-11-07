"""The keys that protect the OpenBao tokens in the config file (ADR 0034).

Each service may hold only its own token, so each token is encrypted for its readers:

- the infra reader token (reads the connection passwords): VEY_CONFIG_KEY, every service;
- the API token (writes keys, never reads them): VEY_CONFIG_API_KEY, the API and migrate;
- the runtime token (reads keys): sealed to VEY_CONFIG_RUNTIME_PUBLIC_KEY. The API seals it
  when it is issued but cannot open it; only the runtime services hold the private key.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SHARED = "VEY_CONFIG_KEY"
API = "VEY_CONFIG_API_KEY"
RUNTIME_PUBLIC = "VEY_CONFIG_RUNTIME_PUBLIC_KEY"
RUNTIME_PRIVATE = "VEY_CONFIG_RUNTIME_PRIVATE_KEY"
ALL = (SHARED, API, RUNTIME_PUBLIC, RUNTIME_PRIVATE)

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
)


class ConfigKeyError(RuntimeError):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigKeyError(f"{name} is not set (run `make env`)")
    return value


def encrypt(key_env: str, value: str) -> str:
    return Fernet(_env(key_env).encode()).encrypt(value.encode()).decode()


def decrypt(key_env: str, token: str) -> str:
    try:
        return Fernet(_env(key_env).encode()).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ConfigKeyError(f"{key_env} does not open this config file") from exc


def seal(value: str) -> str:
    """Encrypt for the runtime services (RSA-OAEP); the sealer cannot open it again."""
    public = serialization.load_der_public_key(base64.b64decode(_env(RUNTIME_PUBLIC)))
    if not isinstance(public, rsa.RSAPublicKey):
        raise ConfigKeyError(f"{RUNTIME_PUBLIC} is not an RSA public key")
    return base64.b64encode(public.encrypt(value.encode(), _OAEP)).decode()


def unseal(sealed: str) -> str:
    private = serialization.load_der_private_key(base64.b64decode(_env(RUNTIME_PRIVATE)), None)
    if not isinstance(private, rsa.RSAPrivateKey):
        raise ConfigKeyError(f"{RUNTIME_PRIVATE} is not an RSA private key")
    try:
        return private.decrypt(base64.b64decode(sealed), _OAEP).decode()
    except ValueError as exc:
        raise ConfigKeyError(f"{RUNTIME_PRIVATE} does not open this config file") from exc


def generate() -> dict[str, str]:
    """A fresh set of keys, as .env lines (`veyntora-api keys`)."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    der_private = private.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    der_public = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return {
        SHARED: Fernet.generate_key().decode(),
        API: Fernet.generate_key().decode(),
        RUNTIME_PUBLIC: base64.b64encode(der_public).decode(),
        RUNTIME_PRIVATE: base64.b64encode(der_private).decode(),
    }
