#!/usr/bin/env bash
set -euxo pipefail
# Restore only the selected source after the akmod layer's temporary repo cleanup.
case "${CURRENT_NVIDIA_VARIANT}:$(uname -m)" in
  580:x86_64|580:aarch64) repo=fedora-nvidia-580 ;;
  open:x86_64) repo=cuda-fedora44-x86_64 ;;
  open:aarch64) repo=fedora-nvidia ;;
  *) echo 'Unsupported NVIDIA variant/architecture' >&2; exit 1 ;;
esac
if [[ "$repo" != cuda-fedora44-x86_64 ]]; then
  curl -fLsS --retry 5 -o "/etc/yum.repos.d/${repo}.repo" "https://negativo17.org/repos/${repo}.repo"
fi
dnf -y --setopt=install_weak_deps=False --enablerepo="$repo" \
  install libnvidia-cfg libnvidia-fbc nvidia-libXNVCtrl nvidia-settings
if [[ "$repo" != cuda-fedora44-x86_64 ]]; then rm -f "/etc/yum.repos.d/${repo}.repo"; fi
ldconfig
