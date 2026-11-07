"""OpenFGA access. Object ids are Veyntora UUIDs: user:<uuid>, group:<uuid>, chatbot:<uuid>."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

from openfga_sdk.client import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import (
    ClientBatchCheckItem,
    ClientBatchCheckRequest,
    ClientCheckRequest,
    ClientListObjectsRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.client.models.write_conflict_opts import (
    ClientWriteRequestOnDuplicateWrites,
    ClientWriteRequestOnMissingDeletes,
    ConflictOptions,
)
from openfga_sdk.models import (
    CreateStoreRequest,
    ReadRequestTupleKey,
    WriteAuthorizationModelRequest,
)

PLATFORM = "platform:default"

_IDEMPOTENT: Any = {
    "conflict": ConflictOptions(
        on_duplicate_writes=ClientWriteRequestOnDuplicateWrites.IGNORE,
        on_missing_deletes=ClientWriteRequestOnMissingDeletes.IGNORE,
    )
}


@dataclass(frozen=True, slots=True)
class Tuple:
    user: str
    relation: str
    object: str

    def to_client(self) -> ClientTuple:
        return ClientTuple(user=self.user, relation=self.relation, object=self.object)


@dataclass(frozen=True, slots=True)
class CheckItem:
    user: str
    relation: str
    object: str


class Authz:
    """Thin async wrapper so the rest of the code never touches SDK types."""

    def __init__(self, client: OpenFgaClient) -> None:
        self._client = client

    @classmethod
    async def connect(cls, api_url: str, store_name: str) -> Self:
        """Connect to an existing store and its latest model (created by `bootstrap`)."""
        client = _client(api_url)
        store_id = await _find_store(client, store_name)
        if store_id is None:
            await client.close()
            raise RuntimeError(f"OpenFGA store {store_name!r} not found; run bootstrap first")
        client.set_store_id(store_id)
        latest = await client.read_latest_authorization_model()
        client.set_authorization_model_id(latest.authorization_model.id)
        return cls(client)

    async def close(self) -> None:
        await self._client.close()

    async def check(self, user: str, relation: str, obj: str) -> bool:
        res = await self._client.check(ClientCheckRequest(user=user, relation=relation, object=obj))
        return bool(res.allowed)

    async def batch_check(self, items: Sequence[CheckItem]) -> list[bool]:
        if not items:
            return []
        body = ClientBatchCheckRequest(
            checks=[
                ClientBatchCheckItem(
                    user=i.user, relation=i.relation, object=i.object, correlation_id=str(n)
                )
                for n, i in enumerate(items)
            ]
        )
        res = await self._client.batch_check(body)
        allowed = {r.correlation_id: bool(r.allowed) and r.error is None for r in res.result}
        return [allowed.get(str(n), False) for n in range(len(items))]

    async def list_objects(self, user: str, relation: str, type_: str) -> list[str]:
        res = await self._client.list_objects(
            ClientListObjectsRequest(user=user, relation=relation, type=type_)
        )
        return list(res.objects or [])

    async def read(self, obj: str, relation: str | None = None) -> list[Tuple]:
        """Tuples written directly on an object (not computed relations)."""
        out: list[Tuple] = []
        token: str | None = None
        while True:
            opts: dict[str, Any] = {"page_size": 100}
            if token:
                opts["continuation_token"] = token
            res = await self._client.read(ReadRequestTupleKey(object=obj, relation=relation), opts)
            out += [Tuple(t.key.user, t.key.relation, t.key.object) for t in res.tuples or []]
            token = res.continuation_token or None
            if not token:
                return out

    async def write(self, writes: Iterable[Tuple] = (), deletes: Iterable[Tuple] = ()) -> None:
        w = [t.to_client() for t in writes]
        d = [t.to_client() for t in deletes]
        if not w and not d:
            return
        await self._client.write(
            ClientWriteRequest(writes=w or None, deletes=d or None), options=_IDEMPOTENT
        )


def _client(api_url: str) -> OpenFgaClient:
    parts = urlsplit(api_url)
    return OpenFgaClient(ClientConfiguration(api_url=f"{parts.scheme}://{parts.netloc}"))


async def _find_store(client: OpenFgaClient, name: str) -> str | None:
    token: str | None = None
    while True:
        opts: dict[str, Any] = {"page_size": 100}
        if token:
            opts["continuation_token"] = token
        res = await client.list_stores(opts)
        for store in res.stores or []:
            if store.name == name:
                return str(store.id)
        token = res.continuation_token or None
        if not token:
            return None


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        out = {k: _strip_empty(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, {}, [], "")}
    if isinstance(value, list):
        return [_strip_empty(v) for v in value]
    return value


def _normalise(model: dict[str, Any]) -> str:
    """Server responses add nulls and empty maps the CLI output omits; compare without them."""
    return json.dumps(
        _strip_empty(
            {k: model.get(k) for k in ("schema_version", "type_definitions", "conditions")}
        ),
        sort_keys=True,
        default=str,
    )


async def ensure_store_and_model(
    api_url: str, store_name: str, model_path: Path
) -> tuple[str, str]:
    """Create the store if missing and write the model if it differs from the latest one.

    Returns (store_id, authorization_model_id). Safe to run on every deploy.
    """
    model = json.loads(await asyncio.to_thread(model_path.read_text))
    model.setdefault("conditions", {})
    client = _client(api_url)
    try:
        store_id = await _find_store(client, store_name)
        if store_id is None:
            created = await client.create_store(CreateStoreRequest(name=store_name))
            store_id = str(created.id)
        client.set_store_id(store_id)

        current: dict[str, Any] | None = None
        try:
            latest = await client.read_latest_authorization_model()
            if latest.authorization_model is not None:
                current = latest.authorization_model.to_dict()
                current.setdefault("conditions", {})
        except Exception:
            current = None

        if current is not None and _normalise(current) == _normalise(model):
            return store_id, str(current["id"])

        written = await client.write_authorization_model(
            WriteAuthorizationModelRequest(
                schema_version=model["schema_version"],
                type_definitions=model["type_definitions"],
                conditions=model.get("conditions") or None,
            )
        )
        return store_id, str(written.authorization_model_id)
    finally:
        await client.close()


def bootstrap_tuples(mapping: dict[str, Any]) -> list[Tuple]:
    """Admin-area tuples from deploy/openfga/bootstrap.json."""
    tuples = [Tuple(PLATFORM, "platform", f"admin_area:{a}") for a in mapping["areas"]]
    for role, grants in mapping["roles"].items():
        for relation, areas in grants.items():
            tuples += [Tuple(f"{PLATFORM}#{role}", relation, f"admin_area:{a}") for a in areas]
    return tuples


def user_ref(user_id: object) -> str:
    return f"user:{user_id}"
