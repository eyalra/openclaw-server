FROM node:22-slim

ARG OPENCLAW_VERSION=latest

# Install minimal system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install openclaw at pinned version
RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

# Ensure home directory structure exists with correct ownership
RUN mkdir -p /home/node/.openclaw/workspace \
    && chown -R 1000:1000 /home/node

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Switch to non-root user
USER node
WORKDIR /home/node

# Persistent data mount point
VOLUME /home/node/.openclaw

# Gateway port
EXPOSE 18789

# Health check against the gateway HTTP endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://127.0.0.1:18789/ || exit 1

ENTRYPOINT ["entrypoint.sh"]
