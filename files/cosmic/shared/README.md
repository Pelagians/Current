# cosmic/shared/

This tree contains COSMIC-family workstation payloads.

It owns COSMIC-specific greeter and session behavior, COSMIC portal selection, plus the family marker at `usr/share/current/workstation/desktop.env` consumed by the shared workstation display-manager helper.

Keep COSMIC-only session glue here instead of mixing it into `files/workstation/shared/`.

COSMIC uses the native packaged `cosmic-greeter.service` with
`/etc/greetd/cosmic-greeter.toml` on every supported distro lane. Generic greetd
is not a fallback. The shared helper validates this contract and repairs service
ownership at boot. The packaged `/usr/lib/pam.d/cosmic-greeter` stack already
includes keyring support; administrator PAM overrides remain intact.

The shipped `cosmic-portals.conf` follows COSMIC upstream preference order: `cosmic;gtk` with `gnome-keyring` for the Secret portal.
