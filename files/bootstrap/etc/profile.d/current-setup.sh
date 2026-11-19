# Prompt only after an authenticated local console login on the bootstrap.
# This file may survive an /etc merge; the vendor marker cannot.
case $- in
  *i*)
    if [ -f /usr/share/current/bootstrap ] && [ -z "${SSH_CONNECTION:-}" ] && [ -t 0 ]; then
      case "$(tty 2>/dev/null)" in
        /dev/tty[0-9]*|/dev/ttyS[0-9]*|/dev/ttyAMA[0-9]*|/dev/hvc[0-9]*)
          if [ "$(id -u)" = 0 ]; then
            /usr/libexec/current-setup || :
          elif id -nG | tr ' ' '\n' | grep -qx wheel; then
            printf '\nCurrent initial setup (administrator authentication required).\n'
            sudo /usr/libexec/current-setup || :
          else
            printf '\nAsk an administrator to run sudo current setup.\n'
          fi
          ;;
      esac
    fi
    ;;
esac
