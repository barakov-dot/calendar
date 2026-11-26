# syntax=docker/dockerfile:1
FROM node:22-slim AS base
WORKDIR /app
RUN chown node:node /app

FROM base AS deps
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --no-audit --no-fund && sha256sum package-lock.json > node_modules/.lock-hash

FROM deps AS dev
COPY --chown=node:node . .
COPY --chmod=755 docker/sync-deps.sh /usr/local/bin/sync-deps
ENTRYPOINT ["sync-deps"]
# vite запускается напрямую, чтобы остановка контейнера не выглядела в логах как ошибка npm
CMD ["node_modules/.bin/vite"]

FROM deps AS build
COPY --chown=node:node . .
RUN npm run build

FROM caddy:2 AS prod
COPY --from=build /app/dist /srv
