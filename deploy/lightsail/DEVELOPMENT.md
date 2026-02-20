# OpenClaw Development and Testing Guide

Guide for developing and testing OpenClaw enhancements locally before deploying to AWS Lightsail.

## Local Development Setup

### Prerequisites

- Docker Desktop (or Docker + Colima)
- Python 3.12+ with virtual environment
- Git repository cloned locally

### Initial Setup

```bash
# Clone repository
git clone <repo-url>
cd openclaw

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install in development mode
pip install -e ".[dev]"

# Verify installation
clawctl --version
```

### Local Directory Structure

```
~/openclaw/                    # Local development
├── data/                      # Local test data (gitignored)
│   ├── secrets/
│   ├── users/
│   └── knowledge/             # Test knowledge directory
├── build/                     # Local build artifacts
├── clawctl.toml              # Local test configuration
└── ...                       # Source code
```

## Testing Enhancements Locally

### 1. Make Code Changes

Edit source files:
- `src/clawctl/` - Python code
- `docker/` - Docker configuration
- Configuration models

### 2. Test with clawctl

```bash
# Create test user
clawctl user add testuser

# Start container
clawctl start testuser

# Check status
clawctl status

# View logs
clawctl logs testuser

# Test specific functionality
clawctl config validate
clawctl user list
```

### 3. Test Docker Image Changes

```bash
# Rebuild image locally
clawctl update

# Or manually
docker build -t openclaw-instance:latest --build-arg OPENCLAW_VERSION=latest docker/

# Test with new image
clawctl user add testuser2
clawctl start testuser2
```

### 4. Test Knowledge Directory Mount

```bash
# Create local knowledge directory
mkdir -p ~/openclaw/data/knowledge/transcripts
echo "# Test transcript" > ~/openclaw/data/knowledge/transcripts/test.md

# Update clawctl.toml
cat >> clawctl.toml << EOF
[clawctl]
knowledge_dir = "$(pwd)/data/knowledge"
EOF

# Rebuild containers to test mount
clawctl clean
clawctl user add testuser
clawctl start testuser

# Verify mount in container
docker exec openclaw-testuser ls -la /mnt/knowledge/
```

### 5. Run Unit Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_docker_manager.py

# Run with coverage
pytest --cov=src/clawctl tests/

# Run specific test
pytest tests/test_docker_manager.py::TestDockerManager::test_create_container
```

## Deploying Stable Changes to Cloud

### Workflow: Test → Commit → Deploy

**1. Commit tested changes:**

```bash
# Ensure all tests pass
pytest tests/

# Commit changes
git add .
git commit -m "Add knowledge directory mount support"
git push origin main
```

**2. Deploy to Lightsail:**

```bash
# Option A: Use deployment script (recommended)
cd deploy/lightsail
./07-deploy-updates.sh

