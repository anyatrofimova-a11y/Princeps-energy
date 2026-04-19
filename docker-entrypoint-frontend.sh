#!/bin/sh
# Substitute BACKEND_URL placeholder in nginx config at container startup.
# BACKEND_URL should be a full URL like https://princeps-web-production.up.railway.app
set -e

BACKEND_URL="${BACKEND_URL:-https://princeps-web-production.up.railway.app}"
# Strip trailing slash if present
BACKEND_URL="${BACKEND_URL%/}"

TEMPLATE=/etc/nginx/templates/default.conf.template
TARGET=/etc/nginx/conf.d/default.conf

# Escape forward slashes for sed
ESCAPED=$(echo "$BACKEND_URL" | sed 's/\//\\\//g')

if [ -f "$TEMPLATE" ]; then
    sed "s/BACKEND_URL_PLACEHOLDER/${ESCAPED}/g" "$TEMPLATE" > "$TARGET"
elif [ -f "$TARGET" ]; then
    sed -i "s/BACKEND_URL_PLACEHOLDER/${ESCAPED}/g" "$TARGET" 2>/dev/null || true
fi
