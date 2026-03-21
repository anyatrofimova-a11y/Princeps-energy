#!/bin/bash
set -euo pipefail

# Deploy Princeps to Fly.io
# Usage: ./deploy.sh [backend|frontend|all]

COMPONENT="${1:-all}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }
err()  { echo -e "${RED}[deploy]${NC} $*" >&2; }

# Pre-flight checks
if ! command -v flyctl &>/dev/null; then
    err "flyctl not found. Install: curl -L https://fly.io/install.sh | sh"
    exit 1
fi

if ! flyctl auth whoami &>/dev/null; then
    err "Not authenticated. Run: flyctl auth login"
    exit 1
fi

deploy_backend() {
    log "Deploying Princeps API (backend)..."
    flyctl deploy --config fly.toml --wait-timeout 300
    log "Backend deployed. Checking health..."
    sleep 5
    curl -sf "https://princeps-api.fly.dev/health" | python3 -m json.tool || warn "Health check pending — app may still be starting"
    log "Backend deployment complete."
}

deploy_frontend() {
    log "Deploying Princeps App (frontend)..."

    # Check for VITE_MAPBOX_TOKEN
    if [ -z "${VITE_MAPBOX_TOKEN:-}" ]; then
        warn "VITE_MAPBOX_TOKEN not set. Map features will not work."
        warn "Set it: export VITE_MAPBOX_TOKEN=pk.xxx before deploying"
    fi

    flyctl deploy --config fly.frontend.toml \
        --build-arg "VITE_MAPBOX_TOKEN=${VITE_MAPBOX_TOKEN:-}" \
        --build-arg "VITE_API_URL=https://princeps-api.fly.dev" \
        --wait-timeout 300
    log "Frontend deployed."
    log "Live at: https://princeps-app.fly.dev"
}

case "$COMPONENT" in
    backend)
        deploy_backend
        ;;
    frontend)
        deploy_frontend
        ;;
    all)
        deploy_backend
        echo ""
        deploy_frontend
        echo ""
        log "Full deployment complete."
        log "  API:      https://princeps-api.fly.dev"
        log "  Frontend: https://princeps-app.fly.dev"
        ;;
    *)
        err "Unknown component: $COMPONENT"
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac
