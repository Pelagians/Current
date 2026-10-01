#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

matrix_file="files/base/runtime/usr/share/current/image-matrix.tsv"
matrix_script="scripts/render-image-matrix.py"
workflow_file=".github/workflows/build-architecture.yml"

supported_recipes="$(python3 "$matrix_script" recipes | sort)"
actual_recipes="$(find recipes/images -type f -name '*.yml' | sort)"

if [ "$actual_recipes" != "$supported_recipes" ]; then
  printf 'Recipe tree does not match the supported image manifest.\n' >&2
  diff -u <(printf '%s\n' "$supported_recipes") <(printf '%s\n' "$actual_recipes") >&2 || true
  exit 1
fi

for retired_dir in \
  recipes/images/core \
  recipes/images/gnome \
  recipes/images/cosmic

do
  [ ! -e "$retired_dir" ] || {
    printf 'Retired recipe directory still present: %s\n' "$retired_dir" >&2
    exit 1
  }
done

for retired_path in \
  recipes/images/console \
  recipes/layers/shared/console.yml \
  files/console/shared/usr/share/current/console/role.env \
  recipes/layers/alma9/full.yml \
  recipes/layers/alma10/full.yml \
  recipes/layers/fedora/gnome.yml \
  recipes/layers/shared/gnome-base.yml \
  recipes/layers/shared/nvidia-gnome.yml \
  recipes/layers/features/rocm-developer-tools.yml \
  files/gnome/flatpak/README.md \
  recipes/layers/shared/end-user-common.yml \
  files/end-user/shared/README.md \
  scripts/verify-alma9-nvidia-legacy.ps1

do
  [ ! -e "$retired_path" ] || {
    printf 'Retired path still present: %s\n' "$retired_path" >&2
    exit 1
  }
done

if find recipes/images/workstation -type f -name 'full*.yml' 2>/dev/null | grep -q .; then
  printf 'Workstation full recipes are no longer supported and must be removed.\n' >&2
  exit 1
fi

if grep -RInE -- 'nvidia-legacy' files/base/runtime/usr/share/current/image-matrix.tsv recipes/images scripts/render-image-matrix.py >/dev/null; then
  printf 'Legacy NVIDIA naming still leaks into the active matrix or recipe tree.\n' >&2
  exit 1
fi

json_check() {
  python3 -c 'import json, sys; payload=json.load(sys.stdin); assert isinstance(payload, list)'
}

while IFS= read -r platform; do
  [ -n "$platform" ] || continue
  python3 "$matrix_script" recipes --platform "$platform" >/dev/null
done < <(tail -n +2 "$matrix_file" | cut -f3 | sort -u)

for architecture in x86_64 aarch64; do
  for job in server-images workstation-images; do
    python3 "$matrix_script" gha --architecture "$architecture" "$job" | json_check >/dev/null
  done
done

python3 "$matrix_script" rebase | grep -q .

python3 <<'PY'
from __future__ import annotations

import csv
import re
from pathlib import Path

root = Path('.')
matrix_file = root / 'files/base/runtime/usr/share/current/image-matrix.tsv'
include_re = re.compile(r'^\s*-\s+from-file:\s+([^\s#]+)\s*(?:#.*)?$')
core_base = root / 'recipes/layers/shared/core-base.yml'
shared_core = root / 'recipes/layers/shared/core.yml'
alma_core = root / 'recipes/layers/alma/core.yml'
k3s_feature = root / 'recipes/layers/features/k3s.yml'
ceph_feature = root / 'recipes/layers/features/ceph.yml'
cockpit_feature = root / 'recipes/layers/features/cockpit.yml'
platform_ceph_layers = {
    'alma9': root / 'recipes/layers/alma9/ceph-host.yml',
    'alma10': root / 'recipes/layers/alma10/ceph-host.yml',
    'fedora': root / 'recipes/layers/fedora/ceph-host.yml',
}
nvidia_base = root / 'recipes/layers/shared/nvidia-base.yml'
alma9_nvidia_workstation = root / 'recipes/layers/alma9/nvidia-workstation.yml'
fedora_nvidia_580 = root / 'recipes/layers/fedora/nvidia-580.yml'
fedora_nvidia_580_workstation = root / 'recipes/layers/fedora/nvidia-580-workstation.yml'
shared_nvidia_workstation = root / 'recipes/layers/shared/nvidia-workstation.yml'
recipe_ymls = sorted((root / 'recipes').rglob('*.yml'))
alma_only_shared_patterns = {
    'epel-release': 'EPEL is Alma/RHEL-family repository setup; use layers/alma/core.yml',
    'config-manager --set-enabled crb': 'CRB is Alma/RHEL-family repository setup; use layers/alma/core.yml',
    'subscription-manager': 'subscription-manager removal is Alma/RHEL-family cleanup; use layers/alma/core.yml',
}

