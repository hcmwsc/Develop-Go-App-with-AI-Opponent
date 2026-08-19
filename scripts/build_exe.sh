#!/usr/bin/env bash
# Build the Windows EXE via Electron + electron-builder.
# Prerequisites:
#   - frontend deps installed (npm install in frontend/)
#   - desktop deps installed (npm install in desktop/)
#   - Python + uvicorn available in backend/ (bundled via extraResources)
# Usage: scripts/build_exe.sh [--win|--mac|--linux]
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FRONTEND="$ROOT/frontend"
DESKTOP="$ROOT/desktop"

TARGET="${1:---win}"

# 1. Build the web frontend (bundled inside the Electron app).
"$ROOT/scripts/build_web.sh"

# 2. Install desktop deps if missing.
if [[ ! -d "$DESKTOP/node_modules" ]]; then
  echo ">> Installing desktop dependencies"
  ( cd "$DESKTOP" && npm install )
fi

# 3. Package with electron-builder.
echo ">> Building Electron package: $TARGET"
( cd "$DESKTOP" && npm run "dist:${TARGET#--}" )

echo ">> Output: $DESKTOP/release"
