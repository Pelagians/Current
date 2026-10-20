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

python3 scripts/validate_image_recipes.py

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

python3 -m unittest discover -s scripts/tests -p 'test_image_*.py' -v
