# syntax=docker/dockerfile:1.7
# Next.js app (landing, user app, admin console) as a standalone server.
# Build from the repository root: docker build -f apps/web/Dockerfile .

FROM node:26.13.0-alpine3.24 AS build
RUN npm install -g pnpm@12.16.1
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /src

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/ui/package.json packages/ui/
COPY packages/spec/package.json packages/spec/
RUN pnpm install --frozen-lockfile --filter "@veyntora/web..."

COPY packages/ui packages/ui
COPY packages/spec/ts packages/spec/ts
COPY packages/spec/tsconfig.json packages/spec/
COPY apps/web apps/web
RUN pnpm --filter @veyntora/web build

FROM node:26.13.0-alpine3.24
# The server needs node only. The package managers bundled with the base image (npm,
# corepack, yarn) are removed: unused, and their own dependencies carry CVEs.
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx \
      /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn-*
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /src/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /src/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /src/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
