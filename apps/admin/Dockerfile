# syntax=docker/dockerfile:1
# Build context is the repository root: the pnpm workspace lockfile lives there.

FROM node:24-slim AS builder

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_OUTPUT_STANDALONE=1

RUN corepack enable

WORKDIR /repo

# Dependency layer first so application edits do not invalidate it.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/admin/package.json apps/admin/package.json
RUN corepack pnpm install --frozen-lockfile

# CONTENTOS_INTERNAL_API_URL is deliberately NOT needed at build time: the
# status page is dynamic and reads it server-side at runtime only.
COPY apps/admin apps/admin
RUN corepack pnpm --filter admin build


FROM node:24-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app

# The node user (uid 1000) ships with the base image.
COPY --from=builder --chown=node:node /repo/apps/admin/.next/standalone ./
COPY --from=builder --chown=node:node /repo/apps/admin/.next/static ./apps/admin/.next/static

USER node

EXPOSE 3000

CMD ["node", "apps/admin/server.js"]
