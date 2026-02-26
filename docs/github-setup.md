# GitHub Repository Access Setup

Configure your OpenClaw agent to clone and push to specific GitHub repositories
using a fine-grained Personal Access Token (PAT).

## Why fine-grained PATs?

GitHub offers two kinds of tokens:

| | Classic PAT | Fine-grained PAT |
|---|---|---|
| Scope | All repos you can access | Only repos you select |
| Permissions | Coarse (e.g. `repo` = everything) | Granular (e.g. Contents: read+write) |
| Expiration | Optional | Required (max 1 year) |
| Audit | Limited | Full audit log |

Fine-grained PATs follow the principle of least privilege: the token can only
access the exact repositories and permissions you choose.

## Step 1: Create a fine-grained PAT

1. Go to [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta)
2. Click **Generate new token**
3. Fill in:
   - **Token name**: `openclaw-<username>` (e.g. `openclaw-omar`)
   - **Expiration**: 90 days is a good balance (set a calendar reminder to rotate)
   - **Resource owner**: Your personal account or organization
4. Under **Repository access**, select **Only select repositories** and pick
   the specific repos the agent needs
5. Under **Permissions → Repository permissions**, set:
   - **Contents**: Read and write (needed for clone + push)
   - Leave everything else at "No access"
6. Click **Generate token** and copy the value (starts with `github_pat_...`)

## Step 2: Store the token as a secret

```bash
# Create the user's secrets directory if it doesn't exist
mkdir -p ~/.config/openclaw/secrets/<username>

# Write the token (paste when prompted, then Ctrl-D)
cat > ~/.config/openclaw/secrets/<username>/github_token
# <paste token, press Enter, then Ctrl-D>

# Lock down permissions
chmod 600 ~/.config/openclaw/secrets/<username>/github_token
```

The token file is mounted read-only into the container at `/run/secrets/github_token`
and used by a credential helper -- it never appears in git URLs, `.git/config`, or
shell history.

## Step 3: Configure your clawctl.toml

Add the token to the user's secrets and configure the git section:

```toml
[[users]]
name = "omar"
port = 18001

[users.secrets]
openrouter_api_key = "openrouter_api_key"
github_token = "github_token"

[users.git]
user_name = "Omar (bot)"
email = "omar@atthought.com"
token_secret = "github_token"

[[users.git.repos]]
url = "https://github.com/your-org/project-alpha.git"
branch = "main"
path = "projects/project-alpha"

[[users.git.repos]]
url = "https://github.com/your-org/project-beta.git"
branch = "develop"
path = "projects/project-beta"
```

- **`token_secret`**: references the filename in the secrets directory
- **`path`**: relative to the agent's workspace (`/home/node/.openclaw/workspace/`)
- **`branch`**: the branch to clone and track (default: `main`)

## Step 4: Verify the token works

Before deploying, test the token locally:

```bash
# Test read access
GIT_TOKEN=$(cat ~/.config/openclaw/secrets/<username>/github_token)
git ls-remote "https://x-access-token:${GIT_TOKEN}@github.com/your-org/project-alpha.git"

# You should see a list of refs (branches/tags). If you get a 401, the token
# is invalid or doesn't have access to that repo.
```

## Step 5: Deploy

```bash
clawctl server deploy -c personal.toml
```

On the next container start, the agent will automatically:
1. Configure git with the credential helper (reads token from `/run/secrets/`)
2. Set `user.name` and `user.email` for commits
3. Clone any repos that don't exist yet
4. Pull updates for repos that already exist

You can also trigger a manual sync:

```bash
clawctl git sync <username> -c personal.toml
```

## Token rotation

Fine-grained PATs expire. When yours is about to expire:

1. Generate a new token (same steps as above)
2. Replace the secret file:
   ```bash
   cat > ~/.config/openclaw/secrets/<username>/github_token
   # <paste new token, Ctrl-D>
   chmod 600 ~/.config/openclaw/secrets/<username>/github_token
   ```
3. Redeploy: `clawctl server deploy -c personal.toml`
4. Restart the user's container so it picks up the new token

## Security checklist

- [ ] Token scoped to **only the repos** the agent needs (not "All repositories")
- [ ] Only **Contents: Read and write** permission granted
- [ ] Token has an **expiration date** (90 days recommended)
- [ ] Secret file has **0600 permissions** (owner read/write only)
- [ ] Token is **not committed** to any git repo (secrets dir is in `.gitignore`)
