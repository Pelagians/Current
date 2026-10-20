# Compatibility policy

Current uses `current`, `ghcr.io/pelagians`, `/usr/share/current`, and `CURRENT_*`.
The earlier myOS CLI, runtime paths, environment fallbacks and cross-namespace
publisher have been removed. Historical decision records describe that migration;
they do not promise that retired interfaces remain installed.

## Supported compatibility surfaces

- Architecture-aware rebasing accepts the earlier matrix headers as well as the
  current manifest. See [image architecture](maintainers/image-architecture.md).
- Published `*-arm64` repositories remain migration aliases for existing ARM
  deployments. New installs use the canonical multi-architecture repository.
  See [image publishing](maintainers/image-publishing.md).
- `current clean-system` remains an alias for managed system Flatpak maintenance.

Use Current names in new automation. A redirect from an old repository URL does
not imply that old image namespaces, commands or environment variables work.
Changes to the supported surfaces above must update their tests and documentation.
