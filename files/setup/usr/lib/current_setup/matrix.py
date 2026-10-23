"""Shared, strict inventory parser; no network or host operations."""
from pathlib import Path
import csv

FIELDS = ['job', 'architecture', 'platform', 'role', 'environment', 'driver', 'image', 'legacy-image', 'recipe']
ALLOWED_ARCHITECTURES = ('x86_64', 'aarch64')
ALLOWED_PLATFORMS = ('alma9', 'alma10', 'fedora')
ALLOWED_JOBS = ('server-images', 'workstation-images')
ALLOWED_ROLES = ('server', 'workstation')
ALLOWED_ENVIRONMENTS = ('cosmic', 'gnome', 'server')
ALLOWED_DRIVERS = ('nvidia-580', 'nvidia-open', 'standard')
ARM_DRIVERS = {
    'alma9': ('standard', 'nvidia-open'),
    'alma10': ('standard', 'nvidia-open'),
    'fedora': ('standard', 'nvidia-580', 'nvidia-open'),
}
RECIPE_SUFFIXES = {
    'standard': '',
    'nvidia-open': '-nvidia-open',
    'nvidia-580': '-nvidia-580',
}


def die(message: str) -> None:
    raise ValueError(message)


def recipe_ref(recipe: str) -> str:
    if not recipe.startswith('recipes/'):
        die(f"recipe path must start with 'recipes/': {recipe}")
    return '/' + recipe.removeprefix('recipes/')


def expected_image(row: dict[str, str]) -> str:
    base = f"{row['platform']}-{row['environment']}"
    image = base if row['driver'] == 'standard' else f"{base}-{row['driver']}"
    return image


def expected_recipe(row: dict[str, str]) -> str:
    suffix = RECIPE_SUFFIXES[row['driver']]
    prefix = 'recipes/images'
    if row['role'] == 'server':
        return f"{prefix}/server/{row['platform']}/server{suffix}.yml"
    return (
        f"{prefix}/workstation/{row['environment']}/{row['platform']}/"
        f"core{suffix}.yml"
    )


def load_rows(path: Path) -> list[dict[str, str]]:
    MATRIX_FILE = path
    if not MATRIX_FILE.is_file():
        die(f'matrix file not found: {MATRIX_FILE}')

    with MATRIX_FILE.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle, delimiter='	')
        if reader.fieldnames != FIELDS:
            die('image matrix header must be exactly: ' + '	'.join(FIELDS))

        rows: list[dict[str, str]] = []
        seen_images: set[tuple[str, str]] = set()
        seen_keys: set[tuple[str, str, str, str, str]] = set()

        for line_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                die(f'{MATRIX_FILE}:{line_number}: extra fields')
            row = {field: (raw_row.get(field) or '').strip() for field in FIELDS}
            missing = [field for field, value in row.items() if not value]
            if missing:
                die(
                    f'{MATRIX_FILE}:{line_number}: missing required fields: '
                    + ', '.join(missing)
                )

            if row['architecture'] not in ALLOWED_ARCHITECTURES:
                die(f"{MATRIX_FILE}:{line_number}: unsupported architecture: {row['architecture']}")
            if row['architecture'] == 'aarch64' and row['driver'] not in ARM_DRIVERS.get(row['platform'], ()):
                die(f"{MATRIX_FILE}:{line_number}: unsupported ARM64 platform/driver contract: {row['platform']}/{row['driver']}")
            if row['job'] not in ALLOWED_JOBS:
                die(f"{MATRIX_FILE}:{line_number}: unsupported job: {row['job']}")
            if row['platform'] not in ALLOWED_PLATFORMS:
                die(f"{MATRIX_FILE}:{line_number}: unsupported platform: {row['platform']}")
            if row['role'] not in ALLOWED_ROLES:
                die(f"{MATRIX_FILE}:{line_number}: unsupported role: {row['role']}")
            if row['environment'] not in ALLOWED_ENVIRONMENTS:
                die(
                    f"{MATRIX_FILE}:{line_number}: unsupported environment: "
                    f"{row['environment']}"
                )
            if row['driver'] not in ALLOWED_DRIVERS:
                die(
                    f"{MATRIX_FILE}:{line_number}: unsupported driver lane: "
                    f"{row['driver']}"
                )
            if not row['recipe'].startswith('recipes/images/') or not row['recipe'].endswith('.yml'):
                die(f"{MATRIX_FILE}:{line_number}: invalid recipe path: {row['recipe']}")
            if row['image'] != expected_image(row):
                die(
                    f"{MATRIX_FILE}:{line_number}: image tag must match platform, "
                    f"environment, and driver: {row['image']}"
                )
            if row['recipe'] != expected_recipe(row):
                die(
                    f"{MATRIX_FILE}:{line_number}: recipe path does not match the "
                    f"supported naming convention: {row['recipe']}"
                )
            legacy_image = row['image'] + ('-arm64' if row['architecture'] == 'aarch64' else '')
            if row['legacy-image'] != legacy_image:
                die(f"{MATRIX_FILE}:{line_number}: incorrect migration alias: {row['legacy-image']}")
            if (row['image'], row['architecture']) in seen_images:
                die(f"{MATRIX_FILE}:{line_number}: duplicate image tag: {row['image']}")

            key = (row['architecture'], row['platform'], row['role'], row['environment'], row['driver'])
            if key in seen_keys:
                die(
                    f"{MATRIX_FILE}:{line_number}: duplicate platform/environment/driver "
                    f"entry: {key}"
                )

            if row['role'] == 'server':
                if row['job'] != 'server-images' or row['environment'] != 'server':
                    die(
                        f"{MATRIX_FILE}:{line_number}: server rows must use the "
                        'server-images job and server environment'
                    )
            elif row['job'] != 'workstation-images' or row['environment'] not in {'gnome', 'cosmic'}:
                die(
                    f"{MATRIX_FILE}:{line_number}: workstation rows must use the "
                    'workstation-images job with gnome/cosmic environments'
                )

            seen_images.add((row['image'], row['architecture']))
            seen_keys.add(key)
            rows.append(row)

    if not rows:
        die('image matrix is empty')
    return rows
