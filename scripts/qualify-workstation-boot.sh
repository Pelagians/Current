#!/usr/bin/env bash
# Run in a booted disposable Current workstation, after graphical login.
set -euo pipefail

# systemd-managed desktop applications need not inherit XDG_SESSION_ID. Resolve
# the user's primary graphical session through logind without inventing any
# display or desktop environment variables. Safe to source in isolated fixtures.
qualify_session() {
  local desktop="$1" current_desktop="${XDG_CURRENT_DESKTOP:-}" session_id="${XDG_SESSION_ID:-}" uid
  uid="$(id -u)"
  current_desktop="${current_desktop//:/;}"
  case ";${current_desktop^^};" in
    *";$desktop;"*) ;;
    *) echo "Wrong logged-in desktop: ${XDG_CURRENT_DESKTOP:-unset}; expected $desktop" >&2; return 1 ;;
  esac
  case "${XDG_SESSION_TYPE:-}" in wayland|x11) ;; *) echo 'No graphical session environment' >&2; return 1 ;; esac
  [[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] || { echo 'No graphical display environment' >&2; return 1; }
  if [[ -z "$session_id" ]]; then
    session_id="$(loginctl show-user "$uid" --property=Display --value)" || return 1
  fi
  [[ -n "$session_id" ]] || { echo 'No primary graphical session in logind' >&2; return 1; }
  loginctl show-session "$session_id" -p Name -p User -p Desktop -p Type -p State
  [[ "$(loginctl show-session "$session_id" --property=User --value)" == "$uid" ]] || { echo 'Graphical session belongs to another user' >&2; return 1; }
  [[ "$(loginctl show-session "$session_id" --property=Type --value)" == "$XDG_SESSION_TYPE" ]] || { echo 'Logind session type does not match the graphical environment' >&2; return 1; }
  [[ "$(loginctl show-session "$session_id" --property=State --value)" == active ]] || { echo 'Graphical session is not active' >&2; return 1; }
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi

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
qualify_session "$desktop"
echo "Ownership and logged-in $desktop environment checks passed. Record the greeter's visual appearance separately."