for shared_layer in sorted((root / 'recipes/layers/shared').glob('*.yml')):
    shared_text = shared_layer.read_text(encoding='utf-8')
    for pattern, reason in alma_only_shared_patterns.items():
        if pattern in shared_text:
            raise SystemExit(f'{shared_layer} contains Alma-only setup ({pattern}): {reason}')


def die(message: str) -> None:
    raise SystemExit(message)


def include_path(ref: str, owner: Path) -> Path:
    ref = ref.strip().strip('"\'')
    if ref.startswith('layers/'):
        return root / 'recipes' / ref
    if ref.startswith('recipes/'):
        return root / ref
    die(f'{owner}: unsupported from-file path: {ref}')


def direct_includes(path: Path) -> list[Path]:
    if not path.is_file():
        die(f'missing recipe/layer included by the matrix graph: {path}')
    includes: list[Path] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        match = include_re.match(line)
        if match:
            includes.append(include_path(match.group(1), path))
    return includes


def recipe_graph(path: Path, stack: tuple[Path, ...] = ()) -> list[Path]:
    if path in stack:
        cycle = ' -> '.join(str(item) for item in (*stack, path))
        die(f'recursive from-file graph: {cycle}')
    graph = [path]
    for include in direct_includes(path):
        graph.extend(recipe_graph(include, (*stack, path)))
    return graph


def exact_line_count(pattern: str, paths: list[Path]) -> int:
    line_re = re.compile(pattern)
    total = 0
    for candidate in paths:
        total += sum(
            1
            for line in candidate.read_text(encoding='utf-8').splitlines()
            if line_re.match(line)
        )
    return total


with matrix_file.open('r', encoding='utf-8', newline='') as handle:
    rows = list(csv.DictReader(handle, delimiter='\t'))

fedora_nvidia_580_rows = [
    row for row in rows
    if row['platform'] == 'fedora' and row['driver'] == 'nvidia-580'
]
if len(fedora_nvidia_580_rows) != 6:
    die(
        'Expected exactly six Fedora NVIDIA 580 rows in the image matrix '
        f'(server, GNOME, COSMIC on both architectures); found {len(fedora_nvidia_580_rows)}'
    )

expected_fedora_nvidia_580_images = {
    'fedora-server-nvidia-580',
    'fedora-gnome-nvidia-580',
    'fedora-cosmic-nvidia-580',
}
actual_fedora_nvidia_580_images = {row['image'] for row in fedora_nvidia_580_rows}
if actual_fedora_nvidia_580_images != expected_fedora_nvidia_580_images:
    die(
        'Fedora NVIDIA 580 rows must be exactly '
        f'{sorted(expected_fedora_nvidia_580_images)}; found '
        f'{sorted(actual_fedora_nvidia_580_images)}'
    )

