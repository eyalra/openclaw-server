# OpenClaw AWS Lightsail Deployment Guide

Complete guide for deploying OpenClaw to AWS Lightsail with multi-user support, secure Tailscale access, and persistent data storage.

## Quick Start

1. **Follow Manual Setup SOPs:**
   - [SOP-01: Lightsail Setup](docs/SOP-01-lightsail-setup.md)
   - [SOP-02: Discord Bot Setup](docs/SOP-02-discord-bot-setup.md)
   - [SOP-03: Tailscale Setup](docs/SOP-03-tailscale-setup.md)

2. **Create Configuration:**
   ```bash
   cd deploy/lightsail
   cp .lightsail-config.example .lightsail-config
   # Edit .lightsail-config with your values
   chmod 600 .lightsail-config
   ```

3. **Run Deployment Scripts:**
   ```bash
   ./scripts/validate-config.sh    # Validate configuration
   ./01-harden-server.sh           # Secure the server
   ./02-install-dependencies.sh   # Install Docker, Tailscale, etc.
   ./03-deploy-openclaw.sh        # Clone repo, build image
   ./04-configure-users.sh        # Set up users (interactive)
   ./05-verify-deployment.sh      # Verify everything works
   ```

## Architecture

```
AWS Lightsail Instance (Medium: $20/month)
├── Hardened Ubuntu 24.04
│   ├── SSH on port 2222 (key-only)
│   └── UFW firewall
├── Tailscale (private network)
├── Docker + Docker Compose
├── OpenClaw Containers (one per user)
│   └── data/users/<username>/ (persistent)
└── Knowledge Directory (shared, read-only)
    └── /mnt/knowledge (company-wide data)
```

## Features

- **Multi-user support:** Each user gets isolated container
- **Secure access:** Tailscale private network (no public ports)
- **Persistent storage:** User data survives container restarts
- **Knowledge base:** Shared read-only directory for company data
- **OpenRouter support:** Use cheap models for testing
- **Discord integration:** Secure communication channel
- **Backup strategy:** Lightsail snapshots + future S3 sync

## Directory Structure

```
deploy/lightsail/
├── docs/                          # Standard Operating Procedures
│   ├── SOP-01-lightsail-setup.md
│   ├── SOP-02-discord-bot-setup.md
│   └── SOP-03-tailscale-setup.md
├── scripts/                       # Helper scripts
│   ├── load-config.sh            # Load .lightsail-config
│   └── validate-config.sh       # Validate configuration
├── 00-rebuild-from-scratch.sh    # Complete rebuild
├── 01-harden-server.sh           # Server hardening
├── 02-install-dependencies.sh   # Install Docker, Tailscale
├── 03-deploy-openclaw.sh        # Deploy OpenClaw
├── 04-configure-users.sh        # Set up users
├── 05-verify-deployment.sh      # Verify deployment
├── 07-deploy-updates.sh         # Deploy code updates
├── .lightsail-config.example    # Configuration template
└── README.md                    # This file
```

## Prerequisites

- AWS account with Lightsail access
- Tailscale account (free tier works)
- Discord account (for bot creation)
- API keys:
  - Anthropic API key (production)
  - OR OpenRouter API key (testing)
- SSH key pair

## Deployment Steps

### Phase 0: Configuration Setup

1. Copy config template:
   ```bash
   cp .lightsail-config.example .lightsail-config
   ```

2. Follow SOPs to get required values:
   - Lightsail IP (from SOP-01)
   - SSH key path (from SOP-01)
   - Tailscale IP (from SOP-03)
   - Discord bot token (from SOP-02)

3. Fill in `.lightsail-config` with your values

4. Validate configuration:
   ```bash
   ./scripts/validate-config.sh
   ```

### Phase 1: Server Hardening

```bash
./01-harden-server.sh
```

**What it does:**
- Updates system packages
- Creates non-root user `openclaw`
- Configures SSH (port 2222, key-only)
- Sets up UFW firewall
- Disables systemd socket activation

**After completion:**
- Update `.lightsail-config`: `SSH_PORT="2222"` and `SSH_USER="openclaw"`
- Remove port 22 from Lightsail firewall
- Test SSH on new port

### Phase 2: Install Dependencies

```bash
./02-install-dependencies.sh
```

**What it does:**
- Installs Docker and Docker Compose
- Installs Tailscale
- Installs AWS CLI
- Adds user to docker group

