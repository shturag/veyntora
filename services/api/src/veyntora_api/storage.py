"""Object storage (S3 API): originals of uploaded documents.

Customer-provided S3 in production, SeaweedFS locally (ADR 0006). Keys are
`sources/{source_id}/{document_id}/{sha256}` so a new version never overwrites the old
object before it has been indexed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import aioboto3

from veyntora_api.settings import Settings


def object_key(source_id: UUID, document_id: UUID, sha256: str) -> str:
    return f"sources/{source_id}/{document_id}/{sha256}"


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._session = aioboto3.Session()

    def _client(self) -> Any:
        return self._session.client(
            "s3",
            endpoint_url=self._s.s3_endpoint,
            region_name=self._s.s3_region,
            aws_access_key_id=self._s.s3_access_key.get_secret_value(),
            aws_secret_access_key=self._s.s3_secret_key.get_secret_value(),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._client() as c:
            await c.put_object(
                Bucket=self._s.s3_bucket, Key=key, Body=data, ContentType=content_type
            )

    async def get(self, key: str) -> bytes:
        async with self._client() as c:
            res = await c.get_object(Bucket=self._s.s3_bucket, Key=key)
            async with res["Body"] as body:
                data: bytes = await body.read()
                return data

    async def delete(self, key: str) -> None:
        async with self._client() as c:
            await c.delete_object(Bucket=self._s.s3_bucket, Key=key)
