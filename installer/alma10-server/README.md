# Alma 10 server installer sources

- `Containerfile`: Anaconda-capable installer environment.
- `iso.toml`: canonical interactive installer configuration and embedded Kickstart.
- [`build-alma10-installer-iso.sh`](../../scripts/build-alma10-installer-iso.sh): builder entrypoint.

The [installer guide](../../docs/user/installer-iso.md) documents commands, overrides,
output, filesystem choices and storage safeguards. Generated media belongs in
`output/installer/alma10-server/`, never Git. There is no separate root config copy.
