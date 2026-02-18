# Slack Integration Setup Guide

## Overview

OpenClaw uses Slack's **Socket Mode** for integration, which is perfect for Docker containers. Socket Mode establishes a WebSocket connection from your container to Slack, so you don't need to expose webhook endpoints.

## Prerequisites

- A Slack workspace where you have permission to install apps
- Admin access to create a Slack app

## Step-by-Step Setup

### 1. Create a Slack App

1. Go to https://api.slack.com/apps
2. Click **"Create New App"**
3. Choose **"From scratch"**
4. Enter:
   - **App Name**: `OpenClaw` (or your preferred name)
   - **Pick a workspace**: Select your workspace
5. Click **"Create App"**

### 2. Enable Socket Mode

1. In your app settings, go to **"Socket Mode"** in the left sidebar
2. Toggle **"Enable Socket Mode"** to ON
3. Click **"Generate"** under **"App-Level Tokens"**
4. Enter a name: `openclaw-socket-mode`
5. Add scope: `connections:write`
6. Click **"Generate"**
7. **Copy the token** - it starts with `xapp-...` (this is your App-Level Token)

### 3. Configure Bot Token Scopes

1. Go to **"OAuth & Permissions"** in the left sidebar
2. Scroll down to **"Scopes"** → **"Bot Token Scopes"**
3. Add the following scopes:
   - `app_mentions:read` - Listen for mentions
   - `channels:history` - Read channel messages
   - `channels:read` - View basic channel info
   - `chat:write` - Send messages
   - `im:history` - Read direct messages
   - `im:read` - View basic DM info
   - `im:write` - Send direct messages
   - `users:read` - View user info

### 4. Install App to Workspace

1. Still in **"OAuth & Permissions"**, scroll to the top
2. Click **"Install to Workspace"**
3. Review the permissions and click **"Allow"**
4. **Copy the Bot User OAuth Token** - it starts with `xoxb-...` (this is your Bot Token)

### 5. Configure OpenClaw

Now that you have both tokens:

**Bot Token**: `xoxb-...` (from OAuth & Permissions)
**App Token**: `xapp-...` (from Socket Mode)

Run the setup command:

```bash
clawctl user set-slack alice
```

This will prompt you for both tokens. Alternatively, you can provide them directly:

```bash
clawctl user set-slack alice --bot-token "xoxb-your-bot-token" --app-token "xapp-your-app-token"
```

The command will:
- Save the tokens as secrets
- Regenerate `openclaw.json` with Slack configuration
- Restart the container to apply changes

### 6. Verify Connection

Check the container logs to see if Slack connected:

```bash
clawctl logs alice
```

You should see messages about Slack connecting. Try mentioning the bot in a Slack channel:

```
@OpenClaw hello
```

## Troubleshooting

### Bot doesn't respond

1. **Check logs**: `clawctl logs alice`
2. **Verify tokens**: Make sure both tokens are correct
3. **Check scopes**: Ensure all required scopes are added
4. **Socket Mode**: Verify Socket Mode is enabled in Slack app settings

### Container won't start

1. Check if tokens are valid format:
   - Bot token: `xoxb-...`
   - App token: `xapp-...`
2. Verify secrets exist: `ls data/secrets/alice/`
3. Check container logs: `docker logs openclaw-alice`

### Token format errors

- Bot tokens must start with `xoxb-`
- App tokens must start with `xapp-`
- No extra whitespace or newlines

## Security Notes

- Tokens are stored in `data/secrets/alice/` with 0600 permissions (owner read/write only)
- Tokens are mounted read-only into containers at `/run/secrets/`
- Never commit tokens to git - they're in `.gitignore`

## Updating Tokens

To update tokens:

```bash
clawctl user set-slack alice
```

Or manually edit the secret files and restart:

```bash
# Edit tokens
nano data/secrets/alice/slack_bot_token
nano data/secrets/alice/slack_app_token

# Regenerate config and restart
clawctl config regenerate alice
clawctl restart alice
```
