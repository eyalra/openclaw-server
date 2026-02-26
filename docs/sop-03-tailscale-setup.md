# SOP-03: Tailscale Setup

## Purpose

Configure Tailscale on both the Lightsail instance and your local machine to create a secure, private mesh network. This allows secure access to OpenClaw without exposing ports to the public internet.

## Prerequisites

- Tailscale account (free tier works - up to 100 devices)
- Lightsail instance running (from SOP-01)
- SSH access to Lightsail instance
- Local machine (Mac, Windows, or Linux)
- **Estimated time:** 10 minutes

## Procedure

### Step 1: Create Tailscale Account

1. Go to [https://tailscale.com/](https://tailscale.com/)
2. Click **"Sign Up"** or **"Log In"**
3. Sign up with:
   - Google account, OR
   - Microsoft account, OR
   - Email address
4. Verify email if required
5. You'll be taken to the Tailscale admin console

**Note:** Free tier supports up to 100 devices, which is more than sufficient for this deployment.

### Step 2: Install Tailscale on Lightsail Instance

**Via SSH:**

1. Connect to your Lightsail instance:
   ```bash
   source deploy/lightsail/scripts/load-config.sh
   ssh -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP"
   ```

2. Install Tailscale:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   ```

3. Start Tailscale (interactive):
   ```bash
   sudo tailscale up
   ```

4. You'll see a message like:
   ```
   To authenticate, visit:
   https://login.tailscale.com/auth/...
   ```

5. **Copy the authentication URL** - you'll need it in the next step

### Step 3: Authenticate Tailscale (Browser)

1. Open the authentication URL from Step 2 in your web browser
2. Log in with your Tailscale account
3. Click **"Connect"** or **"Authorize"**
4. You should see a success message
5. Return to your SSH session

### Step 4: Verify Tailscale on Server

**In your SSH session:**

1. Check Tailscale status:
   ```bash
   tailscale status
   ```

2. You should see output like:
   ```
   100.x.x.x    openclaw-server    ubuntu@    linux   -
   ```

3. Get the Tailscale IP address:
   ```bash
   tailscale ip -4
   ```
   Output: `100.x.x.x` (your Tailscale IP)

4. **Save this IP** - you'll add it to `.lightsail-config`

### Step 5: Configure Tailscale to Start on Boot

**Ensure Tailscale starts automatically:**

```bash
# Enable Tailscale service
sudo systemctl enable tailscaled

# Verify it's enabled
sudo systemctl is-enabled tailscaled
# Should output: enabled
```

### Step 6: Install Tailscale on Local Machine

**macOS:**

```bash
# Using Homebrew
brew install tailscale

# Or download from: https://tailscale.com/download
```

**Linux:**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**Windows:**

1. Download installer from [https://tailscale.com/download](https://tailscale.com/download)
2. Run installer
3. Follow setup wizard

### Step 7: Connect Local Machine to Tailscale

1. **macOS:** Open Tailscale app from Applications
2. **Linux:** Run `sudo tailscale up`
3. **Windows:** Tailscale should start automatically after installation

4. Sign in with the same Tailscale account used in Step 1
5. Your local machine will appear in Tailscale admin console

### Step 8: Verify Connection

**Test connectivity:**

1. Get server Tailscale IP (from Step 4): `100.x.x.x`
2. Get local Tailscale IP:
   ```bash
   tailscale ip -4
   ```

3. Test connection from local machine:
   ```bash
   # Ping server
   ping 100.x.x.x
   
   # Or test SSH via Tailscale
   ssh ubuntu@100.x.x.x
   ```

4. Both devices should appear in Tailscale admin console:
   - [https://login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines)

### Step 9: Update Local Configuration

1. Edit `.lightsail-config`:
   ```bash
   cd deploy/lightsail
   nano .lightsail-config  # or use your preferred editor
   ```

2. Update Tailscale settings:
   ```bash
   TAILSCALE_IP="100.x.x.x"  # From Step 4
   ```

3. Save and verify:
   ```bash
   source scripts/load-config.sh
   echo "Tailscale IP: $TAILSCALE_IP"
   ```

### Step 10: Configure Firewall for Tailscale (Optional)

**Allow Tailscale network in UFW (will be done in hardening script):**

```bash
# On Lightsail instance
sudo ufw allow from 100.64.0.0/10
sudo ufw reload
```

**Note:** This will be automated in `01-harden-server.sh`, but you can do it manually if needed.

## Verification

**Checklist:**
- [ ] Tailscale account created
- [ ] Tailscale installed on Lightsail instance
- [ ] Instance authenticated via browser
- [ ] Tailscale IP obtained: `100.x.x.x`
- [ ] Tailscale installed on local machine
- [ ] Local machine connected to same Tailnet
- [ ] Can ping server via Tailscale IP
- [ ] Both devices visible in Tailscale admin console
- [ ] `.lightsail-config` updated with Tailscale IP

**Test connectivity:**

```bash
# From local machine
source deploy/lightsail/scripts/load-config.sh

# Ping via Tailscale
ping "$TAILSCALE_IP"

# SSH via Tailscale (alternative to public IP)
ssh -i "$SSH_KEY" "$SSH_USER@$TAILSCALE_IP"
```

**Verify in Tailscale console:**
- Go to [https://login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines)
- Both your local machine and Lightsail instance should appear
- Both should show as "Online"

## Troubleshooting

**Tailscale not starting on server:**

```bash
# Check service status
sudo systemctl status tailscaled

# Restart service
sudo systemctl restart tailscaled

# Check logs
sudo journalctl -u tailscaled -f
```

**Cannot authenticate:**

- **Check URL:** Ensure you copied the complete authentication URL
- **Browser:** Try a different browser or incognito mode
- **Account:** Ensure you're logged into the correct Tailscale account
- **Timeout:** Authentication URLs expire - generate a new one with `sudo tailscale up`

**Devices can't see each other:**

- **Same account:** Ensure both devices use the same Tailscale account
- **Admin console:** Check both devices appear in [admin console](https://login.tailscale.com/admin/machines)
- **Firewall:** Ensure Tailscale network is allowed in UFW
- **Restart:** Try restarting Tailscale on both devices

**Cannot ping via Tailscale IP:**

- **Check IPs:** Verify both devices have Tailscale IPs (`tailscale ip -4`)
- **Firewall:** Check UFW allows Tailscale network (100.64.0.0/10)
- **Routing:** Verify Tailscale is running on both devices
- **Admin console:** Check device status in Tailscale admin console

**Tailscale IP keeps changing:**

- Tailscale IPs are stable but can change if device is removed/re-added
- Use Tailscale MagicDNS for stable hostnames: `openclaw-server.tailnet-name.ts.net`
- Or use Tailscale admin console to see current IPs

**Connection slow:**

- Tailscale uses direct connection when possible
- Check network connectivity on both ends
- Use Tailscale admin console to see connection status
- Consider using Tailscale's relay if direct connection fails

## Advanced Configuration (Optional)

### Use MagicDNS

Tailscale provides DNS names for devices:

```bash
# Access server via hostname instead of IP
ssh ubuntu@openclaw-server.your-tailnet.ts.net
```

### Access Control Lists (ACLs)

Configure who can access what:

1. Go to Tailscale admin console
2. Settings → Access Controls
3. Configure ACLs to restrict access if needed

### Subnet Routing (Advanced)

Route entire subnets through Tailscale:

1. Enable subnet routing in admin console
2. Configure on server: `sudo tailscale up --advertise-routes=...`
3. Approve in admin console

## Security Considerations

**Network Security:**
- Tailscale encrypts all traffic end-to-end
- No need for VPN configuration
- Access is limited to devices on your Tailnet
- Can configure ACLs for fine-grained access control

**Best Practices:**
- Use different Tailnets for different environments (dev/prod)
- Regularly review devices in admin console
- Remove unused devices
- Use ACLs to limit access if needed

## Next Steps

After completing this SOP:

1. **Update `.lightsail-config`** with Tailscale IP
2. **Proceed to:** Run `01-harden-server.sh` to secure the server
3. **After deployment:** Access OpenClaw web UI via Tailscale IP:
   ```
   http://<tailscale-ip>:18789
   ```

## Related Documentation

- [Tailscale Documentation](https://tailscale.com/kb/)
- [Tailscale Admin Console](https://login.tailscale.com/admin)
- [Main Deployment Guide](../README.md)
