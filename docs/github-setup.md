# GitHub Repository Access Setup

Configure your OpenClaw agent to clone and push to GitHub repositories
using a dedicated bot account and a classic Personal Access Token (PAT).

## Overview

The agent runs inside a Docker container. On startup the entrypoint:

1. Reads the PAT from `/run/secrets/gh_token` and exports it as `GH_TOKEN`
2. Runs `gh auth setup-git` so plain `git clone`/`push` over HTTPS uses the token
3. Sets `git config --global user.name/email` from `GIT_USER_NAME`/`GIT_USER_EMAIL`
4. Auto-clones repos listed in `.git-repos.json` into the workspace

The token never appears in git URLs, `.git/config`, or shell history.

## Step 1: Create a dedicated GitHub bot account

Create a new GitHub account the agent will commit as (e.g. `omar-bot`).

- Go to [github.com/signup](https://github.com/signup)
- Use a distinct email (e.g. `omar+bot@atthought.com`)
- Pick a recognizable username so commits are clearly from the bot

## Step 2: Invite the bot as a collaborator

**Personal repositories:**

1. Go to your repo → **Settings** → **Collaborators** (under "Access")
2. Click **Add people**, search for the bot account, click **Add**
   (personal repo collaborators automatically get push access)
3. Log in as the bot and **accept the invitation**

**Organization repositories:**

1. On each repo: **Settings** → **Collaborators and teams** → **Add people** → choose **Write** role
2. Or create a Team with Write access and add the bot to it

## Step 3: Create a classic PAT on the bot account

Fine-grained PATs only cover repos the token owner **owns**. Since the bot
is a collaborator (not owner), use a **classic** PAT instead.

1. Log in as the bot account
2. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
3. Click **Generate new token** → **Generate new token (classic)**
4. Fill in:
   - **Note**: `openclaw-agent`
   - **Expiration**: 90 days (set a reminder to rotate)
5. Under **Select scopes**, check **`repo`**
6. Click **Generate token** and copy the value (`ghp_...`) immediately

The access boundary comes from the collaborator invitations — the bot can
only push to repos where you explicitly granted access.

## Step 4: Store the token as a secret

```bash
mkdir -p ~/.config/openclaw/secrets/<username>
echo "<paste-token>" > ~/.config/openclaw/secrets/<username>/gh_token
chmod 600 ~/.config/openclaw/secrets/<username>/gh_token
```

## Step 5: Configure clawctl.toml

```toml
[[users]]
name = "omar"
port = 18001

[users.secrets]
openrouter_api_key = "openrouter_api_key"
gh_token = "gh_token"

[users.git]
user_name = "omarlit32"
email = "omar@atthought.com"
token_secret = "gh_token"

# Repos to auto-clone into the workspace on container start
[[users.git.repos]]
url = "https://github.com/your-org/project-alpha.git"
branch = "main"
path = "project-alpha"

[[users.git.repos]]
url = "https://github.com/your-org/project-beta.git"
branch = "develop"
path = "project-beta"
```

- **`token_secret`**: filename in the secrets directory (becomes `GH_TOKEN` env var)
- **`path`**: clone destination relative to `/home/node/.openclaw/workspace/`
- **`branch`**: branch to check out (default: `main`)
- Repos that already exist on disk are skipped (not re-cloned)

## Step 6: Deploy

```bash
clawctl server deploy -c personal.toml
```

On the next container start the agent can `git clone`, `git push`, and
`gh pr create` against any repo the bot account has access to.

## Token rotation

When your token is about to expire:

1. Generate a new classic PAT (same steps as above)
2. Replace the secret:
   ```bash
   echo "<new-token>" > ~/.config/openclaw/secrets/<username>/gh_token
   chmod 600 ~/.config/openclaw/secrets/<username>/gh_token
   ```
3. Redeploy: `clawctl server deploy -c personal.toml`
4. Restart the container so it picks up the new token

## Security checklist

- [ ] Bot account invited as collaborator only on repos the agent needs
- [ ] Classic PAT has only the `repo` scope
- [ ] Token has an expiration date (90 days recommended)
- [ ] Secret file has 0600 permissions (owner read/write only)
- [ ] Token is not committed to any git repo (secrets dir is in `.gitignore`)
