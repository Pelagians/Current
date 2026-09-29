# Interactive convenience only. Polkit and filesystem permissions enforce scope.
case $- in
  *i*)
    flatpak() {
      local arg subcommand="" has_scope="" end_options=""
      for arg in "$@"; do
        [ -z "$end_options" ] || break
        case "$arg" in
          --) end_options=1 ;;
          --user|-u|--system|--installation|--installation=*) has_scope=1 ;;
          -*) ;;
          *) if [ -z "$subcommand" ]; then subcommand=$arg; fi ;;
        esac
      done
      if [ -z "$has_scope" ]; then
        case "$subcommand" in
          install|remove|uninstall|update|repair)
            set -- --user "$@"
            ;;
        esac
      fi
      command flatpak "$@"
    }
    ;;
esac
