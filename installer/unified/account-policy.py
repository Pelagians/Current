#!/usr/bin/env python3
"""Label newly created Anaconda accounts with the installed payload's policy.

Keep this in the installer runtime. Never relabel reused home trees, force a
particular context, or leave a service that can relabel an administrator's data
on subsequent boots/rebases.
"""
import ast
import importlib.util
import inspect
from pathlib import Path


def _current_label_new_home(root, homedir):
    # Resolve /home -> /var/home inside the installed root, not the live ISO.
    home = util.execWithCapture('readlink', ['-e', '--', homedir], root=root).strip()
    if not home.startswith('/') or home == '/' or '\n' in home:
        raise RuntimeError('Cannot resolve the newly created Current home')
    # restorecon intentionally exits zero without doing anything if its chroot
    # cannot see selinuxfs. Never treat that no-op as a successful label repair.
    if util.execWithRedirect('selinuxenabled', [], root=root):
        raise RuntimeError('Installed root cannot see the active SELinux filesystem')
    if util.execWithRedirect('restorecon', ['-R', '-v', '--', home], root=root):
        raise RuntimeError('Cannot label the newly created Current home')
    paths = ['/etc/passwd', '/etc/shadow', '/etc/group', '/etc/gshadow', '/etc/.pwd.lock']
    if util.execWithRedirect('restorecon', ['-i', '-v', '--', *paths], root=root):
        raise RuntimeError('Cannot label Current account state')


def install(path):
    source = path.read_text()
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'create_user']
    if len(functions) != 1 or '_current_label_new_home' in source:
        raise ValueError('Anaconda account contract changed; review integration')
    function = functions[0]
    body = ast.get_source_segment(source, function)
    if ('mk_homedir = not os.path.exists(root + homedir)' not in body
            or 'util.execWithRedirect("useradd", args)' not in body
            or any(isinstance(node, ast.Return) for node in ast.walk(function))):
        raise ValueError('Anaconda account contract changed; review integration')
    lines = source.splitlines(keepends=True)
    lines.insert(function.end_lineno,
                 '\n    if mk_homedir:\n        _current_label_new_home(root, homedir)\n')
    source = ''.join(lines) + '\n\n' + inspect.getsource(_current_label_new_home)
    compile(source, str(path), 'exec')
    path.write_text(source)


def install_mounts(path):
    source = path.read_text()
    classes = [node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == 'PrepareBootcMountTargetsTask']
    if len(classes) != 1:
        raise ValueError('Anaconda bootc mount contract changed; review integration')
    original = ast.get_source_segment(source, classes[0])
    anchor = 'for path in ("/proc", "/sys"):'
    if (original.count(anchor) != 1 or '/sys/fs/selinux' in original
            or 'safe_exec_program("mount", ["--bind", path, sysroot_path])' not in original
            or 'self._internal_mounts.append(sysroot_path)' not in original):
        raise ValueError('Anaconda bootc mount contract changed; review integration')
    # A nonrecursive /sys bind excludes its separately mounted selinuxfs. Bind
    # only that required API, and let Anaconda's existing reverse teardown own it.
    replacement = original.replace(anchor, 'for path in ("/proc", "/sys", "/sys/fs/selinux"):')
    source = source.replace(original, replacement, 1)
    compile(source, str(path), 'exec')
    path.write_text(source)


if __name__ == '__main__':
    package = importlib.util.find_spec('pyanaconda')
    root = Path(package.origin).parent
    install(root / 'core/users.py')
    install_mounts(root / 'modules/payloads/payload/rpm_ostree/installation.py')