for row in rows:
    recipe = root / row['recipe']
    graph = recipe_graph(recipe)
    text = recipe.read_text(encoding='utf-8')
    # Supplemental Alma packages are restricted to the ARM image/role that
    # needs them. Install them before the existing common transaction.
    for platform, environment, name, before in (
        ('alma9', None, 'arm-core', core_base),
        ('alma9', 'cosmic', 'arm-cosmic', root / 'recipes/layers/alma/cosmic.yml'),
        ('alma10', 'gnome', 'arm-gnome', root / 'recipes/layers/shared/workstation-gnome-modern.yml'),
        ('alma10', 'cosmic', 'arm-cosmic', root / 'recipes/layers/alma/cosmic.yml'),
    ):
        layer = root / 'recipes/layers' / platform / (name + '.yml')
        expected = row['platform'] == platform and any(r['image'] == row['image'] and r['architecture'] == 'aarch64' for r in rows)
        expected = expected and (environment is None or row['environment'] == environment)
        if graph.count(layer) != int(expected):
            die(f"{row['image']}: incorrect supplemental ARM package layer {layer}")
        if expected and not graph.index(layer) < graph.index(before):
            die(f"{row['image']}: {layer} must precede {before}")
    if row['platform'] in {'alma10', 'fedora'}:
        rocm = root / 'recipes/layers' / row['platform'] / 'rocm.yml'
        if graph.count(rocm) != 1:
            die(f"{row['image']} must include the architecture-guarded ROCm layer")
    expected_platforms = {'linux/arm64' if r['architecture'] == 'aarch64' else 'linux/amd64'
                          for r in rows if r['image'] == row['image']}
    platforms = set(re.findall(r'^  - (linux/\S+)$', text, re.M))
    if platforms != expected_platforms:
        die(f"{row['image']} must explicitly select {expected_platforms}")

    if f"name: {row['image']}\n" not in text:
        die(f"{recipe}: recipe name must match manifest image")

    if graph.count(core_base) != 1:
        die(f"{row['image']} must include shared/core-base.yml exactly once")

    if graph.count(k3s_feature) != 1:
        die(f"{row['image']} must include features/k3s.yml exactly once")

    if graph.count(shared_core) != 1:
        die(f"{row['image']} must include shared/core.yml exactly once")

    alma_core_count = graph.count(alma_core)
    if row['platform'].startswith('alma'):
        if alma_core_count != 1:
            die(f"Alma image {row['image']} must include alma/core.yml exactly once")
        if not (graph.index(core_base) < graph.index(alma_core) < graph.index(shared_core)):
            die(f"Alma image {row['image']} must order core layers as shared/core-base.yml, alma/core.yml, shared/core.yml")
    elif alma_core_count != 0:
        die(f"Non-Alma image {row['image']} must not include alma/core.yml")
    elif not (graph.index(core_base) < graph.index(shared_core)):
        die(f"{row['image']} must order shared/core-base.yml before shared/core.yml")

    if graph.count(cockpit_feature) != 1:
        die(f"Image {row['image']} must include features/cockpit.yml exactly once")

    if graph.count(ceph_feature) != 1:
        die(f"Image {row['image']} must include features/ceph.yml exactly once")

    expected_platform_ceph = platform_ceph_layers.get(row['platform'])
    if expected_platform_ceph is None:
        die(f"No ceph-host validation mapping exists for platform {row['platform']}")

    expected_platform_ceph_count = graph.count(expected_platform_ceph)
    unexpected_platform_ceph = {
        path.relative_to(root).as_posix(): graph.count(path)
        for path in platform_ceph_layers.values()
        if path != expected_platform_ceph and graph.count(path) != 0
    }

    if row['role'] == 'server':
        if expected_platform_ceph_count != 1:
            die(f"Server image {row['image']} must include {expected_platform_ceph.relative_to(root)} exactly once")
        if unexpected_platform_ceph:
            die(f"Server image {row['image']} must not include non-matching ceph-host layers: {unexpected_platform_ceph}")
    else:
        if expected_platform_ceph_count != 0 or unexpected_platform_ceph:
            die(f"Workstation image {row['image']} must not include any ceph-host package layers")

    nvidia_count = graph.count(nvidia_base)
    if row['driver'] == 'standard':
        if nvidia_count != 0:
            die(f"standard image {row['image']} must not include shared/nvidia-base.yml")
    elif nvidia_count != 1:
        die(f"NVIDIA image {row['image']} must include shared/nvidia-base.yml exactly once")

    alma9_nvidia_workstation_count = graph.count(alma9_nvidia_workstation)
    if row['platform'] == 'alma9' and row['driver'] != 'standard' and row['role'] == 'workstation':
        if alma9_nvidia_workstation_count != 1:
            die(f"Alma 9 NVIDIA workstation {row['image']} must include alma9/nvidia-workstation.yml exactly once")
    elif alma9_nvidia_workstation_count != 0:
        die(f"Image {row['image']} must not include Alma 9 NVIDIA workstation-only media backend layer")

    fedora_nvidia_580_count = graph.count(fedora_nvidia_580)
    fedora_nvidia_580_workstation_count = graph.count(fedora_nvidia_580_workstation)
    shared_nvidia_workstation_count = graph.count(shared_nvidia_workstation)
    if row['platform'] == 'fedora' and row['driver'] == 'nvidia-580':
        if fedora_nvidia_580_count != 1:
            die(f"Fedora NVIDIA 580 image {row['image']} must include fedora/nvidia-580.yml exactly once")
        if row['role'] == 'workstation':
            if fedora_nvidia_580_workstation_count != 1:
                die(f"Fedora NVIDIA 580 workstation {row['image']} must include fedora/nvidia-580-workstation.yml exactly once")
            if shared_nvidia_workstation_count != 0:
                die(f"Fedora NVIDIA 580 workstation {row['image']} must not include shared/nvidia-workstation.yml")
        elif fedora_nvidia_580_workstation_count != 0:
            die(f"Fedora NVIDIA 580 server {row['image']} must not include Fedora workstation-only NVIDIA layer")
    elif fedora_nvidia_580_count != 0 or fedora_nvidia_580_workstation_count != 0:
        die(f"Image {row['image']} must not include Fedora NVIDIA 580 layers")

    fedora_open = root / 'recipes/layers/fedora/nvidia-open.yml'
    fedora_open_workstation = root / 'recipes/layers/fedora/nvidia-open-workstation.yml'
    expected_open = row['platform'] == 'fedora' and row['driver'] == 'nvidia-open'
    if graph.count(fedora_open) != int(expected_open):
        die(f"{row['image']}: incorrect Fedora open-module source dispatcher")
    if graph.count(fedora_open_workstation) != int(expected_open and row['role'] == 'workstation'):
        die(f"{row['image']}: incorrect Fedora NVIDIA workstation dispatcher")
    if expected_open and shared_nvidia_workstation_count:
        die(f"{row['image']}: use the explicit architecture-specific userspace source")

