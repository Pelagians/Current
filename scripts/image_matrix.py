"""Build-side image manifest and recipe graph contracts (stdlib only)."""
from __future__ import annotations
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "files/setup/usr/lib"))
from current_setup.matrix import (FIELDS, ALLOWED_ARCHITECTURES, ALLOWED_PLATFORMS,
    ALLOWED_JOBS, ALLOWED_ROLES, ALLOWED_ENVIRONMENTS, ALLOWED_DRIVERS, ARM_DRIVERS,
    RECIPE_SUFFIXES, expected_image, expected_recipe, recipe_ref, load_rows as _load_rows)
MATRIX_FILE = ROOT / "files/base/runtime/usr/share/current/image-matrix.tsv"

def die(message: str) -> None:
    raise SystemExit(message)

def load_rows():
    try:
        return _load_rows(MATRIX_FILE)
    except ValueError as error:
        die(str(error))


INCLUDE_RE = re.compile(r'^\s*-\s+from-file:\s+([^\s#]+)\s*(?:#.*)?$')

def include_path(ref: str, owner: Path) -> Path:
    ref = ref.strip().strip('"\'')
    if ref.startswith('layers/'):
        return ROOT / 'recipes' / ref
    if ref.startswith('recipes/'):
        return ROOT / ref
    die(f'{owner}: unsupported from-file path: {ref}')


def direct_includes(path: Path) -> list[Path]:
    if not path.is_file():
        die(f'missing recipe/layer included by the matrix graph: {path}')
    includes: list[Path] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        match = INCLUDE_RE.match(line)
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
