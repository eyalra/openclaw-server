# Managing Server Files

How to update the read-only files available inside user containers.

## Overview

Each user container has several read-only bind mounts supplied by the host.
Because they are bind mounts, updating the files on the host side is
immediately visible inside running containers — no restart is needed unless a
**new mount point** was added after the container was created.

| Mount point (in container) | Host path | Updated via |
|---|---|---|
| `/mnt/files` | `data/users/<user>/files/` | `clawctl files push` |
| `/mnt/shared/<collection>/` | `data/shared/<collection>/` | `clawctl shared-collections sync` |
| `/mnt/knowledge` *(deprecated)* | `data/knowledge/` | Manual `scp`/`rsync` |
| `/run/secrets` | `data/secrets/<user>/` | `clawctl server deploy` |

## Per-User Files (`/mnt/files`)

Push individual files or entire directories to a user's container.

```bash
# Push a single file
clawctl files push <username> report.pdf

# Push to a specific subdirectory inside /mnt/files
clawctl files push <username> data.csv --dest reports/q4.csv

# Push a whole directory
clawctl files push <username> ./reference-docs/

# Mark a script as executable
clawctl files push <username> run.sh --executable

# List everything pushed to a user
clawctl files list <username>

# Verify checksums
clawctl files verify <username>

# Remove a single file
clawctl files remove <username> reports/q4.csv

# Remove everything
clawctl files remove-all <username> --yes
```

Files land on the host at `data/users/<username>/files/` and appear
read-only inside the container at `/mnt/files`.

## Shared Collections (`/mnt/shared/`)

Shared collections sync documents from S3 or a local directory and make them
available to all (or specific) users.

### Configuration

Add a `[clawctl.shared_collections]` section to your `clawctl.toml`:

```toml
[clawctl.shared_collections]
source_type = "s3"            # "s3" or "local"
s3_bucket = "company-docs"
s3_prefix = "shared/"
sync_schedule = "daily"       # "daily", "hourly", or "HH:MM"
collections = ["newsletters", "company-docs"]

# Restrict a collection to specific users
[[clawctl.shared_collections.drives]]
name = "engineering"
users = ["alice", "bob"]
```

### Syncing

```bash
# Sync all collections
clawctl shared-collections sync

# Sync a single collection
clawctl shared-collections sync newsletters

# List configured collections and their status
clawctl shared-collections list
```

### Automatic sync daemon

```bash
clawctl shared-collections schedule start   # start background sync
clawctl shared-collections schedule status  # check if running
clawctl shared-collections schedule stop    # stop the daemon
```

## Knowledge Directory (`/mnt/knowledge`) — Deprecated

> Use shared collections instead. The knowledge mount is kept for backward
> compatibility only.

Copy files directly to the server:

```bash
scp -P 2222 -r ./knowledge-files/ openclaw@<server-ip>:/home/openclaw/data/knowledge/
```

## Code & Application Updates

Deploy updated clawctl/clawlib code and rebuild containers:

```bash
clawctl server deploy -c personal.toml    # rsync code + secrets to server
clawctl server setup -c personal.toml     # rebuild image, recreate containers
```

## When Do I Need to Restart Containers?

| Change | Restart needed? |
|---|---|
| Updated files in an existing mount | No — bind mounts reflect changes immediately |
| New secret added to config | Yes — `clawctl server deploy` + `clawctl server setup` |
| New shared collection added to config | Yes — new mount must be added to the container |
| Code/image change | Yes — `clawctl server setup` recreates containers |

To restart a single user or all users:

```bash
clawctl instance restart <username>
clawctl instance restart-all
```