expected_singletons = {
    'pcp package': (r'^\s*-\s+pcp\s*$', 1),
    'NVIDIA PCP PMDA package': (r'^\s*-\s+pcp-pmda-nvidia-gpu\s*$', 1),
    'pmcd service enablement': (r'^\s*-\s+pmcd\.service\s*$', 1),
    'pmlogger service enablement': (r'^\s*-\s+pmlogger\.service\s*$', 1),
    'NVIDIA PMDA registration service enablement': (r'^\s*-\s+current-pcp-nvidia-pmda-apply\.service\s*$', 1),
}

for label, (pattern, expected) in expected_singletons.items():
    count = exact_line_count(pattern, recipe_ymls)
    if count != expected:
        die(f'{label} must appear exactly {expected} time in recipes/**/*.yml; found {count}')

if any('cockpit-pcp' in item.read_text(encoding='utf-8') for item in recipe_ymls):
    die('cockpit-pcp must not be layered into Current recipes')
PY

required_workflow_snippets=(
  'define-image-matrix:'
  'server_images: ${{ steps.render.outputs.server_images }}'
  'workstation_images: ${{ steps.render.outputs.workstation_images }}'
  "emit_output server_images python3 ./scripts/render-image-matrix.py gha --architecture '\${{ inputs.architecture }}' server-images"
  "emit_output workstation_images python3 ./scripts/render-image-matrix.py gha --architecture '\${{ inputs.architecture }}' workstation-images"
  'include: ${{ fromJSON(needs.define-image-matrix.outputs.server_images) }}'
  'include: ${{ fromJSON(needs.define-image-matrix.outputs.workstation_images) }}'
)

for snippet in "${required_workflow_snippets[@]}"; do
  grep -Fq -- "$snippet" "$workflow_file" || {
    printf 'Workflow is missing manifest-driven matrix wiring: %s\n' "$snippet" >&2
    exit 1
  }
done

for forbidden_snippet in \
  'workstation_core_images' \
  'workstation_full_images' \
  'console_images' \
  'workstation-core-images:' \
  'workstation-full-images:' \
  'console-images:' \
  'verify-alma9-nvidia-legacy.ps1' \
  'github.base_ref || github.ref_name' \
  '--branch "$active_branch"'

do
  if grep -Fq -- "$forbidden_snippet" "$workflow_file"; then
    printf 'Workflow still contains retired matrix wiring: %s\n' "$forbidden_snippet" >&2
    exit 1
  fi
done

if grep -Fq -- 'recipe: /images/' "$workflow_file"; then
  printf 'Workflow still contains hard-coded recipe entries instead of manifest-driven matrices.\n' >&2
  exit 1
fi

# Architecture is selected by the caller before the reusable role split.
for snippet in 'x64-images:' 'arm64-images:' 'architecture: x86_64' 'architecture: aarch64' 'runner: ubuntu-latest' 'runner: ubuntu-24.04-arm'; do
  grep -Fq "$snippet" .github/workflows/build.yml || { echo "Missing architecture-first CI wiring: $snippet" >&2; exit 1; }
done
[[ "$(grep -Fc 'uses: ./.github/workflows/build-architecture.yml' .github/workflows/build.yml)" == 2 ]]
[[ "$(grep -Fc 'runs-on: ${{ inputs.runner }}' "$workflow_file")" == 3 ]]
python3 scripts/tests/test-image-architectures.py
python3 scripts/tests/test-fedora-nvidia.py

python3 scripts/tests/test-image-publication.py
