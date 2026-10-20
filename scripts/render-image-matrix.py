#!/usr/bin/env python3
"""Render the supported image matrix from the shipped TSV manifest."""

from __future__ import annotations

import argparse
import json
import sys

from image_matrix import (
    ALLOWED_ARCHITECTURES, ALLOWED_JOBS, ALLOWED_PLATFORMS, ALLOWED_ROLES,
    ALLOWED_ENVIRONMENTS, ALLOWED_DRIVERS, load_rows, recipe_ref,
)

def display_role(role: str) -> str:
    return role[:1].upper() + role[1:]


def display_environment(environment: str) -> str:
    if environment == 'gnome':
        return 'GNOME'
    if environment == 'cosmic':
        return 'COSMIC'
    return environment[:1].upper() + environment[1:]


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
