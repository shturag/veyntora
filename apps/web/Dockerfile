# syntax=docker/dockerfile:1.7
# Next.js app (landing, user app, admin console) as a standalone server.
# Build from the repository root: docker build -f apps/web/Dockerfile .

FROM node:24.22.2-alpine3.24 AS build
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

FROM node:24.22.2-alpine3.24
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
