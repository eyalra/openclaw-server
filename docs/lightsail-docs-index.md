# OpenClaw Lightsail Deployment Documentation

This directory contains Standard Operating Procedures (SOPs) for manual setup tasks required before automated deployment scripts can run.

## Documentation Index

### Setup Procedures

1. **[SOP-01: Lightsail Instance Setup](SOP-01-lightsail-setup.md)**
   - Creating AWS Lightsail instance
   - Configuring firewall rules
   - Setting up SSH access
   - **Estimated time:** 15 minutes

2. **[SOP-02: Discord Bot Setup](SOP-02-discord-bot-setup.md)**
   - Creating Discord application
   - Configuring bot permissions
   - Getting bot token
   - **Estimated time:** 10 minutes

3. **[SOP-03: Tailscale Setup](SOP-03-tailscale-setup.md)**
   - Installing Tailscale on Lightsail
   - Authenticating and connecting
   - Configuring local access
   - **Estimated time:** 10 minutes

## Prerequisites Checklist

Before starting deployment, ensure you have:

- [ ] AWS account with Lightsail access
- [ ] Tailscale account (free tier works)
- [ ] Discord account (for bot creation)
- [ ] API keys ready:
  - [ ] Anthropic API key (for production)
  - [ ] OR OpenRouter API key (for testing)
- [ ] SSH key pair (Lightsail will generate or use existing)

## Quick Start

1. **Follow SOP-01** to create Lightsail instance
2. **Follow SOP-02** to create Discord bot
3. **Follow SOP-03** to set up Tailscale
4. Create `.lightsail-config` from `.lightsail-config.example`
5. Run deployment scripts in order (01-05)

## Related Documentation

- [Main Deployment Guide](../README.md)
- [Development Workflow](../DEVELOPMENT.md)
- [Configuration Reference](../.lightsail-config.example)
