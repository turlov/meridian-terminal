# RPM for the headless Fedora build. Built by packaging/linux/build.sh:
#   rpmbuild -bb --define "_topdir $TOP" --define "mversion 1.0.0" meridian.spec
%global debug_package %{nil}
%global __os_install_post %{nil}
%global __brp_strip %{nil}
%global _build_id_links none

Name:           meridian-terminal
Version:        %{mversion}
Release:        1%{?dist}
Summary:        Meridian Terminal: headless AI-assisted trading engine for Freedom Broker
License:        LicenseRef-Proprietary
URL:            https://github.com/
ExclusiveArch:  x86_64 aarch64
AutoReqProv:    no
Requires(pre):  shadow-utils
Requires:       systemd
Requires:       util-linux

%description
Meridian Terminal watches a stock watchlist, scores news with Claude, proposes trades from
simple rules, has Claude review each idea and lets a deterministic risk gate decide.
Orders go to Freedom Broker (Tradernet). This package runs it as a systemd service and
serves the dashboard on 127.0.0.1:8765 (reach it through an SSH tunnel).

%install
mkdir -p %{buildroot}/opt/meridian %{buildroot}%{_bindir} %{buildroot}%{_unitdir} \
         %{buildroot}/var/lib/meridian
cp -a %{_sourcedir}/meridian/. %{buildroot}/opt/meridian/
install -m 0755 %{_sourcedir}/meridian-wrapper.sh %{buildroot}%{_bindir}/meridian
install -m 0644 %{_sourcedir}/meridian.service %{buildroot}%{_unitdir}/meridian.service

%pre
getent group meridian >/dev/null || groupadd -r meridian
getent passwd meridian >/dev/null || \
  useradd -r -g meridian -d /var/lib/meridian -s /sbin/nologin -c "Meridian Terminal" meridian
exit 0

%post
# Let systemd execute the binary under SELinux (files in /opt default to usr_t).
if command -v semanage >/dev/null 2>&1; then
  semanage fcontext -a -t bin_t '/opt/meridian/meridian' 2>/dev/null || \
    semanage fcontext -m -t bin_t '/opt/meridian/meridian' 2>/dev/null || :
  restorecon -F /opt/meridian/meridian 2>/dev/null || :
elif command -v chcon >/dev/null 2>&1; then
  chcon -t bin_t /opt/meridian/meridian 2>/dev/null || :
fi
systemctl daemon-reload >/dev/null 2>&1 || :
if [ $1 -eq 1 ]; then
  echo
  echo "Meridian Terminal installed. Next:"
  echo "  sudo meridian setup                     # API keys, watchlist, risk limits"
  echo "  sudo systemctl enable --now meridian    # start now and on every boot"
  echo "  sudo meridian url                       # dashboard link (use an SSH tunnel)"
fi

%preun
if [ $1 -eq 0 ]; then
  systemctl --no-reload disable --now meridian.service >/dev/null 2>&1 || :
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || :
if [ $1 -ge 1 ]; then
  systemctl try-restart meridian.service >/dev/null 2>&1 || :
fi
if [ $1 -eq 0 ] && command -v semanage >/dev/null 2>&1; then
  semanage fcontext -d '/opt/meridian/meridian' 2>/dev/null || :
fi

%files
/opt/meridian
%{_bindir}/meridian
%{_unitdir}/meridian.service
%dir %attr(0750, meridian, meridian) /var/lib/meridian
