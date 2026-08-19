#!/usr/bin/env bash
# Build iOS/Android packages via Capacitor.
# Prerequisites:
#   - frontend deps installed
#   - @capacitor/cli + @capacitor/ios + @capacitor/android installed
#   - Xcode (iOS) or Android Studio (Android) for final archive
# Usage: scripts/build_mobile.sh <api-url> [ios|android|sync]
#   api-url: REQUIRED — the cloud backend URL (e.g. https://api.example.com)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FRONTEND="$ROOT/frontend"

API_URL="${1:?usage: build_mobile.sh <api-url> [ios|android|sync]}"
ACTION="${2:-sync}"

# 1. Build frontend with the cloud API URL baked in.
"$ROOT/scripts/build_web.sh" "$API_URL"

# 2. Ensure Capacitor deps are present.
( cd "$FRONTEND" && npm install -D @capacitor/cli @capacitor/core @capacitor/ios @capacitor/android )

# 3. Add platforms if not yet added.
if [[ ! -d "$FRONTEND/ios" ]]; then
  ( cd "$FRONTEND" && npx cap add ios || true )
fi
if [[ ! -d "$FRONTEND/android" ]]; then
  ( cd "$FRONTEND" && npx cap add android || true )
fi

# 4. Sync web build into native projects.
( cd "$FRONTEND" && npx cap sync )

case "$ACTION" in
  ios)
    echo ">> Open $FRONTEND/ios/App.xcworkspace in Xcode to archive & sign."
    ( cd "$FRONTEND" && npx cap open ios )
    ;;
  android)
    echo ">> Open $FRONTEND/android in Android Studio to build APK/AAB."
    ( cd "$FRONTEND" && npx cap open android )
    ;;
  sync)
    echo ">> Capacitor sync complete. Use 'ios' or 'android' to open IDEs."
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    exit 1
    ;;
esac
