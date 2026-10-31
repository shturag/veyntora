"""S3 buckets (AWS or on-premises stores such as MinIO, SeaweedFS or Ceph).

Read-only: list the chosen prefixes and download objects. The ETag tells changed objects
apart, so later syncs download only what changed. The access needed is s3:ListBucket and
s3:GetObject on the bucket.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aioboto3
from botocore.config import Config
from veyntora_api.knowledge.connectors import S3Settings

from veyntora_workers.connectors.listing import Entry, Listing

_TIMEOUTS = Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 3})


class S3Reader:
    def __init__(self, cfg: S3Settings, secret_key: str) -> None:
        self.cfg = cfg
        self._secret = secret_key
        self._session = aioboto3.Session()
        self.listed_all = False

    def _client(self) -> Any:
        return self._session.client(
            "s3",
            endpoint_url=self.cfg.endpoint_url,
            region_name=self.cfg.region,
            aws_access_key_id=self.cfg.access_key_id,
            aws_secret_access_key=self._secret,
            config=_TIMEOUTS,
        )

    async def check(self) -> str:
        async with self._client() as s3:
            await s3.head_bucket(Bucket=self.cfg.bucket)
            page = await s3.list_objects_v2(
                Bucket=self.cfg.bucket, Prefix=(self.cfg.prefixes or [""])[0], MaxKeys=1000
            )
        count = int(page.get("KeyCount", 0))
        more = "+" if page.get("IsTruncated") else ""
        return f"Bucket {self.cfg.bucket} is readable; {count}{more} objects in the first prefix."

    async def entries(self) -> AsyncIterator[Entry]:
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            for prefix in self.cfg.prefixes or [""]:
                async for page in paginator.paginate(Bucket=self.cfg.bucket, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        key = str(obj["Key"])
                        if key.endswith("/"):
                            continue  # folder marker
                        yield Entry(
                            external_id=key,
                            path=key,
                            name=key.rsplit("/", 1)[-1],
                            url=None,
                            version=str(obj.get("ETag") or "").strip('"') or None,
                            size=int(obj.get("Size") or 0),
                            modified=obj.get("LastModified"),
                        )
        self.listed_all = True

    async def download(self, entry: Entry) -> bytes:
        async with self._client() as s3:
            obj = await s3.get_object(Bucket=self.cfg.bucket, Key=entry.external_id)
            async with obj["Body"] as body:
                data: bytes = await body.read()
        return data

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(), download=self.download, complete=lambda: self.listed_all
        )
