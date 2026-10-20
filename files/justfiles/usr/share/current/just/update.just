# Update System Flatpaks and OS Image independently.
update-system:
  /usr/libexec/current-update-system

# Clean Unused System Flatpaks
flatpak-clean-system:
  sudo /usr/libexec/current-flatpak-system-maintenance cleanup

# Backward-compatible alias for older muscle memory.
clean-system:
  current flatpak-clean-system

# Repair System Flatpaks
flatpak-repair-system:
  sudo /usr/libexec/current-flatpak-system-maintenance repair

# Show System Flatpak State
flatpak-status:
  /usr/libexec/current-flatpak-system-maintenance status

# Show Current User Portal Service State
flatpak-portal-status:
    #!/usr/bin/env bash
    set -euo pipefail

    systemctl --user --no-pager status \
      xdg-desktop-portal.service \
      xdg-document-portal.service \
      xdg-permission-store.service || true
    systemctl --user --no-pager status \
      xdg-desktop-portal-gnome.service \
      xdg-desktop-portal-cosmic.service \
      xdg-desktop-portal-gtk.service 2>/dev/null || true

# Update User Flatpaks, Homebrew, and Distrobox Containers
update-user:
  /usr/libexec/current-update-user

# Update Podman Containers
update-podman:
  /usr/libexec/current-update-podman

# Update Firmware
update-firmware:
  sudo fwupdmgr refresh --force
  sudo fwupdmgr get-updates
  sudo fwupdmgr update

# Update independent categories, preserving failures in the final status.
update-all:
  /usr/libexec/current-update-all

# Update Chooser
update:
    #!/usr/bin/env bash
    set -euo pipefail
    sel="$(fzf --prompt='Update: ' --height=15 --border --exit-0 \
          --with-nth=2.. \
          <<< $'update-system    Update System Flatpaks and OS Image\nupdate-user      Update user Flatpaks, Homebrew, and Distrobox containers\nupdate-podman    Update Podman Containers\nupdate-firmware  Update Firmware\nupdate-all       Update Everything\n')"
    [[ -n "$sel" ]] || { echo "No selection."; exit 0; }
    target="${sel%% *}"
    echo "→ Running: just ${target}"
    exec current "${target}"
