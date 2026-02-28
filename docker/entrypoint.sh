#!/bin/sh
set -e

# Read secret files from /run/secrets/ and export as environment variables.
# Filename (lowercase) is converted to UPPER_CASE env var name.
# e.g., /run/secrets/anthropic_api_key -> ANTHROPIC_API_KEY
if [ -d /run/secrets ]; then
    for secret_file in /run/secrets/*; do
        [ -f "$secret_file" ] || continue
        var_name=$(basename "$secret_file" | tr '[:lower:]' '[:upper:]')
        # Remove trailing newlines/whitespace from secret values
        secret_value=$(cat "$secret_file" | tr -d '\n\r' | sed 's/[[:space:]]*$//')
        export "$var_name"="$secret_value"
    done
fi

# Seed gog OAuth client credentials on first start (idempotent).
# GOG_CLIENT_ID and GOG_CLIENT_SECRET come from the secrets mounted above.
# The file keyring backend is required for headless Linux containers;
# GOG_KEYRING_PASSWORD (also from secrets) unlocks it non-interactively.
# Errors are non-fatal: a bad credential value won't crash the container.
# If gog setup fails, we remove credentials.json so openclaw gateway doesn't try to use invalid credentials.
if [ -n "$GOG_CLIENT_ID" ] && [ -n "$GOG_CLIENT_SECRET" ]; then
    CREDENTIALS_FILE="$HOME/.config/gogcli/credentials.json"
    
    # Validate existing credentials.json if present
    if [ -f "$CREDENTIALS_FILE" ]; then
        # Check if it's valid JSON with required fields using node (available in container)
        if ! node -e "
            try {
                const creds = require('$CREDENTIALS_FILE');
                if (!creds.installed || !creds.installed.client_id || !creds.installed.client_secret) {
                    process.exit(1);
                }
            } catch (e) {
                process.exit(1);
            }
        " 2>/dev/null; then
            echo "Invalid credentials.json detected, removing and recreating..."
            rm -f "$CREDENTIALS_FILE"
        fi
    fi
    
    # Create credentials.json if it doesn't exist or was removed
    if [ ! -f "$CREDENTIALS_FILE" ]; then
        # Ensure directory exists
        mkdir -p "$HOME/.config/gogcli"
        
        # gog requires the Google "installed" OAuth client JSON wrapper format
        gog auth keyring file || true
        
        # Create credentials JSON and set it, verifying it was accepted
        CREDENTIALS_JSON=$(printf '{"installed":{"client_id":"%s","client_secret":"%s","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}}' \
            "$GOG_CLIENT_ID" "$GOG_CLIENT_SECRET")
        
        # Try to set credentials and capture output
        SET_OUTPUT=$(echo "$CREDENTIALS_JSON" | gog auth credentials set - 2>&1)
        SET_EXIT=$?
        
        if [ $SET_EXIT -eq 0 ] && [ -f "$CREDENTIALS_FILE" ]; then
            # Verify the file is valid JSON with required fields
            # Note: gog stores credentials in flattened format (client_id/client_secret at top level)
            # even though we send it in "installed" wrapper format
            if node -e "
                try {
                    const creds = require('$CREDENTIALS_FILE');
                    // gog may store in flattened format (client_id/client_secret) or installed format
                    const clientId = creds.client_id || (creds.installed && creds.installed.client_id);
                    const clientSecret = creds.client_secret || (creds.installed && creds.installed.client_secret);
                    
                    if (!clientId || !clientSecret) {
                        console.error('Missing required fields: client_id or client_secret');
                        process.exit(1);
                    }
                    // Verify values match what we set (trimmed)
                    const expectedId = '$GOG_CLIENT_ID'.trim();
                    const expectedSecret = '$GOG_CLIENT_SECRET'.trim();
                    if (clientId !== expectedId || clientSecret !== expectedSecret) {
                        console.error('Values mismatch');
                        console.error('Expected ID length:', expectedId.length, 'Got:', clientId.length);
                        console.error('Expected Secret length:', expectedSecret.length, 'Got:', clientSecret.length);
                        process.exit(1);
                    }
                } catch (e) {
                    console.error('Invalid JSON:', e.message);
                    process.exit(1);
                }
            " 2>&1; then
                # Verify gog accepts it by checking status
                if gog auth status >/dev/null 2>&1; then
                    echo "gog credentials set successfully"
                else
                    echo "Warning: credentials.json created but gog rejects it, removing..."
                    echo "  Debug: gog auth status output:"
                    gog auth status 2>&1 | sed 's/^/    /' || true
                    rm -f "$CREDENTIALS_FILE"
                fi
            else
                echo "Warning: credentials.json created but appears invalid, removing..."
                echo "  Debug: Node validation output:"
                node -e "
                    try {
                        const creds = require('$CREDENTIALS_FILE');
                        const clientId = creds.client_id || (creds.installed && creds.installed.client_id);
                        const clientSecret = creds.client_secret || (creds.installed && creds.installed.client_secret);
                        
                        if (!clientId || !clientSecret) {
                            console.error('Missing required fields');
                            console.error('Has client_id:', !!creds.client_id);
                            console.error('Has installed.client_id:', !!(creds.installed && creds.installed.client_id));
                            process.exit(1);
                        }
                        const expectedId = '$GOG_CLIENT_ID'.trim();
                        const expectedSecret = '$GOG_CLIENT_SECRET'.trim();
                        if (clientId !== expectedId || clientSecret !== expectedSecret) {
                            console.error('Values mismatch');
                            console.error('Expected client_id length:', expectedId.length);
                            console.error('Got client_id length:', clientId.length);
                            console.error('Expected secret length:', expectedSecret.length);
                            console.error('Got secret length:', clientSecret.length);
                            process.exit(1);
                        }
                    } catch (e) {
                        console.error('Invalid JSON:', e.message);
                        process.exit(1);
                    }
                " 2>&1 | sed 's/^/    /' || true
                rm -f "$CREDENTIALS_FILE"
            fi
        else
            echo "Warning: Failed to set gog credentials"
            echo "  Output: $SET_OUTPUT"
            # Remove file if it was created but invalid
            rm -f "$CREDENTIALS_FILE"
        fi
    fi
else
    # No gog credentials provided - remove any existing invalid file
    CREDENTIALS_FILE="$HOME/.config/gogcli/credentials.json"
    if [ -f "$CREDENTIALS_FILE" ]; then
        # Validate it if it exists
        if ! node -e "
            try {
                const creds = require('$CREDENTIALS_FILE');
                if (!creds.installed || !creds.installed.client_id || !creds.installed.client_secret) {
                    process.exit(1);
                }
            } catch (e) {
                process.exit(1);
            }
        " 2>/dev/null; then
            echo "Warning: Invalid credentials.json found but no GOG_CLIENT_ID/SECRET provided, removing..."
            rm -f "$CREDENTIALS_FILE"
        fi
    fi
fi

# GitHub CLI authentication and git credential helper.
# GH_TOKEN comes from /run/secrets/gh_token (exported above).
# `gh auth setup-git` configures git to use gh as a credential helper,
# so HTTPS clone/push works without tokens in URLs or .git/config.
if [ -n "$GH_TOKEN" ]; then
    gh auth setup-git 2>/dev/null || true
fi

# Git identity from env vars set by docker_manager
if [ -n "$GIT_USER_NAME" ]; then
    git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "$GIT_USER_EMAIL" ]; then
    git config --global user.email "$GIT_USER_EMAIL"
fi

# Auto-clone repositories listed in .git-repos.json (written by docker_manager).
# Only clones repos that don't already exist; existing repos are left untouched.
REPOS_MANIFEST="$HOME/.openclaw/.git-repos.json"
if [ -f "$REPOS_MANIFEST" ] && [ -n "$GH_TOKEN" ]; then
    WORKSPACE="$HOME/.openclaw/workspace"
    mkdir -p "$WORKSPACE"
    node -e "
        const fs = require('fs');
        const { execSync } = require('child_process');
        const repos = JSON.parse(fs.readFileSync('$REPOS_MANIFEST', 'utf8'));
        for (const repo of repos) {
            const dest = '$WORKSPACE/' + repo.path;
            if (fs.existsSync(dest + '/.git')) {
                console.log('git: ' + repo.path + ' already cloned, skipping');
                continue;
            }
            console.log('git: cloning ' + repo.url + ' -> ' + repo.path);
            try {
                execSync(
                    'git clone --branch ' + repo.branch + ' -- ' + repo.url + ' ' + dest,
                    { stdio: 'inherit' }
                );
            } catch (e) {
                console.error('git: clone failed for ' + repo.path + ': ' + e.message);
            }
        }
    " 2>&1 || true
fi

exec openclaw gateway
