#!/bin/sh
set -e

# Read secret files from /run/secrets/ and export as environment variables.
# Filename (lowercase) is converted to UPPER_CASE env var name.
# e.g., /run/secrets/anthropic_api_key -> ANTHROPIC_API_KEY
if [ -d /run/secrets ]; then
    for secret_file in /run/secrets/*; do
        [ -f "$secret_file" ] || continue
        var_name=$(basename "$secret_file" | tr '[:lower:]' '[:upper:]')
        export "$var_name"="$(cat "$secret_file")"
    done
fi

exec openclaw gateway
