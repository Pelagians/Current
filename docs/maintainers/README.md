# Maintainer map

| Change | Start here |
| --- | --- |
| Supported images, architecture and recipe composition | [Image architecture](image-architecture.md), shipped `image-matrix.tsv`, `recipes/images/` |
| Layer ownership and runtime safeguards | [Runtime contracts](runtime-contracts.md), `recipes/layers/` and matching `files/` payloads |
| Display managers and desktop sessions | [Workstation layering](workstation-layering.md), [boot qualification](workstation-rebase-qualification.md) |
| Distro and CPU exceptions | [Alma drift](alma-drift.md), [ARM lanes and qualification](arm-image-lanes.md) |
| Signatures, indexes, tags and promotion | [Image publishing](image-publishing.md), `.github/workflows/` |
| Local checks and fixtures | [Validation](validation.md), `scripts/tests/` |

CI selects architecture before server/workstation. Shared recipes retain explicit
distro and CPU exceptions. User instructions live in [the user guide](../user/README.md);
policy history lives in [decision records](../decisions/README.md).
