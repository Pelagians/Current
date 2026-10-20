# Image architecture

The support contract is `files/base/runtime/usr/share/current/image-matrix.tsv`.
It describes 45 native builds across 24 public image families. Shared recipes
select CPU-specific package work explicitly; CI selects architecture before role.

## Where to edit

| Concern | Owner |
| --- | --- |
| Supported image/platform/desktop/driver combinations | Shipped TSV manifest |
| Image composition and OCI platforms | `recipes/images/server/<platform>/` or `recipes/images/workstation/<environment>/<platform>/` |
| Low-level baseline, payloads and command surface | `recipes/layers/shared/core-base.yml` |
| Distro repository setup | `recipes/layers/alma/core.yml` and version/platform layers |
| Cross-distro operator tools and Distrobox compatibility links | `recipes/layers/shared/core.yml` |
| Individual capabilities | `recipes/layers/features/` |
| Workstation policy and desktop implementations | `recipes/layers/shared/workstation-*.yml` and matching `files/` trees |
| Native build split and publishing gates | `.github/workflows/build.yml`, `build-architecture.yml`, `scripts/publish-image-index.py` |

[Runtime contracts](runtime-contracts.md) define layer ownership and safeguards.
[Workstation layering](workstation-layering.md) records desktop/distro exceptions.
Keep one owner for shared packages and payloads; platform layers should carry
actual drift. Ceph's common payload (`features/ceph.yml`) applies to all images;
its host package transaction (`features/ceph-host.yml`) applies once per server.

## Manifest and naming

The TSV is shipped at `/usr/share/current/image-matrix.tsv`. The rebase picker
fetches the same source from the stable branch. The nine columns are:

```text
job architecture platform role environment driver image legacy-image recipe
```

`architecture` is `x86_64` or `aarch64`. Public image names are
`<platform>-<environment>` with an optional `-<driver>` suffix; internal recipe
filenames such as `core.yml` do not define public roles. `legacy-image` identifies
supported ARM migration aliases. New references use
`ghcr.io/pelagians/<image>:<tag>` and let the OCI index select the native platform.

`scripts/image_matrix.py` validates the schema, naming, allowed combinations and
recipe includes. The renderer CLI, publisher and build validators share it:

```bash
python3 scripts/render-image-matrix.py recipes
python3 scripts/render-image-matrix.py gha --architecture aarch64 workstation-images
python3 scripts/render-image-matrix.py rebase
```

The runtime picker stays a Bash/awk implementation so installed images need no
build-side Python modules. Compatibility fixtures exercise its three supported
TSV formats and native CPU filtering.

## CI and qualification

The 24 recipes declare their supported OCI platforms. Each CI build restricts
the recipe to one native platform. The publisher combines all 45 native outputs
into verified, signed indexes and preserves ARM repository aliases. Branch-head
and PR-merge candidates both build; branch-tag publishing remains enabled.

See [publishing](image-publishing.md) for digest/signature and channel gates,
[ARM lanes](arm-image-lanes.md) for package differences and qualification status,
and [validation](validation.md) for local checks. A passing build does not qualify
booted desktop switching, retained containers or GPU hardware.
