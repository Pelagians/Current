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


if __name__ == '__main__':
    package = importlib.util.find_spec('pyanaconda')
    install(Path(package.origin).parent / 'core/users.py')
