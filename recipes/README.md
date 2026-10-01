# recipes/

This tree defines the buildable images and the reusable layers they compose.

## Image tree

```text
recipes/images/
  workstation/
    gnome/
      alma9/
      alma10/
      fedora/
    cosmic/
      alma9/
      alma10/
      fedora/
  server/
    alma9/
    alma10/
    fedora/
```

CI selects architecture first, then server/workstation role. Existing x64 recipe
paths remain in place; ARM candidates live under `images/arm64/`. Both reuse the
same role and desktop layers. See [ARM candidate status](../docs/maintainers/arm-image-lanes.md).

- `workstation` is the flagship desktop role.
- `server` is the headless admin/operator role.
- GNOME and COSMIC are workstation environments under the workstation role.

Supported published tags are short and come from the shipped image matrix rather than from the internal filenames.

## How images relate

- Every recipe builds from an explicit distro core plus the shared admin/operator overlay carried through `shared/core.yml`.
- Workstation recipes build from an explicit distro core plus the shared workstation and environment layers.
- Fedora has both workstation and server recipes.
- The machine-readable support contract lives in `files/base/runtime/usr/share/current/image-matrix.tsv`.
- Retired product lines stay deleted; if the product model changes, update the manifest first and then add recipes intentionally.

## Reading order

1. open the target image under `recipes/images/**`
2. follow each `from-file:` in order
3. use `recipes/layers/README.md` to understand what each layer is allowed to own
4. use `files/README.md` when a `files` module pulls payload trees
