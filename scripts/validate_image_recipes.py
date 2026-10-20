#!/usr/bin/env python3
"""Validate recipe composition against the supported manifest."""
from __future__ import annotations

import re
from pathlib import Path

from image_matrix import ROOT as root, load_rows, recipe_graph, die
core_base = root / 'recipes/layers/shared/core-base.yml'
shared_core = root / 'recipes/layers/shared/core.yml'
alma_core = root / 'recipes/layers/alma/core.yml'
k3s_feature = root / 'recipes/layers/features/k3s.yml'
ceph_feature = root / 'recipes/layers/features/ceph.yml'
cockpit_feature = root / 'recipes/layers/features/cockpit.yml'
ceph_host = root / 'recipes/layers/features/ceph-host.yml'
nvidia_base = root / 'recipes/layers/shared/nvidia-base.yml'
alma9_nvidia_workstation = root / 'recipes/layers/alma9/nvidia-workstation.yml'
fedora_nvidia_580 = root / 'recipes/layers/fedora/nvidia-580.yml'
fedora_nvidia_workstation = root / 'recipes/layers/fedora/nvidia-workstation.yml'
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


rows = load_rows()

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

    if graph.count(ceph_host) != int(row['role'] == 'server'):
        die(f"{row['image']}: include features/ceph-host.yml exactly once on servers and never on workstations")

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
    shared_nvidia_workstation_count = graph.count(shared_nvidia_workstation)
    if row['platform'] == 'fedora' and row['driver'] == 'nvidia-580':
        if fedora_nvidia_580_count != 1:
            die(f"Fedora NVIDIA 580 image {row['image']} must include fedora/nvidia-580.yml exactly once")
    elif fedora_nvidia_580_count != 0:
        die(f"Image {row['image']} must not include Fedora NVIDIA 580 layers")

    fedora_open = root / 'recipes/layers/fedora/nvidia-open.yml'
    expected_open = row['platform'] == 'fedora' and row['driver'] == 'nvidia-open'
    if graph.count(fedora_open) != int(expected_open):
        die(f"{row['image']}: incorrect Fedora open-module source dispatcher")
    fedora_workstation = row['platform'] == 'fedora' and row['driver'] != 'standard' and row['role'] == 'workstation'
    if graph.count(fedora_nvidia_workstation) != int(fedora_workstation):
        die(f"{row['image']}: incorrect Fedora NVIDIA workstation dispatcher")
    if fedora_workstation and shared_nvidia_workstation_count:
        die(f"{row['image']}: use the explicit variant/architecture userspace source")

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

# Distrobox compatibility paths are materialized after the package transaction.
core_text = shared_core.read_text()
if not core_text.index('- distrobox\n') < core_text.index('- distrobox-helper-links.sh'):
    die('Distrobox helper links must follow distrobox installation')
