# 0001 · Monorepo and toolchain

Status: accepted · 2026-10-30 · Phase 0

## Decision

- One repository. Python packages form a **uv workspace** (`packages/spec`, `packages/providers`, `services/*`) with one `uv.lock`. JS packages form a **pnpm workspace** (`apps/web`, `packages/ui`, `packages/spec`) with one `pnpm-lock.yaml`, orchestrated by Turborepo.
- Every dependency and image is pinned exactly: lock files for libraries, explicit tags for images, commit SHAs for GitHub Actions. Versions were taken from the registries on 2026-10-30.
- Python 3.12 (as briefed), Node 24 LTS in images.

## Deviations from "latest stable", with reasons

| Component | Latest | Pinned | Why |
|---|---|---|---|
| TypeScript | 7.0.2 | 6.0.3 | TS 7 (native compiler) exposes no classic compiler API (`"."` exports only the version). Next.js type-checking and typescript-eslint require that API; typescript-eslint 8.72 supports `<6.1`. |
| ESLint | 10.14 | 9.39.5 | `eslint-config-next` 16.4 depends on `eslint-plugin-react`, `-import` and `-jsx-a11y`, which support ESLint ≤ 9. |
| lucide-react | 1.65.0 | 1.62.0 | 1.65 was published on the build day; pnpm 12's minimum release age blocks it. We keep the age policy instead of excluding the package. |
| NextAuth / Auth.js | 5.0.0-beta | not used | v5 is still beta. Authentication runs in the API instead (ADR 0003). |
| hvac | 2.4.0 | not used | The OpenBao client is a thin httpx wrapper, so it can be write-only by construction (ADR 0004). |

## Consequences

- `make sync`, `make ci`, `make up` are the entry points. CI runs the same commands.
- pnpm only runs install scripts for packages listed under `allowBuilds` in `pnpm-workspace.yaml`.
- On macOS, uv marks `.venv` hidden and Python skips hidden `.pth` files, which breaks editable installs. pytest and the Makefile therefore set import paths explicitly (`pythonpath` in `pyproject.toml`, `PYTHONPATH` in the Makefile). Linux and CI are unaffected.
