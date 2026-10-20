#!/usr/bin/env bash
set -euo pipefail
# EL9's COPR omits icons and wallpapers required by its COSMIC packages.
# Use only the same publisher's signed, data-only noarch assets from EL10.
. /usr/share/current/os-release-meta.env
[[ "$DISTRO_ID" == almalinux && "$EL_MAJOR" == 9 ]]
arch="$(uname -m)"
case "$arch" in x86_64|aarch64) ;; *) echo "Unsupported COSMIC asset architecture: $arch" >&2; exit 1 ;; esac
repo=current-el9-cosmic-assets
base=https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic
dnf -y --setopt=install_weak_deps=False \
  --repofrompath="${repo},${base}/rhel+epel-10-${arch}/" \
  --setopt="${repo}.includepkgs=cosmic-icon-theme,cosmic-wallpapers" \
  --setopt="${repo}.gpgcheck=1" \
  --setopt="${repo}.gpgkey=${base}/pubkey.gpg" \
  --setopt="${repo}.skip_if_unavailable=False" \
  install cosmic-icon-theme.noarch cosmic-wallpapers.noarch
for package in cosmic-icon-theme cosmic-wallpapers; do
  [[ "$(rpm -q "$package" --queryformat '%{ARCH}')" == noarch ]]
  [[ -z "$(rpm -q --scripts "$package")" ]]
  rpm -ql "$package" | while IFS= read -r path; do
    case "$path" in
      /usr/share/icons/*|/usr/share/backgrounds/cosmic|/usr/share/backgrounds/cosmic/*|/usr/share/licenses/*) ;;
      *) echo "Unexpected COSMIC asset payload: $path" >&2; exit 1 ;;
    esac
  done
done
dnf -q --disablerepo='*' repoquery --installed --whatprovides 'cosmic-icon-theme >= 1.9.0' \
  --qf '%{name}.%{arch}' | grep -Fx cosmic-icon-theme.noarch
