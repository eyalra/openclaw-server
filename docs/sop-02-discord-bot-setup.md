# SOP-02: Discord Bot Setup

## Purpose

Create a Discord bot application and configure it for use with OpenClaw. This bot will serve as the secure communication channel for users to interact with their OpenClaw instances.

## Prerequisites

- Discord account (free account works)
- Access to a Discord server (or ability to create one)
- Web browser for Discord Developer Portal
- **Estimated time:** 10 minutes

**Note:** Discord bot creation does NOT require phone verification, making it ideal for initial setup.

## Procedure

### Step 1: Access Discord Developer Portal

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Log in with your Discord account
3. Click **"New Application"** button (top right)

### Step 2: Create Application

1. **Application name:** Enter a name (e.g., `OpenClaw`, `MyOpenClawBot`)
2. **Application description:** Optional - describe your bot
3. Click **"Create"**
4. You'll be taken to the application dashboard

### Step 3: Create Bot

1. In the left sidebar, click **"Bot"**
2. Click **"Add Bot"** button
3. Confirm by clicking **"Yes, do it!"**
4. Your bot is now created

### Step 4: Configure Bot Settings

**Bot username:**
- The bot's display name (can be changed later)
- This is what users will see in Discord

**Bot icon:**
- Optional: Upload an avatar image
- Recommended: 512x512 pixels

**Public Bot:**
- Leave **unchecked** (unless you want others to invite your bot)
- For private use, keep it unchecked

### Step 5: Enable Privileged Gateway Intents

**CRITICAL:** This step is required for the bot to read message content.

1. Scroll down to **"Privileged Gateway Intents"** section
2. Enable **"MESSAGE CONTENT INTENT"**
   - This allows the bot to read message content
   - Required for OpenClaw to process user messages
3. Click **"Save Changes"** at the bottom

**Note:** Enabling this intent may require verification if your bot is in 100+ servers, but for private use this won't be an issue.

### Step 6: Get Bot Token

1. Still in the **"Bot"** section
2. Under **"Token"**, click **"Reset Token"** or **"Copy"**
3. **IMPORTANT:** Copy the token immediately
   - Token format: Starts with `MT...` or `OD...` (long string)
   - This token is shown only once
   - If you lose it, you'll need to reset it
4. **Save the token securely** - you'll need it in Phase 5 of deployment

**Security Best Practices:**
- Never share this token publicly
- Never commit it to git
- Store it in `.lightsail-config` or secret management system
- If token is compromised, reset it immediately

### Step 7: Configure OAuth2 & Permissions

1. In left sidebar, click **"OAuth2"**
2. Click **"URL Generator"** submenu

**Select Scopes:**
- Check **`bot`** (required)

**Select Bot Permissions:**
Under **"Bot Permissions"**, enable:
- **Text Permissions:**
  - ✅ Send Messages
  - ✅ Read Message History
  - ✅ Use Slash Commands
  - ✅ Embed Links (optional, for rich responses)
  - ✅ Attach Files (optional)
- **General Permissions:**
  - ✅ View Channels (if needed)

**Note:** You can add more permissions later if needed.

### Step 8: Generate Invite URL

1. After selecting scopes and permissions, an **"Invite URL"** appears at the bottom
2. Copy this URL (it will look like):
   ```
   https://discord.com/api/oauth2/authorize?client_id=...&permissions=...&scope=bot
   ```
3. Save this URL - you'll use it to invite the bot to your server

### Step 9: Invite Bot to Discord Server

1. Open the invite URL in a new browser tab
2. Select the Discord server where you want to add the bot
3. Click **"Authorize"**
4. Complete any CAPTCHA if prompted
5. Bot should now appear in your server's member list (may show as offline initially)

**Note:** You must have "Manage Server" permission on the Discord server to invite bots.

### Step 10: Verify Bot in Server

1. Go to your Discord server
2. Check member list - bot should appear (may be offline)
3. Bot will come online when OpenClaw container starts
4. Bot username should match what you configured in Step 4

### Step 11: Configure Server Permissions (Optional)

**Set up bot permissions per channel:**

1. Right-click on a channel → **"Edit Channel"**
2. Go to **"Permissions"** tab
3. Add bot role/user
4. Configure channel-specific permissions:
   - **View Channel:** ✅
   - **Send Messages:** ✅
   - **Read Message History:** ✅

**Or use server-wide permissions:**
- Server Settings → Roles → Bot Role → Permissions

## Verification

**Checklist:**
- [ ] Application created in Developer Portal
- [ ] Bot created and added to application
- [ ] MESSAGE CONTENT INTENT enabled
- [ ] Bot token copied and saved securely
- [ ] OAuth2 URL generated with correct permissions
- [ ] Bot invited to Discord server
- [ ] Bot appears in server member list
- [ ] Bot has appropriate channel permissions

**Test bot token (optional):**
```bash
# Test token format (should be long string starting with MT or OD)
echo "Your token starts with: ${DISCORD_TOKEN:0:2}"
```

## Troubleshooting

**Bot token not working:**

- **Check token:** Ensure you copied the complete token (no spaces/line breaks)
- **Reset token:** If token is lost, reset it in Developer Portal → Bot → Reset Token
- **Verify format:** Token should be ~70 characters, starts with `MT` or `OD`

**Bot not appearing in server:**

- **Check invite URL:** Ensure you used the correct OAuth2 URL
- **Verify permissions:** You need "Manage Server" permission
- **Check server:** Ensure you selected the correct server when authorizing
- **Re-invite:** Try generating a new invite URL and inviting again

**Bot can't read messages:**

- **Check intent:** MESSAGE CONTENT INTENT must be enabled
- **Verify permissions:** Bot needs "Read Message History" permission
- **Check channel:** Bot needs access to the channel
- **Restart container:** After fixing permissions, restart OpenClaw container

**Bot shows offline:**

- This is normal until OpenClaw container starts
- Bot will come online when container connects
- Check container logs if bot stays offline: `docker logs openclaw-user1`

**Permission denied errors:**

- **Check bot role:** Ensure bot has necessary permissions in server
- **Channel permissions:** Verify bot can access specific channels
- **Server permissions:** Check server-wide bot permissions
- **Re-invite:** Generate new invite URL with updated permissions

## Security Considerations

**Token Security:**
- Never commit bot token to git
- Store in `.lightsail-config` (gitignored) or secret management
- If token is exposed, reset it immediately in Developer Portal
- Use different bots for different environments (dev/prod)

**Server Security:**
- Only invite bot to trusted servers
- Limit bot permissions to minimum required
- Monitor bot activity for unusual behavior
- Regularly rotate tokens (reset every 90 days recommended)

## Next Steps

After completing this SOP:

1. **Save bot token** - You'll need it when running `04-configure-users.sh`
2. **Proceed to:** [SOP-03: Tailscale Setup](SOP-03-tailscale-setup.md) (can be done in parallel)
3. **Or continue:** Run deployment scripts starting with `01-harden-server.sh`

## Related Documentation

- [Discord Developer Documentation](https://discord.com/developers/docs/)
- [Discord Bot Best Practices](https://discord.com/developers/docs/topics/community-resources)
- [Main Deployment Guide](../README.md)
