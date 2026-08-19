#!/usr/bin/env bash
# Download KataGo binary + a network model and place them under backend/katago/.
# KataGo is MIT-licensed; models vary by license — check before redistribution.
# Usage: scripts/download_katago.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
KG_DIR="$ROOT/backend/katago"
mkdir -p "$KG_DIR"

# Detect platform
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  OS=linux;   ARCH=x64    ;;
  Linux-aarch64) OS=linux;   ARCH=arm64  ;;
  Darwin-x86_64) OS=macos;   ARCH=x64    ;;
  Darwin-arm64)  OS=macos;   ARCH=arm64  ;;
  MINGW*-x86_64|MSYS*-x86_64) OS=windows; ARCH=x64 ;;
  *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac
echo ">> Platform: $OS/$ARCH"

# Ask the user to confirm the KataGo release to fetch. The latest release
# URL changes over time; we default to the GitHub latest redirect.
KG_VERSION="${KATAGO_VERSION:-1.15.3}"
echo ">> KataGo version: $KG_VERSION"
echo ">> NOTE: This script downloads binaries from GitHub. If the URL is"
echo "   stale, manually download from https://github.com/lightvector/KataGo/releases"
echo "   and extract katago binary + analysis_example.cfg into $KG_DIR"
echo

read -r -p "Continue download? [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
  echo "Aborted. Place katago binary, model, and .cfg under $KG_DIR manually."
  exit 0
fi

# This URL pattern matches KataGo's GitHub releases; adjust if it changes.
URL="https://github.com/lightvector/KataGo/releases/download/v${KG_VERSION}/katago-v${KG_VERSION}-${OS}-${ARCH}.zip"
TMP="$KG_DIR/katago.zip"
echo ">> Downloading $URL"
if command -v curl >/dev/null; then
  curl -L --fail -o "$TMP" "$URL"
else
  wget -O "$TMP" "$URL"
fi

if command -v unzip >/dev/null; then
  unzip -o "$TMP" -d "$KG_DIR"
  rm -f "$TMP"
else
  echo "unzip not found; please extract $TMP manually into $KG_DIR"
fi

# Model: KataGo distributes small test models; for production use a real
# network (b18c384, b40c256, etc.) from https://katagotraining.org/networks/
echo
echo ">> KataGo binary placed in $KG_DIR."
echo ">> Next: download a network .bin.gz from https://katagotraining.org/networks/"
echo "   and save as $KG_DIR/model.bin.gz"
echo ">> Then create $KG_DIR/analysis.cfg (see KataGo docs)."
echo ">> Set env vars before starting the backend:"
echo "   export KATAGO_BINARY=$KG_DIR/katago"
echo "   export KATAGO_MODEL=$KG_DIR/model.bin.gz"
echo "   export KATAGO_CONFIG=$KG_DIR/analysis.cfg"
echo "   export GO_AI_ENGINE=auto   # will auto-pick KataGo now"
