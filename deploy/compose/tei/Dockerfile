# Picks the upstream TEI CPU image that matches the build platform, so `docker compose up`
# works on x86 servers and on Apple Silicon without extra settings. GPU nodes use the CUDA
# image directly (deploy/helm).
ARG TEI_VERSION=1.9.4
FROM ghcr.io/huggingface/text-embeddings-inference:cpu-${TEI_VERSION} AS tei-amd64
FROM ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-${TEI_VERSION} AS tei-arm64
ARG TARGETARCH
FROM tei-${TARGETARCH}