**After completion:**
- Authenticate Tailscale: `sudo tailscale up` (on server)
- Update `.lightsail-config` with Tailscale IP

### Phase 3: Deploy OpenClaw

```bash
./03-deploy-openclaw.sh
```

**What it does:**
- Clones OpenClaw repository
- Builds Docker image
- Creates directory structure
- Sets up knowledge directory

### Phase 4: Configure Users

```bash
./04-configure-users.sh
```

**What it does:**
- Creates `clawctl.toml` with user definitions
- Uses `clawctl user add` to provision users
- Prompts for API keys and Discord tokens
- Creates containers for each user

**Interactive prompts:**
- Model provider choice (Anthropic/OpenRouter/Both)
- User names
- API keys
- Discord bot tokens

### Phase 5: Verify Deployment

```bash
./05-verify-deployment.sh
```

**What it checks:**
- Docker installation
- Container status
- Tailscale connection
- Knowledge directory
- Access URLs

## Managing Deployment

### Deploy Code Updates

```bash
./07-deploy-updates.sh
```

Pushes local changes to git, pulls on server, rebuilds image, and restarts containers.

### Complete Rebuild

```bash
./00-rebuild-from-scratch.sh
```

Wipes everything and rebuilds from scratch. Use with caution!

**Options:**
- `--keep-knowledge` - Preserve knowledge directory
- `--remove-images` - Remove Docker images too

### Check Status

```bash
ssh -p 2222 -i <key> openclaw@<ip>
cd ~/openclaw
clawctl status --config clawctl.toml
```

### View Logs

```bash
ssh -p 2222 -i <key> openclaw@<ip>
docker logs openclaw-user1
# Or use clawctl
clawctl logs user1 --config clawctl.toml
```

## Accessing OpenClaw

### Via Tailscale (Recommended)

1. Ensure Tailscale is running on your local machine
2. Get Tailscale IP from server: `tailscale ip -4`
3. Access: `http://<tailscale-ip>:18789` (user1)
4. Enter gateway token when prompted

### Via SSH Tunnel

```bash
source scripts/load-config.sh
ssh -p "$SSH_PORT" -i "$SSH_KEY" -L 18789:localhost:18789 "$SSH_USER@$LIGHTSAIL_IP"
# Then access: http://localhost:18789
```

## Adding Users

1. Edit `clawctl.toml` on server (add `[[users]]` block)
2. Run: `clawctl user add <username> --config /path/to/clawctl.toml`
3. Follow prompts for secrets

## Knowledge Directory

**Location:** `/home/openclaw/data/knowledge/` (on server)

**Structure:**
```
knowledge/
├── transcripts/
├── newsletters/
└── emails/
```

**Upload files:**
```bash
scp -P 2222 -r knowledge-files/ openclaw@<ip>:/home/openclaw/data/knowledge/
```

**Access in containers:** `/mnt/knowledge/` (read-only)

## Backup Strategy

**Current:** Lightsail snapshots
- Manual: Lightsail Console → Snapshots → Create snapshot
- Automated: Future script for daily snapshots

**Future:** S3 sync
- Sync `data/users/` directories to S3
- Granular restore capability

## Troubleshooting

See [Troubleshooting Guide](docs/README.md#troubleshooting) in docs directory.

Common issues:
- **SSH connection failed:** Check IP, key, port, firewall
- **Container won't start:** Check logs, permissions, secrets
- **Discord bot offline:** Verify token, check container logs
- **Knowledge directory not accessible:** Check permissions, verify mount

## Cost Estimate

**Monthly:**
- Lightsail Medium: $20
- Snapshots (7 days): ~$3
- Tailscale: Free
- **Total: ~$23/month**

## Security

- SSH hardened (port 2222, key-only)
- UFW firewall configured
- Tailscale private network (no public ports)
- Non-root user for operations
- Containers run as non-root
- Secrets stored with 600 permissions

## Related Documentation

- [Development Workflow](DEVELOPMENT.md) - Local testing and deployment
- [SOPs](docs/) - Manual setup procedures
- [Configuration Reference](.lightsail-config.example)

## Support

For issues:
1. Check troubleshooting section
2. Review container logs: `docker logs openclaw-<username>`
3. Verify configuration: `./scripts/validate-config.sh`
4. Check SOPs for manual setup steps
