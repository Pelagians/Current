#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

command -v python3 >/dev/null 2>&1 || { printf 'Missing required tool: python3
' >&2; exit 127; }

bash -n files/scripts/just-el9.sh
bash -n files/workstation/shared/usr/libexec/current-workstation-dm-apply
bash -n files/flatpak/base/usr/libexec/current-flatpak-session-env
bash -n files/flatpak/cleanup/usr/libexec/current-flatpak-system-maintenance
bash -n files/nvidia/usr/local/libexec/current/current-pcp-nvidia-pmda-apply
bash -n modules/os-release-meta/os-release-meta.sh
bash -n files/justfiles/usr/local/bin/current
bash -n scripts/build-alma10-installer-iso.sh

# Current display branding.
test -f files/base/branding/usr/share/fastfetch/logos/current
test -f files/base/branding/usr/share/fastfetch/presets/current.jsonc
test ! -e files/base/branding/usr/share/fastfetch/logos/myos
test ! -e files/base/branding/usr/share/fastfetch/presets/myos.jsonc
grep -q 'fastfetch -c current' files/base/branding/etc/profile.d/current-fastfetch.sh
grep -q '"source": "current"' files/base/branding/usr/share/fastfetch/presets/current.jsonc
grep -q 'export ORIGINAL_PRETTY=' modules/os-release-meta/os-release-meta.sh || grep -q 'ORIGINAL_PRETTY' recipes/layers/shared/core-base.yml
grep -q 'NAME=\\"Current ' recipes/layers/shared/core-base.yml
grep -q 'VENDOR_NAME=\\"Pelagian Current\\"' recipes/layers/shared/core-base.yml
grep -q 'UPSTREAM_OS=' recipes/layers/shared/core-base.yml


# Current command and runtime namespace.
test -f files/justfiles/usr/local/bin/current
test ! -e files/justfiles/usr/local/bin/myos
test -d files/justfiles/usr/share/current/just
test ! -e files/justfiles/usr/share/myos
test -f files/base/runtime/usr/share/current/image-matrix.tsv
test ! -e files/base/runtime/usr/share/myos
grep -q 'JUSTFILE="/usr/share/current/just/index.just"' files/justfiles/usr/local/bin/current
grep -q 'default_matrix_url="https://raw.githubusercontent.com/Pelagians/Current/stable/files/base/runtime/usr/share/current/image-matrix.tsv"' files/justfiles/usr/share/current/just/rebase.just
grep -q 'CURRENT_IMAGE_MATRIX_URL' files/justfiles/usr/share/current/just/rebase.just
! grep -q 'MYOS_IMAGE_MATRIX_URL' files/justfiles/usr/share/current/just/rebase.just
grep -q 'CURRENT_REGISTRY_NAMESPACE' files/justfiles/usr/share/current/just/rebase.just
! grep -q 'MYOS_REGISTRY_NAMESPACE' files/justfiles/usr/share/current/just/rebase.just
grep -q 'ghcr.io/pelagians' files/justfiles/usr/share/current/just/rebase.just
grep -q 'current --list' files/justfiles/usr/share/current/just/index.just
grep -q 'CURRENT_INSTALLER_PAYLOAD_REF' scripts/build-alma10-installer-iso.sh
! grep -q 'MYOS_INSTALLER_PAYLOAD_REF' scripts/build-alma10-installer-iso.sh
test ! -e scripts/sync-ghcr-compat-aliases.sh

# No Current runtime implementation should keep old myOS env/config/path names.
! grep -RInE \
  --exclude-dir=.git \
  --exclude='*.svg' \
  --exclude='validate-runtime-artifacts.sh' \
  -- 'myos|myOS|myos-dev|MYOS_' \
  files scripts modules recipes .github installer README.md docs/README.md docs/user docs/brand docs/maintainers SUPPORT.md CONTRIBUTING.md

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

run_os_release_meta_smoke() {
  local name="$1"
  local os_release_body="$2"
  local expected_distro="$3"
  local expected_major="$4"
  local expected_minor="$5"
  local expected_el_family="$6"
  local expected_el_major="$7"
  local expected_el_minor="$8"
  local root="${tmpdir}/${name}"

  mkdir -p "${root}/etc/dnf/vars" "${root}/usr/share/current"
  printf '%s
' "${os_release_body}" > "${root}/os-release"

  OS_RELEASE_META_OS_RELEASE_PATH="${root}/os-release"   OS_RELEASE_META_ENV_PATH="${root}/usr/share/current/os-release-meta.env"   OS_RELEASE_META_DNF_VARS_DIR="${root}/etc/dnf/vars"     bash modules/os-release-meta/os-release-meta.sh

  (
    set -euo pipefail
    # shellcheck disable=SC1090
    . "${root}/usr/share/current/os-release-meta.env"
    [ "${DISTRO_ID}" = "${expected_distro}" ]
    [ "${DISTRO_MAJOR}" = "${expected_major}" ]
    [ "${DISTRO_MINOR}" = "${expected_minor}" ]
    [ "${EL_FAMILY}" = "${expected_el_family}" ]
    [ "${EL_MAJOR}" = "${expected_el_major}" ]
    [ "${EL_MINOR}" = "${expected_el_minor}" ]
  )

  if [[ "${expected_el_family}" == true ]]; then
    [ "$(cat "${root}/etc/dnf/vars/releasever_major")" = "${expected_major}" ]
    [ "$(cat "${root}/etc/dnf/vars/releasever_minor")" = "${expected_minor}" ]
  else
    [ ! -e "${root}/etc/dnf/vars/releasever_major" ]
    [ ! -e "${root}/etc/dnf/vars/releasever_minor" ]
  fi
}

run_os_release_meta_smoke alma10 $'ID="almalinux"
ID_LIKE="rhel centos fedora"
VERSION_ID="10.1"
PLATFORM_ID="platform:el10"' almalinux 10 1 true 10 1
run_os_release_meta_smoke fedora $'ID="fedora"
VERSION_ID="44"
NAME="Fedora Linux"' fedora 44 0 false '' ''

test -f files/flatpak/base/etc/profile.d/flatpak-user-default.sh
test -f files/flatpak/base/usr/lib/environment.d/60-current-flatpak-exports.conf
test ! -e files/flatpak/base/usr/lib/environment.d/60-myos-flatpak-exports.conf
test -f files/gnome/shared/etc/dconf/db/gdm.d/02-current-global
test ! -e files/gnome/shared/etc/dconf/db/gdm.d/02-myos-global
test -f files/flatpak/base/etc/systemd/system/system-flatpak-setup.service.d/10-managed-org-system.conf
grep -q "current-flatpak-system-maintenance setup" files/flatpak/base/etc/systemd/system/system-flatpak-setup.service.d/10-managed-org-system.conf
test -f files/flatpak/base/usr/libexec/current-flatpak-session-env
test -f files/flatpak/cleanup/usr/libexec/current-flatpak-system-maintenance
test -f files/workstation/shared/usr/libexec/current-workstation-dm-apply
grep -q 'desktop_env_file="/usr/share/current/workstation/desktop.env"' files/workstation/shared/usr/libexec/current-workstation-dm-apply
grep -q 'CURRENT_DESKTOP' files/workstation/shared/usr/libexec/current-workstation-dm-apply

grep -q 'from-file: layers/shared/workstation-substrate.yml' recipes/layers/shared/workstation-common.yml
grep -q 'from-file: layers/shared/workstation-media.yml' recipes/layers/shared/workstation-common.yml
grep -q 'from-file: layers/shared/workstation-admin-tools.yml' recipes/layers/shared/workstation-common.yml
grep -q 'from-file: layers/shared/workstation-policy.yml' recipes/layers/shared/workstation-common.yml
grep -q 'from-file: layers/shared/workstation-user-tools.yml' recipes/layers/shared/workstation-common.yml
! grep -q 'brave-browser-rpm-beta' recipes/layers/shared/workstation-common.yml
! grep -q 'current-workstation-dm-apply.service' recipes/layers/shared/workstation-common.yml
grep -q '^        - ModemManager$' recipes/layers/shared/workstation-substrate.yml
grep -q '^        - libva$' recipes/layers/shared/workstation-media.yml
grep -q '^        - libvdpau$' recipes/layers/shared/workstation-media.yml
grep -q '^        - mesa-dri-drivers$' recipes/layers/shared/workstation-media.yml
grep -q '^        - libva-utils$' recipes/layers/alma9/workstation.yml
grep -q 'libva-nvidia-driver' recipes/layers/alma9/nvidia-workstation.yml
! grep -q 'libva-nvidia-driver' recipes/layers/alma9/nvidia-580.yml
grep -q '^        - tcpdump$' recipes/layers/shared/workstation-admin-tools.yml
grep -q 'current-workstation-dm-apply.service' recipes/layers/shared/workstation-policy.yml
grep -q 'brave-origin-beta' recipes/layers/shared/workstation-user-tools.yml
test -f files/workstation/user-tools/usr/lib/tmpfiles.d/current-brave-origin-opt.conf
grep -Eq '^L\+ /var/opt/brave\.com .*/usr/lib/opt/brave\.com$' files/workstation/user-tools/usr/lib/tmpfiles.d/current-brave-origin-opt.conf

test -f files/base/runtime/etc/ld.so.conf.d/rocm.conf
test -f files/base/runtime/etc/profile.d/rocm.sh
test -f files/base/runtime/etc/udev/rules.d/70-render.rules
test -f files/base/runtime/etc/udev/rules.d/70-amdgpu-kfd.rules
! grep -q 'agent/runtime-core' recipes/layers/shared/core-base.yml
! grep -q 'agent/platform-host' recipes/layers/shared/core.yml
! grep -q '/etc/current/dns' recipes/layers/shared/core.yml
! grep -q '/etc/current/firewall' recipes/layers/shared/core.yml
! grep -q '/etc/current' recipes/layers/shared/core.yml

grep -q 'from-file: layers/features/k3s.yml' recipes/layers/shared/core-base.yml
grep -q 'from-file: layers/features/pcp.yml' recipes/layers/shared/core-base.yml
grep -q 'from-file: layers/features/tailscale.yml' recipes/layers/shared/core-base.yml
grep -q 'from-file: layers/shared/system-policy.yml' recipes/layers/shared/core-base.yml
! grep -q 'tailscale.repo' recipes/layers/shared/core-base.yml
! grep -q 'pmcd.service' recipes/layers/shared/core-base.yml
! grep -q 'bootc-fetch-apply-updates' recipes/layers/shared/core-base.yml
grep -q '^        - pcp$' recipes/layers/features/pcp.yml
grep -q 'pmcd.service' recipes/layers/features/pcp.yml
grep -q 'tailscale.repo' recipes/layers/features/tailscale.yml
grep -q 'tailscaled.service' recipes/layers/features/tailscale.yml
grep -q 'bootc-fetch-apply-updates.service' recipes/layers/shared/system-policy.yml
grep -q 'transparent_hugepage=madvise' recipes/layers/shared/system-policy.yml

test -f files/k3s/shared/usr/lib/systemd/system/k3s.service
test -f files/k3s/shared/usr/lib/systemd/system/k3s-agent.service
grep -q "version='v1.36.1+k3s1'" recipes/layers/features/k3s.yml
! grep -q 'current cluster' recipes/layers/features/k3s.yml

test -f files/ceph-host/shared/usr/lib/modules-load.d/90-current-ceph-host.conf
grep -q 'from-file: layers/features/ceph.yml' recipes/layers/shared/core.yml

grep -q '^        - pcp-pmda-nvidia-gpu$' recipes/layers/shared/nvidia-base.yml
grep -q 'nvidia-container-toolkit.repo' recipes/layers/shared/nvidia-base.yml
grep -q 'repo_gpgcheck=0' recipes/layers/shared/nvidia-base.yml
grep -q 'gpgcheck=1' recipes/layers/shared/nvidia-base.yml
grep -q 'fedora-nvidia-580.repo' recipes/layers/fedora/nvidia-580.yml
grep -q 'https://negativo17.org/repos/fedora-nvidia-580.repo' recipes/layers/fedora/nvidia-580.yml
grep -q 'kernel-devel-matched' recipes/layers/fedora/nvidia-580.yml
grep -q 'akmods --force --kernels' recipes/layers/fedora/nvidia-580.yml
grep -q 'modinfo' recipes/layers/fedora/nvidia-580.yml
grep -q 'dnf -y remove akmod-nvidia akmods kernel-devel kernel-headers' recipes/layers/fedora/nvidia-580.yml
grep -q 'nvidia-driver nvidia-persistenced nvidia-driver-cuda' recipes/layers/fedora/nvidia-580.yml
! grep -q 'libva-nvidia-driver' recipes/layers/fedora/nvidia-580.yml
grep -q 'fedora-nvidia-580.repo' recipes/layers/fedora/nvidia-580-workstation.yml
grep -q 'https://negativo17.org/repos/fedora-nvidia-580.repo' recipes/layers/fedora/nvidia-580-workstation.yml
grep -q 'install libnvidia-cfg libnvidia-fbc nvidia-libXNVCtrl nvidia-settings' recipes/layers/fedora/nvidia-580-workstation.yml
grep -q 'rm -f /etc/yum.repos.d/fedora-nvidia-580.repo' recipes/layers/fedora/nvidia-580-workstation.yml
test -f files/nvidia/usr/local/libexec/current/current-pcp-nvidia-pmda-apply
test -f files/nvidia/usr/lib/systemd/system/current-pcp-nvidia-pmda-apply.service

grep -q "import '/usr/share/current/just/default.just'" files/justfiles/usr/share/current/just/index.just
grep -q "import '/usr/share/current/just/rebase.just'" files/justfiles/usr/share/current/just/index.just
grep -q "import '/usr/share/current/just/update.just'" files/justfiles/usr/share/current/just/index.just
! grep -q "cluster.just" files/justfiles/usr/share/current/just/index.just
test ! -e files/justfiles/usr/share/current/just/cluster.just
grep -q '^rebase:$' files/justfiles/usr/share/current/just/rebase.just

# Flatpak transaction, wrapper, policy, and orchestration behavior.
bash -n files/flatpak/base/etc/profile.d/flatpak-user-default.sh
python3 scripts/test-flatpak-maintenance.py
