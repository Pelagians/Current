#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source files/workstation/shared/usr/libexec/current-workstation-dm-apply

root="$(mktemp -d)"
trap 'rm -rf "${root}"' EXIT
mkdir -p "${root}/etc/pam.d" "${root}/usr/lib/pam.d"
local_pam="${root}/etc/pam.d/cosmic-greeter"
vendor_pam="${root}/usr/lib/pam.d/cosmic-greeter"

# Simulate an installed keyring module without requiring host PAM packages.
pam_gnome_keyring_available() { return 0; }
printf 'auth include login\nsession include login\n' > "${vendor_pam}"
pam_gnome_keyring_available() { return 1; }
ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"
[[ ! -e "${local_pam}" ]]
pam_gnome_keyring_available() { return 0; }
ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"
grep -Fxq 'auth optional pam_gnome_keyring.so' "${local_pam}"
grep -Fxq 'session optional pam_gnome_keyring.so auto_start' "${local_pam}"

# A vendor update must replace our generated override, then add keyring once.
printf 'auth include login\naccount include login\nsession include login\n' > "${vendor_pam}"
ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"
grep -Fxq 'account include login' "${local_pam}"
[[ "$(grep -Fc 'auth optional pam_gnome_keyring.so' "${local_pam}")" == 1 ]]

# Leave administrator overrides, including a symlink, untouched.
printf 'auth include custom\n' > "${local_pam}"
ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"
grep -Fxq 'auth include custom' "${local_pam}"
! grep -Fq 'account include login' "${local_pam}"
rm "${local_pam}"
ln -s "${vendor_pam}" "${local_pam}"
ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"
! grep -Fq 'pam_gnome_keyring.so' "${vendor_pam}"

# Older packages still install directly in /etc.
rm "${local_pam}" "${vendor_pam}"
printf 'auth include login\nsession include login\n' > "${local_pam}"
ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"
grep -Fxq 'auth optional pam_gnome_keyring.so' "${local_pam}"

rm "${local_pam}"
if ensure_cosmic_keyring_pam "${local_pam}" "${vendor_pam}"; then
  echo 'missing PAM stack unexpectedly passed' >&2
  exit 1
fi

echo 'COSMIC PAM reconciliation checks passed'
