# Contributing

Use the Current CLI, runtime paths and environment variables. Supported migration
interfaces are listed in [the compatibility policy](docs/compatibility.md).
Start with the [maintainer map](docs/maintainers/README.md) to find the owner of a change.

## Start with the image contract

Before changing a layer, decide which role and tier should own that behavior.

- shared low-level base behavior belongs in `recipes/layers/shared/core-base.yml`
- shared cross-distro core tooling belongs in `recipes/layers/shared/core.yml`
- shared Cockpit / Ceph / k3s / PCP / Tailscale behavior belongs in `recipes/layers/features/*.yml`
- shared system policy belongs in `recipes/layers/shared/system-policy.yml`
- workstation behavior belongs in `workstation-common` plus explicit workstation sublayers
- workstation app governance belongs in the Flatpak layers under `recipes/layers/shared/flatpak-*.yml`
- distro-family or distro-version drift belongs under `recipes/layers/alma/`, `recipes/layers/alma9/`, `recipes/layers/alma10/`, or `recipes/layers/fedora/`
- optional capabilities belong under `recipes/layers/features/`

## Keep public and maintainer docs in sync

User-facing docs live under `docs/user/`.
Maintainer and operator docs live under `docs/maintainers/`.
Decision records live under `docs/decisions/`.

If a change alters the supported image matrix, runtime contracts, validation expectations, or public product identity, update the matching docs in the same change.

## Writing guidance

Use Current for public product language.

Use legacy names only when referring to compatibility aliases, migration behavior, old image references, paths, or environment variables that still exist.

Current should sound practical, upstream-respecting, developer-first, and calm. Avoid AI hype, cyberpunk language, electrical-current metaphors, or claims that Current replaces upstream Linux distributions.

## Validation

Run the smallest meaningful set of checks for your change.

Typical local checks:

```bash
git diff --check
bash ./scripts/validate-runtime-artifacts.sh
bash ./scripts/validate-image-matrix.sh
```

If you touch Alma 9 NVIDIA legacy logic and have the tooling available:

```bash
pwsh ./scripts/verify-alma9-nvidia-580.ps1
```

More detail lives in [docs/maintainers/validation.md](docs/maintainers/validation.md).
