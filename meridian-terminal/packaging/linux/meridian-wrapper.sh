#!/bin/sh
# `meridian` command for the system install. Runs as the service user so every file in
# /var/lib/meridian stays owned by it. Examples:
#   sudo meridian setup      sudo meridian status      sudo meridian url
#   sudo meridian halt       sudo meridian resume      sudo meridian backtest NVDA.US
export MERIDIAN_HOME="${MERIDIAN_HOME:-/var/lib/meridian}"
BIN=/opt/meridian/meridian

if [ "$(id -u)" = "0" ] && id meridian >/dev/null 2>&1; then
  exec runuser -u meridian -- env MERIDIAN_HOME="$MERIDIAN_HOME" "$BIN" "$@"
fi
if [ "$(id -un)" != "meridian" ] && [ ! -w "$MERIDIAN_HOME" ]; then
  echo "Meridian's data lives in $MERIDIAN_HOME. Run with sudo, e.g.: sudo meridian ${*:-status}" >&2
  exit 1
fi
exec "$BIN" "$@"
