# DailyGreen Multi-Stage Production Dockerfile
# Stage 1: Build & Asset Compilation
FROM node:22-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache python3 make g++ git

COPY package*.json ./
RUN npm ci

COPY . .

# Run TypeScript verification and Vite production bundling
RUN npm run build

# -------------------------------------------------------------
# Stage 2: Production Minimal Runtime
FROM node:22-alpine AS runner

WORKDIR /app

# Install minimal runtime dependencies: git, python3, curl, wget
RUN apk add --no-cache \
    git \
    python3 \
    curl \
    wget \
    ca-certificates \
    tzdata

# Create dedicated non-root application user and group (UID/GID 10001)
RUN addgroup -g 10001 dailygreen && \
    adduser -u 10001 -G dailygreen -s /bin/sh -D -h /app dailygreen

# Copy runtime files from builder
COPY --from=builder --chown=dailygreen:dailygreen /app/package*.json ./
COPY --from=builder --chown=dailygreen:dailygreen /app/node_modules ./node_modules
COPY --from=builder --chown=dailygreen:dailygreen /app/dist ./dist
COPY --from=builder --chown=dailygreen:dailygreen /app/server.ts ./server.ts
COPY --from=builder --chown=dailygreen:dailygreen /app/src ./src
COPY --from=builder --chown=dailygreen:dailygreen /app/config ./config
COPY --from=builder --chown=dailygreen:dailygreen /app/tsconfig.json ./tsconfig.json
COPY --from=builder --chown=dailygreen:dailygreen /app/vite.config.ts ./vite.config.ts

# Prepare isolated persistence directories with strict non-root permissions
RUN mkdir -p /app/.dailygreen-data/workspaces \
             /app/.dailygreen-data/backups \
             /app/.dailygreen-data/logs && \
    chown -R dailygreen:dailygreen /app && \
    chmod -R 0750 /app/.dailygreen-data

# Declare durable storage volume
VOLUME ["/app/.dailygreen-data"]

# Fail-safe security defaults
ENV NODE_ENV=production \
    PORT=3000 \
    DRY_RUN=true \
    ALLOW_LIVE_MUTATIONS=false \
    MAX_WORKERS=1 \
    DAILYGREEN_ENABLED=false \
    DAILYGREEN_TIMEZONE=Asia/Tashkent

EXPOSE 3000

# Run strictly under unprivileged user
USER dailygreen

# Container healthcheck monitoring endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:3000/api/health > /dev/null 2>&1 || exit 1

# Process supervisor entrypoint
CMD ["npx", "tsx", "server.ts"]
