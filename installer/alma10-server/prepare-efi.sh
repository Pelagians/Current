#!/usr/bin/env bash
set -euo pipefail

# osbuild's grub2.iso stage reads these files from /boot/efi. Alma bootc
# relocates the base image's signed EFI binaries into bootupd's update tree.
# The optional root allows qualification against an isolated filesystem.
root="${1:-/}"
root="${root%/}"
# Defaults preserve the existing Alma x64 installer contract.
vendor="${2:-almalinux}"
architecture="${3:-x86_64}"
case "$vendor:$architecture" in
  almalinux:x86_64|fedora:x86_64) suffix=x64 ;;
  fedora:aarch64) suffix=aa64 ;;
  *) echo "Unsupported installer EFI platform: $vendor:$architecture" >&2; exit 1 ;;
esac
destination="$root/boot/efi/EFI/$vendor"
updates="$root/usr/lib/bootupd/updates/EFI/$vendor"
files=("shim$suffix.efi" "mm$suffix.efi" "gcd$suffix.efi")
sources=()

# Validate the whole input set before writing anything. gcdx64.efi must come
# from grub2-efi-x64-cdboot; the installed-system grubx64.efi is not a substitute.
for file in "${files[@]}"; do
  if [[ -s "$destination/$file" ]]; then
    sources+=("$destination/$file")
  elif [[ -s "$updates/$file" ]]; then
    sources+=("$updates/$file")
  else
    source_found=
    for source in "$root"/usr/lib/efi/*/*/EFI/"$vendor/$file"; do
      if [[ -s "$source" ]]; then source_found="$source"; break; fi
    done
    if [[ -n "$source_found" ]]; then
      sources+=("$source_found")
      continue
    fi
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
printf 'Installer EFI preparation: %s %s shim, MokManager, CD-boot GRUB and font ready\n' "$vendor" "$architecture"
