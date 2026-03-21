#!/bin/sh
# Substitute BACKEND_HOST placeholder in nginx config
set -e

BACKEND_HOST="${BACKEND_HOST:-princeps-api.internal}"

# Replace placeholder with actual backend host
sed -i "s/BACKEND_PLACEHOLDER/${BACKEND_HOST}/g" /etc/nginx/conf.d/default.conf 2>/dev/null || true

# If the template hasn't been processed yet, do it now
if [ -f /etc/nginx/templates/default.conf.template ]; then
    sed "s/BACKEND_PLACEHOLDER/${BACKEND_HOST}/g" \
        /etc/nginx/templates/default.conf.template \
        > /etc/nginx/conf.d/default.conf
fi
