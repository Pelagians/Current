#!/usr/bin/env bash
set -euo pipefail
# Older rootless containers retain these host-side mount source paths.
for helper in distrobox-export distrobox-host-exec distrobox-init; do
  if [[ -x "/usr/bin/${helper}" && ! -e "/usr/sbin/${helper}" ]]; then
    ln -s "../bin/${helper}" "/usr/sbin/${helper}"
  fi
  test -x "/usr/sbin/${helper}"
done
