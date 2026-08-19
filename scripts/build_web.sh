#!/usr/bin/env bash
# Build the web frontend (production static bundle).
# Usage: scripts/build_web.sh [vite-api-url]
#   If VITE_API_URL is set (e.g. https://api.example.com), the bundle will
#   call that backend; otherwise it assumes same-origin (dev proxy / static host).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FRONTEND="$ROOT/frontend"

API_URL="${1:-${VITE_API_URL:-}}"
if [[ -n "$API_URL" ]]; then
  echo ">> Building frontend with VITE_API_URL=$API_URL"
  ( cd "$FRONTEND" && VITE_API_URL="$API_URL" npm run build )
else
  echo ">> Building frontend (same-origin backend)"
  ( cd "$FRONTEND" && npm run build )
fi

echo ">> Web bundle: $FRONTEND/dist"
