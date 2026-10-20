#!/usr/bin/env bash
set -euo pipefail

# osbuild's grub2.iso stage reads these files from /boot/efi. Alma bootc
# relocates the base image's signed EFI binaries into bootupd's update tree.
# The optional root allows qualification against an isolated filesystem.
root="${1:-/}"
root="${root%/}"
destination="$root/boot/efi/EFI/almalinux"
updates="$root/usr/lib/bootupd/updates/EFI/almalinux"
files=(shimx64.efi mmx64.efi gcdx64.efi)
sources=()

# Validate the whole input set before writing anything. gcdx64.efi must come
# from grub2-efi-x64-cdboot; the installed-system grubx64.efi is not a substitute.
for file in "${files[@]}"; do
  if [[ -s "$destination/$file" ]]; then
    sources+=("$destination/$file")
  elif [[ -s "$updates/$file" ]]; then
    sources+=("$updates/$file")
  else
    printf 'Installer EFI preparation: missing %s in %s and %s\n' \
      "$file" "$destination" "$updates" >&2
    exit 1
  fi
done
if [[ ! -s "$root/usr/share/grub/unicode.pf2" ]]; then
  printf 'Installer EFI preparation: missing /usr/share/grub/unicode.pf2\n' >&2
  exit 1
fi

mkdir -p "$destination"
for i in "${!files[@]}"; do
  if [[ "${sources[$i]}" != "$destination/${files[$i]}" ]]; then
    cp --preserve=mode,timestamps -- "${sources[$i]}" "$destination/${files[$i]}"
  fi
done
printf 'Installer EFI preparation: Alma x64 shim, MokManager, CD-boot GRUB and font ready\n'
