# Multi-architecture image publishing

Current has 24 public image families, 45 native builds and 24 shared recipes.
The matrix still records each supported CPU explicitly: 24 x64 and 21 ARM rows.
Alma 9 proprietary R580 has three x64-only families; no ARM variant is implied.

For example, `ghcr.io/pelagians/fedora-gnome:latest` is a signed OCI index with
`linux/amd64` and `linux/arm64` children. bootc resolves its native platform.
Architecture-specific references are `:latest-amd64` and `:latest-arm64` in the
same repository. Existing `fedora-gnome-arm64:latest` references keep receiving
the same ARM child through a signed compatibility repository.

## Build and promotion

The existing architecture-first workflow runs each shared recipe on its native
runner with one explicit `--platform`. A generated, ignored staging recipe adds
an alternate tag `run-<run-id>-<attempt>-<architecture>` and labels recording the
exact source revision and native build identity. BlueBuild may add its usual PR,
branch and distro-version prefixes/suffixes to that tag. Native jobs never write
public shared channels. Generated recipes retain the common modules and native
package/source guards; no new desktop, bootc or image-role model is introduced.

After each successful build, `scripts/publish-image-index.py record` resolves its
actual native digest, checks its config platform/revision/build identity and
uploads a digest artifact. Provenance descriptors are excluded from OS children.
Artifacts must cover every matrix row from the same commit, run and attempt;
paired architectures must also agree on their distro version.

The publisher depends on both complete architecture workflows. It validates all
artifacts and registry configs before publishing. It signs/verifies native child
digests, creates a complete index for each family, verifies its exact platform /
digest set and source revision, then signs/verifies the index. ARM compatibility
repositories are also copied and signed at staging references. Only after every
index and compatibility reference is ready does promotion advance public tags.

Each tag update is atomic. GHCR does not provide a transaction spanning 24
repositories; cancellation or a registry failure during promotion can leave
families at different releases, but every advanced family has a complete, signed
index. Retry the publication after diagnosing the failure; do not construct an
index from mutable native tags or mix artifacts from different runs/attempts.

## Channels and reruns

Only the default `stable` branch advances `:latest`. Pull requests advance
`:pr-<number>`; other branches advance `:br-<branch-with-slashes-replaced>`.
Tag-triggered runs use a source-SHA channel. Each channel also gets `-amd64` /
`-arm64` debug tags and an ARM compatibility repository alias. The publisher signs
compatibility digests in their own repository because signature locations are
repository scoped. Signing uses BlueBuild's Cosign v3 compatibility flags
(`--new-bundle-format=false --use-signing-config=false`) and empty key password,
preserving the `.sig` attachments consumed by containers/image and bootc.
Existing distro streams also advance: `:44` on stable Fedora, and `:pr-28-44`
on its PR channel, for example. ARM compatibility repositories receive those
streams too. Historical dated/SHA tags remain unchanged.

Native artifacts from different attempts are intentionally rejected. After a
failed native build, rerun **all jobs** so all 45 artifacts and their source
labels agree on the attempt. Artifact uploads overwrite only their own previous
native artifact. A failed-job-only rerun cannot publish a mixed-attempt release.

The new nine-column matrix adds `legacy-image`. The new rebase picker accepts
both previous matrix formats for rollout. Older pickers safely reject the new
header; upgrade their installed Current image and reboot before using the new
matrix. The picker retains CPU filtering for unsupported combinations while its
selected reference uses the common public repository.

## Verification

Run the normal validators, which include isolated publication fixtures:

```bash
bash scripts/validate-image-matrix.sh
bash scripts/validate-runtime-artifacts.sh
```

After CI publishes a candidate, inspect the actual index and native configs:

```bash
skopeo inspect --raw docker://ghcr.io/pelagians/fedora-gnome:pr-28
skopeo inspect --override-arch amd64 docker://ghcr.io/pelagians/fedora-gnome:pr-28
skopeo inspect --override-arch arm64 docker://ghcr.io/pelagians/fedora-gnome:pr-28
cosign verify --key cosign.pub ghcr.io/pelagians/fedora-gnome:pr-28
```

Repeat for every family and verify the compatibility ARM repositories. Registry
and fixture checks establish publication contracts. Booted workstation/GPU
qualification remains required; see the persistent rebase qualification document.
