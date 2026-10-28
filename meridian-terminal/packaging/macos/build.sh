#!/usr/bin/env bash
# Build "Meridian Terminal.app" and a drag-to-install DMG. Run on a Mac:
#   bash packaging/macos/build.sh
#
# Optional, for a signed and notarized app (Apple Developer account, $99/yr):
#   export MACOS_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#   export APPLE_ID=you@example.com APPLE_TEAM_ID=TEAMID APPLE_APP_PASSWORD=abcd-efgh-ijkl-mnop
set -euo pipefail
cd "$(dirname "$0")/../.."

APP="Meridian Terminal"
PY="${PYTHON:-python3}"
ARCH="$(uname -m)"

if [ ! -x .venv-build/bin/python ]; then "$PY" -m venv .venv-build; fi
VPY=.venv-build/bin/python
"$VPY" -m pip install --upgrade pip >/dev/null
"$VPY" -m pip install -r requirements-desktop.txt -r requirements-build.txt
VERSION="$("$VPY" -c 'import meridian; print(meridian.__version__)')"

echo "== tests"
"$VPY" -m pytest -q tests

echo "== icons"
"$VPY" packaging/icons/make_icons.py

# numpy wheels on macOS 14+ hosts need macOS 14; older hosts produce builds for themselves.
HOST_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$HOST_MAJOR" -lt 14 ]; then export MACOS_MIN_VERSION="$HOST_MAJOR.0"; else export MACOS_MIN_VERSION="14.0"; fi

echo "== pyinstaller"
rm -rf build "dist/$APP" "dist/$APP.app"
"$VPY" -m PyInstaller --noconfirm --clean packaging/meridian.spec
APP_PATH="dist/$APP.app"

echo "== codesign"
if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --timestamp \
    --entitlements packaging/macos/entitlements.plist --sign "$MACOS_SIGN_IDENTITY" "$APP_PATH"
else
  codesign --force --deep --sign - "$APP_PATH"      # ad-hoc signature (required on Apple Silicon)
fi
codesign --verify --deep --strict "$APP_PATH"

echo "== smoke test"
bash packaging/smoke_test.sh "$APP_PATH/Contents/MacOS/$APP"

echo "== dmg"
DMG="dist/MeridianTerminal-$VERSION-macOS-$ARCH.dmg"
STAGE="$(mktemp -d)"
cp -R "$APP_PATH" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "$APP" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$MACOS_SIGN_IDENTITY" "$DMG"
  if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
    echo "== notarize"
    xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$DMG"
  fi
fi

echo
echo "Built $DMG"
echo "Open it and drag Meridian Terminal to Applications."
