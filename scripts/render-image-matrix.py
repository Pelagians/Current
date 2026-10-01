#!/usr/bin/env python3
"""Render the supported image matrix from the shipped TSV manifest."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX_FILE = ROOT / 'files/base/runtime/usr/share/current/image-matrix.tsv'
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
    raise SystemExit(message)


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


def display_role(role: str) -> str:
    return role[:1].upper() + role[1:]


def display_environment(environment: str) -> str:
    if environment == 'gnome':
        return 'GNOME'
    if environment == 'cosmic':
        return 'COSMIC'
    return environment[:1].upper() + environment[1:]


def load_rows() -> list[dict[str, str]]:
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

    return rows


def filter_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, str]]:
    for field in ('job', 'architecture', 'platform', 'role', 'environment', 'driver'):
        value = getattr(args, field, None)
        if value:
            rows = [row for row in rows if row[field] == value]
    return rows


def cmd_recipes(args: argparse.Namespace) -> int:
    for recipe in dict.fromkeys(row['recipe'] for row in filter_rows(load_rows(), args)):
        print(recipe)
    return 0


def cmd_gha(args: argparse.Namespace) -> int:
    rows = filter_rows(load_rows(), args)
    payload = [{'name': row['image'], 'recipe': recipe_ref(row['recipe']),
                'platform': 'linux/arm64' if row['architecture'] == 'aarch64' else 'linux/amd64'}
               for row in rows]
    json.dump(payload, sys.stdout, separators=(',', ':'))
    print()
    return 0


def cmd_rebase(_: argparse.Namespace) -> int:
    for row in load_rows():
        print(
            f"{row['architecture']} | {display_role(row['role'])} | "
            f"{display_environment(row['environment'])} | "
            f"{row['platform']} | {row['driver']} | {row['image']}:latest"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)

    recipes = subparsers.add_parser('recipes', help='print supported recipe paths')
    recipes.add_argument('--architecture', choices=sorted(ALLOWED_ARCHITECTURES))
    recipes.add_argument('--job', choices=sorted(ALLOWED_JOBS))
    recipes.add_argument('--platform', choices=sorted(ALLOWED_PLATFORMS))
    recipes.add_argument('--role', choices=sorted(ALLOWED_ROLES))
    recipes.add_argument('--environment', choices=sorted(ALLOWED_ENVIRONMENTS))
    recipes.add_argument('--driver', choices=sorted(ALLOWED_DRIVERS))
    recipes.set_defaults(func=cmd_recipes)

    gha = subparsers.add_parser('gha', help='emit a GitHub Actions matrix JSON array')
    gha.add_argument('--architecture', choices=sorted(ALLOWED_ARCHITECTURES), required=True)
    gha.add_argument('--platform', choices=sorted(ALLOWED_PLATFORMS))
    gha.add_argument('job', choices=sorted(ALLOWED_JOBS))
    gha.set_defaults(func=cmd_gha)

    rebase = subparsers.add_parser('rebase', help='emit current rebase picker rows')
    rebase.set_defaults(func=cmd_rebase)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
