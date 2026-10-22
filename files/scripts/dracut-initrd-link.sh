#!/usr/bin/env bash
# Build-time only. Reuse dracut's packaged shutdown restoration rather than
# replacing its unpacking, SELinux relabeling or shutdown-root implementation.
set -euo pipefail
root="${1:-/}"
shopt -s nullglob
images=("${root%/}"/usr/lib/modules/*/initramfs.img)
if (( ${#images[@]} == 0 )); then
  printf 'No generated bootc initramfs found; run this after the initramfs module.\n' >&2
  exit 1
fi
for image in "${images[@]}"; do
  [[ -f "$image" && -s "$image" ]] || { printf 'Invalid initramfs: %s\n' "$image" >&2; exit 1; }
  alias="${image%/*}/initrd"
  if [[ -e "$alias" ]]; then
    # Preserve an existing vendor-provided shutdown image or working alias.
    [[ -f "$alias" && -s "$alias" ]] || { printf 'Invalid vendor initrd: %s\n' "$alias" >&2; exit 1; }
  elif [[ -L "$alias" ]]; then
    printf 'Refusing to replace dangling vendor initrd: %s\n' "$alias" >&2
    exit 1
  else
    ln -s initramfs.img "$alias"
  fi
done
