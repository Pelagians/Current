# Repository validation helpers. Source from a validator; do not install in images.
reject_matches() {
  local result
  if grep "$@"; then
    printf 'Forbidden content matched: grep %s\n' "$*" >&2
    return 1
  else
    result=$?
    # A missing file, unreadable tree or invalid regex must also fail validation.
    if [[ "$result" -ne 1 ]]; then return "$result"; fi
  fi
}
