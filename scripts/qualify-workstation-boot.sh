#!/usr/bin/env bash
# Run in a booted disposable Current workstation, after graphical login.
set -euo pipefail

marker=/usr/share/current/workstation/desktop.env
case "$(cat "$marker")" in
  CURRENT_DESKTOP=gnome) selected=gdm.service; desktop=GNOME ;;
  CURRENT_DESKTOP=cosmic) selected=cosmic-greeter.service; desktop=COSMIC ;;
  *) printf 'Invalid workstation marker\n' >&2; exit 1 ;;
esac
[[ ! -e /etc/current/workstation-dm-unmanaged ]] || { echo 'Ownership is opted out' >&2; exit 1; }
[[ "$(systemctl get-default)" == graphical.target ]]
systemctl status --no-pager current-workstation-dm-apply.service display-manager.service
[[ "$(systemctl show current-workstation-dm-apply.service -p Result --value)" == success ]]
systemctl is-active --quiet current-workstation-dm-apply.service
systemctl is-active --quiet "$selected"
[[ "$(readlink -f /etc/systemd/system/display-manager.service)" == "/usr/lib/systemd/system/$selected" ]]
readlink -f /etc/systemd/system/display-manager.service
for unit in gdm.service cosmic-greeter.service greetd.service; do
  state="$(systemctl is-enabled "$unit" 2>&1)" || :
  printf '%s: %s\n' "$unit" "$state"
  if [[ "$unit" != "$selected" ]]; then
    if systemctl is-active --quiet "$unit"; then echo "Competing manager active: $unit" >&2; exit 1; fi
    case "$state" in enabled|enabled-runtime|linked|linked-runtime) echo "Competing manager enabled: $unit" >&2; exit 1 ;; esac
  fi
done
journalctl -b --no-pager -u current-workstation-dm-apply.service -u "$selected"
if [[ "${1:-}" == --system-only ]]; then
  echo 'System ownership checks passed; graphical login/session verification remains required.'
  exit 0
fi
[[ -n "${XDG_SESSION_ID:-}" ]] || { echo 'Run after graphical login, or use --system-only for ownership checks.' >&2; exit 1; }
loginctl show-session "$XDG_SESSION_ID" -p Name -p Desktop -p Type -p State
current_desktop="${XDG_CURRENT_DESKTOP:-}"
case ";${current_desktop^^};" in
  *";$desktop;"*) ;;
  *) echo "Wrong logged-in desktop: ${XDG_CURRENT_DESKTOP:-unset}; expected $desktop" >&2; exit 1 ;;
esac
echo "Ownership and logged-in $desktop environment checks passed. Record the greeter's visual appearance separately."
