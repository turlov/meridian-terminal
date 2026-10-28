#!/usr/bin/env bash
# Build the headless Linux binary, an RPM (if rpmbuild is installed) and a tarball.
#   bash packaging/linux/build.sh
# Build on the oldest distro you need to support: the binary needs that glibc or newer.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${PYTHON:-python3}"
ARCH="$(uname -m)"
if [ ! -x .venv-build/bin/python ]; then "$PY" -m venv .venv-build; fi
VPY=.venv-build/bin/python
"$VPY" -m pip install --upgrade pip >/dev/null
"$VPY" -m pip install -r requirements.txt -r requirements-build.txt
VERSION="$("$VPY" -c 'import meridian; print(meridian.__version__)')"

echo "== tests"
"$VPY" -m pytest -q tests

echo "== pyinstaller"
rm -rf build dist/meridian
"$VPY" -m PyInstaller --noconfirm --clean packaging/meridian.spec

echo "== smoke test"
bash packaging/smoke_test.sh dist/meridian/meridian

echo "== tarball"
NAME="meridian-$VERSION-linux-$ARCH"
rm -rf "dist/$NAME" "dist/$NAME.tar.gz"
mkdir -p "dist/$NAME"
cp -a dist/meridian "dist/$NAME/meridian"
cp packaging/linux/install.sh packaging/linux/uninstall.sh packaging/linux/meridian.service \
   packaging/linux/meridian-wrapper.sh "dist/$NAME/"
cp README.md "dist/$NAME/"
chmod +x "dist/$NAME/"*.sh
tar -C dist -czf "dist/$NAME.tar.gz" "$NAME"
rm -rf "dist/$NAME"

if command -v rpmbuild >/dev/null 2>&1; then
  echo "== rpm"
  TOP="$(mktemp -d)"
  mkdir -p "$TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
  cp -a dist/meridian "$TOP/SOURCES/meridian"
  cp packaging/linux/meridian.service packaging/linux/meridian-wrapper.sh "$TOP/SOURCES/"
  rpmbuild -bb --quiet --define "_topdir $TOP" --define "mversion $VERSION" \
    --define "_unitdir /usr/lib/systemd/system" packaging/linux/meridian.spec
  cp "$TOP"/RPMS/*/*.rpm dist/
  rm -rf "$TOP"
else
  echo "rpmbuild not found; skipped the RPM (sudo dnf install rpm-build)"
fi

echo
ls -1 dist/*.tar.gz dist/*.rpm 2>/dev/null
