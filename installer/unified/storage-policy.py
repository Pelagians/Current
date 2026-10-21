#!/usr/bin/env python3
"""Install Current's filesystem policy into the Anaconda runtime only.

Anaconda 44 provides a root-device allowlist, but no filesystem denylist.
Register one check in its existing pre-install storage validator; fail the image
build if that integration point changes. Do not replace upstream checks.
Apply the Alma-compatible XFS creation option at Blivet's formatter, rather than
changing the storage plan during validation or rewriting existing filesystems.
"""
import inspect
import importlib.util
import ast
from pathlib import Path
import textwrap


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
    compile(source, str(path), 'exec')
    path.write_text(source)


def xfs_do_task(self, options=None, label=False, set_uuid=False, nodiscard=False):
    """Create XFS that Alma 9 can both mount and inspect with repair tools.

    Apply at the formatter, including manual partitions and /boot. Existing
    filesystems are untouched. Disable parent pointers (kernel incompatibility)
    and atomic extent exchange (xfs_repair incompatibility). Conflicting options make
    mkfs.xfs reject the request before formatting instead of weakening this.
    """
    return super(type(self), self).do_task(
        options=[*(options or []), '-nparent=0', '-iexchange=0'], label=label,
        set_uuid=set_uuid, nodiscard=nodiscard)


def install_xfs(path):
    source = path.read_text()
    anchor = '''class XFSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_XFS_MKFS
    fstype = "xfs"
    can_nodiscard = True
    can_set_uuid = True
    can_label = True
    force = True
'''
    classes = [node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == 'XFSMkfs']
    if (source.count(anchor) != 1 or len(classes) != 1
            or ast.get_source_segment(source, classes[0]) != anchor.rstrip()):
        raise ValueError('Blivet XFS formatter contract changed; review integration')
    method = inspect.getsource(xfs_do_task).replace('def xfs_do_task(', 'def do_task(', 1)
    # Bind super to the concrete upstream class, including when it is subclassed.
    method = method.replace('super(type(self), self)', 'super(XFSMkfs, self)')
    source = source.replace(anchor, anchor + '\n' + textwrap.indent(method, '    '))
    compile(source, str(path), 'exec')
    path.write_text(source)


if __name__ == '__main__':
    # Importing the storage package probes live firmware. A native ARM container
    # build has no EFI runtime, so locate and compile the packaged source without
    # initializing Anaconda's hardware detection. Real VM tests exercise it.
    package = importlib.util.find_spec('pyanaconda')
    install(Path(package.origin).parent / 'modules/storage/checker/utils.py')
    package = importlib.util.find_spec('blivet')
    install_xfs(Path(package.origin).parent / 'tasks/fsmkfs.py')
