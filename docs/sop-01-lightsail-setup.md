# SOP-01: AWS Lightsail Instance Setup

## Purpose

Create and configure an AWS Lightsail instance for hosting OpenClaw containers. This procedure covers instance creation, firewall configuration, and initial SSH access setup.

## Prerequisites

- AWS account with Lightsail access
- Access to AWS Console
- Basic understanding of cloud instances
- **Estimated time:** 15 minutes

## Procedure

### Step 1: Access AWS Lightsail Console

1. Log in to [AWS Console](https://console.aws.amazon.com/)
2. Navigate to **Lightsail** service
3. Click **"Create instance"** button

### Step 2: Configure Instance Settings

**Instance location:**
- Choose your preferred AWS region (e.g., `us-east-1`, `us-west-2`)
- Note the region - you'll need it for `.lightsail-config`

**Platform:**
- Select **Linux/Unix**

**Blueprint:**
- Choose **Ubuntu 24.04 LTS** (or latest LTS version)

**Instance plan:**
- Select **Medium** plan:
  - 2 vCPU
  - 4GB RAM
  - 60GB SSD storage
  - 3TB data transfer
  - **Cost:** $20/month

**Alternative plans:**
- **Small** ($10/month): 1 vCPU, 2GB RAM - may be insufficient for 2+ users
- **Large** ($40/month): 4 vCPU, 8GB RAM - for scaling beyond 5 users

### Step 3: Name Your Instance

- **Instance name:** `openclaw-server` (or your preferred name)
- This name will appear in Lightsail console
- Note the name - you'll add it to `.lightsail-config`

### Step 4: SSH Key Pair Setup

**Option A: Create New Key Pair (Recommended for first-time setup)**

1. Under **"SSH key pair"**, select **"Create new"**
2. Choose key pair name: `openclaw-lightsail-key`
3. Click **"Download"** to save the `.pem` file
4. **IMPORTANT:** Save the key file securely:
   ```bash
   # Move to ~/.ssh/ directory
   mv ~/Downloads/openclaw-lightsail-key.pem ~/.ssh/
   
   # Set correct permissions (required for SSH)
   chmod 600 ~/.ssh/openclaw-lightsail-key.pem
   ```
5. Note the key path - you'll add it to `.lightsail-config`

**Option B: Use Existing Key Pair**

1. If you already have a Lightsail key pair, select it from the dropdown
2. Ensure you have the corresponding `.pem` file locally
3. Verify permissions: `chmod 600 ~/.ssh/your-key.pem`

### Step 5: Launch Instance

1. Review your settings
2. Click **"Create instance"**
3. Wait for instance to start (1-2 minutes)
4. Instance status will show **"Running"** when ready

### Step 6: Configure Firewall Rules

1. Click on your instance name to open instance details
2. Go to **"Networking"** tab
3. Under **"Firewall"**, click **"Add rule"**

**Add SSH rule for port 2222:**
- **Application:** Custom
- **Protocol:** TCP
- **Port:** `2222`
- **Source:** 
  - **Option 1:** Your IP address (most secure)
  - **Option 2:** `0.0.0.0/0` (temporarily, for initial setup)
- Click **"Create"**

**Keep port 22 open initially:**
- Do NOT delete the default SSH rule (port 22) yet
- This is your safety net if port 2222 configuration fails
- You'll remove it after verifying SSH on port 2222 works

### Step 7: Get Instance IP Address

**Option A: Use Static IP (Recommended)**

1. In instance details, go to **"Networking"** tab
2. Under **"Public IP"**, click **"Create static IP"**
3. Name: `openclaw-static-ip`
4. Attach to instance: Select your instance
5. Click **"Create"**
6. Note the static IP address (e.g., `54.123.45.67`)

**Option B: Use Dynamic IP**

1. In instance details, find **"Public IP"** address
2. Note the IP address
3. **Warning:** This IP will change if you stop/start the instance

### Step 8: Update Local Configuration

1. Copy the example config file:
   ```bash
   cd deploy/lightsail
   cp .lightsail-config.example .lightsail-config
   ```

2. Edit `.lightsail-config` and update:
   ```bash
   LIGHTSAIL_IP="<your-static-ip>"              # From Step 7
   LIGHTSAIL_INSTANCE_NAME="openclaw-server"    # From Step 3
   AWS_REGION="us-east-1"                       # From Step 2
   SSH_KEY="$HOME/.ssh/openclaw-lightsail-key.pem"  # From Step 4
   SSH_USER="ubuntu"                            # Default for Ubuntu
   SSH_PORT="22"                                # Will change to 2222 after hardening
   ```

3. Set secure permissions:
   ```bash
   chmod 600 .lightsail-config
   ```

### Step 9: Test Initial SSH Connection

```bash
# Load config
source deploy/lightsail/scripts/load-config.sh

# Test SSH connection (using default port 22)
ssh -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP"

# If successful, you should see Ubuntu welcome message
# Type 'exit' to disconnect
```

## Verification

**Checklist:**
- [ ] Instance is running in Lightsail console
- [ ] Static IP is assigned (if using)
- [ ] Firewall rule for port 2222 is added
- [ ] Port 22 firewall rule still exists (safety net)
- [ ] SSH key file exists locally with 600 permissions
- [ ] Can SSH to instance using default port 22
- [ ] `.lightsail-config` file is created and populated
- [ ] `.lightsail-config` has 600 permissions

**Test SSH connection:**
```bash
source deploy/lightsail/scripts/load-config.sh
ssh -i "$SSH_KEY" "$SSH_USER@$LIGHTSAIL_IP" "echo 'Connection successful'"
```

## Troubleshooting

**Cannot connect via SSH:**

- **Check firewall:** Ensure port 22 rule exists in Lightsail console
- **Verify IP:** Confirm you're using the correct IP address
- **Check key permissions:** `chmod 600 ~/.ssh/your-key.pem`
- **Verify key format:** Ensure key file is `.pem` format (not `.ppk`)
- **Check instance status:** Instance must be "Running" in console

**Key permission denied:**

```bash
# Fix permissions
chmod 600 ~/.ssh/openclaw-lightsail-key.pem

# Verify
ls -l ~/.ssh/openclaw-lightsail-key.pem
# Should show: -rw------- (600)
```

**Instance not starting:**

- Check AWS service limits
- Verify account has Lightsail access
- Check for any error messages in Lightsail console
- Try a different region if current region has capacity issues

**Cannot create static IP:**

- Ensure instance is running
- Check if you've reached static IP limit (5 per region)
- Try attaching to instance from Networking tab instead

## Next Steps

After completing this SOP:

1. **Proceed to:** [SOP-02: Discord Bot Setup](SOP-02-discord-bot-setup.md) (can be done in parallel)
2. **Then run:** `01-harden-server.sh` to secure SSH and configure server
3. **After hardening:** Update `.lightsail-config` with `SSH_PORT="2222"`

## Related Documentation

- [AWS Lightsail Documentation](https://docs.aws.amazon.com/lightsail/)
- [Lightsail Pricing](https://aws.amazon.com/lightsail/pricing/)
- [Main Deployment Guide](../README.md)