# Option B: Manual deployment
ssh -p 2222 -i <key> openclaw@<ip>
cd ~/openclaw
git pull origin main
clawctl update --config clawctl.toml
clawctl restart-all --config clawctl.toml
```

### Deployment Script Details

**`07-deploy-updates.sh`** automatically:
1. Pushes local changes to git
2. Pulls changes on Lightsail
3. Rebuilds Docker image
4. Restarts containers (rolling update)
5. Verifies deployment

**Usage:**
```bash
cd deploy/lightsail
source scripts/load-config.sh  # Loads .lightsail-config
./07-deploy-updates.sh
```

## Version Control Strategy

### Branching Model

- **`main`** - Stable, tested code (deployed to cloud)
- **`develop`** - Integration branch for features
- **`feature/*`** - Feature branches for development

### Workflow

```
Local Development:
  1. Create feature branch: git checkout -b feature/knowledge-mount
  2. Make changes, test locally
  3. Commit: git commit -m "Add knowledge directory mount"
  4. Test: pytest tests/ && clawctl user add testuser
  5. Merge to develop: git checkout develop && git merge feature/knowledge-mount

Cloud Deployment:
  1. Merge develop → main: git checkout main && git merge develop
  2. Push: git push origin main
  3. Deploy: ./deploy/lightsail/07-deploy-updates.sh
```

## Testing Checklist

Before deploying to Lightsail, verify locally:

- [ ] All unit tests pass: `pytest tests/`
- [ ] Code lints cleanly (if linter configured)
- [ ] Can create user: `clawctl user add testuser`
- [ ] Container starts: `clawctl start testuser`
- [ ] Container accessible: `clawctl status`
- [ ] Knowledge directory mounts (if applicable)
- [ ] Discord/Slack channels work (if applicable)
- [ ] Secrets are properly loaded
- [ ] Logs show no errors: `clawctl logs testuser`
- [ ] Can clean up: `clawctl clean`

## Hotfix Workflow

For urgent fixes:

```bash
# Local: Create hotfix branch
git checkout -b hotfix/critical-fix main

# Make fix, test locally
clawctl user add testuser
clawctl start testuser
# ... verify fix works ...

# Commit and push
git commit -m "Fix critical issue"
git push origin hotfix/critical-fix

# Deploy directly to Lightsail
cd deploy/lightsail
source scripts/load-config.sh
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" << EOF
cd ~/openclaw
git fetch origin
git checkout hotfix/critical-fix
clawctl update --config clawctl.toml
clawctl restart-all --config clawctl.toml
EOF

# Merge back to main after verification
git checkout main
git merge hotfix/critical-fix
git push origin main
```

## Code Changes Workflow

### Adding New Features

1. **Create feature branch:**
   ```bash
   git checkout -b feature/new-feature
   ```

2. **Make changes:**
   - Edit source code
   - Add tests
   - Update documentation

3. **Test locally:**
   ```bash
   pytest tests/
   clawctl user add testuser
   # Test feature works
   ```

4. **Commit and push:**
   ```bash
   git add .
   git commit -m "Add new feature"
   git push origin feature/new-feature
   ```

5. **Merge to develop:**
   ```bash
   git checkout develop
   git merge feature/new-feature
   ```

6. **Deploy to cloud (after merge to main):**
   ```bash
   ./deploy/lightsail/07-deploy-updates.sh
   ```

### Modifying Docker Configuration

1. **Edit Docker files:**
   - `docker/Dockerfile`
   - `docker/entrypoint.sh`

2. **Test locally:**
   ```bash
   docker build -t openclaw-instance:latest docker/
   clawctl user add testuser
   clawctl start testuser
   ```

3. **Deploy:**
   ```bash
   ./deploy/lightsail/07-deploy-updates.sh
   ```

### Modifying Configuration Models

1. **Edit models:**
   - `src/clawctl/models/config.py`

2. **Update TOML schema:**
   - `config/clawctl.example.toml`

3. **Test:**
   ```bash
   pytest tests/test_config.py
   clawctl config validate
   ```

## Debugging

### Local Debugging

```bash
# Check container logs
docker logs openclaw-testuser

# Execute commands in container
docker exec -it openclaw-testuser bash

# Check volume mounts
docker inspect openclaw-testuser | grep -A 20 Mounts

# Check network
docker network inspect openclaw-net-testuser
```

### Remote Debugging

```bash
# SSH to server
source deploy/lightsail/scripts/load-config.sh
ssh -p "$SSH_PORT" -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP"

# Check containers
docker ps -a
docker logs openclaw-user1

# Check configuration
cat ~/openclaw/clawctl.toml

# Check secrets
ls -la ~/data/secrets/user1/

# Check knowledge directory
ls -la ~/data/knowledge/
docker exec openclaw-user1 ls -la /mnt/knowledge/
```

## Best Practices

1. **Always test locally first** - Catch issues before cloud deployment
2. **Write tests** - Add unit tests for new features
3. **Small commits** - Commit frequently with clear messages
4. **Document changes** - Update README and docs as needed
5. **Verify deployment** - Always check status after deployment
6. **Monitor logs** - Watch container logs for errors
7. **Backup before changes** - Create snapshot before major updates

## Continuous Integration (Future)

Example GitHub Actions workflow:

```yaml
# .github/workflows/test.yml
name: Test and Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pip install -e ".[dev]"
      - run: pytest tests/
  
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to Lightsail
        run: |
          cd deploy/lightsail
          ./07-deploy-updates.sh
        env:
          LIGHTSAIL_IP: ${{ secrets.LIGHTSAIL_IP }}
          SSH_KEY: ${{ secrets.SSH_KEY }}
```

## Related Documentation

- [Main Deployment Guide](README.md)
- [SOPs](docs/) - Manual setup procedures
- [Configuration Reference](.lightsail-config.example)
