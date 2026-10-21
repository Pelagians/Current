#!/usr/bin/env python3
"""Install Current's filesystem check into the Anaconda runtime only.

Anaconda 44 provides a root-device allowlist, but no filesystem denylist.
Register one check in its existing pre-install storage validator; fail the image
build if that integration point changes. Do not replace upstream checks.
"""
import ast
import inspect
from pathlib import Path


def verify_current_filesystems(storage, constraints, report_error, report_warning):
    """Reject assigned or newly created Btrfs, leaving unused volumes alone."""
    for device in storage.devices:
        fmt = device.format
        if fmt.type == 'btrfs' and (fmt.mountpoint or not device.exists or not fmt.exists):
            report_error('Current cannot install using Btrfs: AlmaLinux destinations do not '
                         'support it by default. Use XFS for the installed system '
                         f'({fmt.mountpoint or device.name}).')


def install(path):
    source = path.read_text()
    anchor = '        self.add_check(verify_root)\n'
    declaration = 'class StorageChecker:\n'
    if source.count(anchor) != 1 or source.count(declaration) != 1 or 'verify_current_filesystems' in source:
        raise ValueError('Anaconda storage checker contract changed; review integration')
    source = source.replace(declaration, inspect.getsource(verify_current_filesystems) + '\n\n' + declaration)
    source = source.replace(anchor, anchor + '        self.add_check(verify_current_filesystems)\n')
    ast.parse(source)
    path.write_text(source)


if __name__ == '__main__':
    from pyanaconda.modules.storage.checker import utils
    install(Path(utils.__file__))
