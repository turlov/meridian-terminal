#!/usr/bin/env bash
# Install the headless build from the tarball (any systemd distro; on Fedora prefer the RPM).
#   sudo ./install.sh
set -euo pipefail
[ "$(id -u)" = "0" ] || { echo "Run with sudo: sudo ./install.sh"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"

getent group meridian >/dev/null || groupadd -r meridian
getent passwd meridian >/dev/null || \
  useradd -r -g meridian -d /var/lib/meridian -s /sbin/nologin -c "Meridian Terminal" meridian

systemctl stop meridian 2>/dev/null || true
rm -rf /opt/meridian
mkdir -p /opt/meridian
cp -a "$HERE/meridian/." /opt/meridian/
chown -R root:root /opt/meridian
install -m 0755 "$HERE/meridian-wrapper.sh" /usr/local/bin/meridian
install -m 0644 "$HERE/meridian.service" /etc/systemd/system/meridian.service
install -d -o meridian -g meridian -m 0750 /var/lib/meridian

if command -v restorecon >/dev/null 2>&1; then           # SELinux (Fedora, RHEL)
  if command -v semanage >/dev/null 2>&1; then
    semanage fcontext -a -t bin_t '/opt/meridian/meridian' 2>/dev/null || \
      semanage fcontext -m -t bin_t '/opt/meridian/meridian' 2>/dev/null || true
  fi
  restorecon -RF /opt/meridian /var/lib/meridian /usr/local/bin/meridian /etc/systemd/system/meridian.service 2>/dev/null || true
  command -v semanage >/dev/null 2>&1 || chcon -t bin_t /opt/meridian/meridian 2>/dev/null || true
fi
systemctl daemon-reload 2>/dev/null || true

echo "Installed Meridian Terminal $(/opt/meridian/meridian version 2>/dev/null | awk '{print $NF}')."
echo "Next:"
echo "  sudo meridian setup                     # API keys, watchlist, risk limits"
echo "  sudo systemctl enable --now meridian    # start now and on every boot"
echo "  sudo meridian url                       # dashboard link (use an SSH tunnel)"
