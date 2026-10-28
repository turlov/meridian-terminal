#!/usr/bin/env bash
# Remove a tarball install. Keeps /var/lib/meridian (settings, keys, trade history)
# unless you pass --purge.
set -euo pipefail
[ "$(id -u)" = "0" ] || { echo "Run with sudo: sudo ./uninstall.sh"; exit 1; }
systemctl disable --now meridian 2>/dev/null || true
rm -f /etc/systemd/system/meridian.service /usr/local/bin/meridian
rm -rf /opt/meridian
command -v semanage >/dev/null 2>&1 && semanage fcontext -d '/opt/meridian/meridian' 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
if [ "${1:-}" = "--purge" ]; then
  rm -rf /var/lib/meridian
  userdel meridian 2>/dev/null || true
  echo "Removed Meridian Terminal and its data."
else
  echo "Removed Meridian Terminal. Your data is still in /var/lib/meridian (use --purge to delete it)."
fi
