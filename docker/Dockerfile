FROM node:22-slim

ARG OPENCLAW_VERSION=latest

# Install minimal system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install openclaw at pinned version
RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

# Install gog (gogcli) for Gmail/Google Workspace access
RUN GOGCLI_URL=$(curl -sL https://api.github.com/repos/steipete/gogcli/releases/latest \
        | grep '"browser_download_url"' \
        | grep 'linux_amd64.tar.gz' \
        | cut -d'"' -f4) \
    && curl -L "$GOGCLI_URL" | tar -xz -C /usr/local/bin gog \
    && chmod +x /usr/local/bin/gog

# Install gh (GitHub CLI) via official GitHub apt repo
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Install gemini CLI via npm
RUN npm install -g @google/gemini-cli

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
