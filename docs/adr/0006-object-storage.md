# 0006 · Object storage: customer S3 in production, SeaweedFS locally

Status: accepted · 2026-10-30 · decided by the product owner

## Context

The brief names MinIO. MinIO's community edition no longer ships images: `minio/minio` is gone from Docker Hub, and the last source release is from October 2025, so known vulnerabilities stay unfixed.

## Decision

- Veyntora talks to object storage only through the **S3 API** (aioboto3), with endpoint, region, bucket and credentials as configuration.
- **Production (Helm):** no bundled object store. Customers provide S3 (AWS S3, Ceph RGW, NetApp StorageGRID, …). The WORM audit bucket (Phase 7) needs S3 Object Lock.
- **Local development (compose):** SeaweedFS 4.51 (Apache-2.0) with one identity per bucket (`veyntora`, `langfuse`), each limited to its own bucket.

## Consequences

Contract tests for storage run against SeaweedFS in CI. Object-lock behaviour is verified against the customer's store during Phase 7 acceptance.
