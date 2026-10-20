#!/usr/bin/env bash
set -euo pipefail
# Runs ONLY inside the disposable installer build, never on the development host.
[[ "$CURRENT_PAYLOAD_REF" =~ ^ghcr\.io/pelagians/current-bootstrap[-a-z0-9_]*@sha256:[a-f0-9]{64}$ ]] || {
  echo 'Expected an immutable Current bootstrap reference' >&2; exit 1;
}
sed -i "s|@PAYLOAD@|$CURRENT_PAYLOAD_REF|g" /usr/share/anaconda/interactive-defaults.ks
mkdir -p /etc/anaconda/conf.d
cat > /etc/anaconda/conf.d/99-current.conf <<'CONFIG'
[Storage]
default_file_system = xfs
CONFIG
# Upstream generic ISO Anaconda runtime setup. Credentials are runtime-only.
echo 'install:x:0:0:root:/root:/usr/libexec/anaconda/run-anaconda' >> /etc/passwd
echo 'install::14438:0:99999:7:::' >> /etc/shadow
passwd -d root
mv /usr/share/anaconda/list-harddrives-stub /usr/bin/list-harddrives
mv /etc/yum.repos.d /etc/anaconda.repos.d
ln -sfn /usr/lib/systemd/system/anaconda.target /etc/systemd/system/default.target
rm -f /usr/lib/systemd/system-generators/systemd-gpt-auto-generator
ln -sfn /usr/lib/systemd/system/anaconda-shell@.service /usr/lib/systemd/system/autovt@.service
mkdir -p /usr/lib/systemd/logind.conf.d /etc/systemd/user/pipewire.service.d /etc/systemd/user/pipewire.socket.d
printf '[Login]\nReserveVT=2\n' > /usr/lib/systemd/logind.conf.d/anaconda-shell.conf
printf '[Unit]\nConditionUser=\n' | tee /etc/systemd/user/pipewire.service.d/allowroot.conf > /etc/systemd/user/pipewire.socket.d/allowroot.conf
mkdir -p "$(realpath /root)" /var/mnt
mapfile -t kernels < <(find /usr/lib/modules -mindepth 2 -maxdepth 2 -name vmlinuz)
[[ "${#kernels[@]}" = 1 ]]
kernel="$(basename "$(dirname "${kernels[0]}")")"
DRACUT_NO_XATTR=1 dracut --force --zstd --reproducible --no-hostonly --add anaconda \
  "/usr/lib/modules/$kernel/initramfs.img" "$kernel"
