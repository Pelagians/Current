#!/usr/bin/env python3
"""Deterministic behavior tests. No host Flatpak installation is touched.

Only fixed executable/lock paths in a temporary helper copy are substituted.
The production helper deliberately exposes no environment-variable root hooks.
"""
import itertools
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'files/flatpak/cleanup/usr/libexec/current-flatpak-system-maintenance'
WRAPPER = ROOT / 'files/flatpak/base/etc/profile.d/flatpak-user-default.sh'
RECIPES = ROOT / 'files/justfiles/usr/share/current/just/update.just'
POLICY = ROOT / 'files/flatpak/base/usr/share/polkit-1/rules.d/00-current-flatpak.rules'

MOCK = r'''#!/usr/bin/python3
import json, os, signal, sys, time
from pathlib import Path
if 'FP_EXPECT_UMASK' in os.environ:
    current_umask = os.umask(0)
    os.umask(current_umask)
    assert current_umask == int(os.environ['FP_EXPECT_UMASK'], 8), oct(current_umask)
state = Path(os.environ['FP_STATE'])
s = json.loads(state.read_text())
a = sys.argv[1:]
assert a.pop(0) == '--system', a
with open(os.environ['FP_LOG'], 'a') as f:
    f.write(json.dumps(a) + '\n')
cmd = a[0]
if cmd == 'remotes':
    if s.get('fail_list'): sys.exit(11)
    if s['exists']:
        options = list(s.get('options', []))
        if s['hidden']: options.append('no-enumerate')
        print('org-system\t' + s.get('url', 'https://dl.flathub.org/repo/') + '\t' + ','.join(options))
elif cmd == 'remote-modify':
    if '--no-enumerate' in a:
        if s.get('fail_restore'): sys.exit(12)
        s['hidden'] = True
    else:
        if s.get('fail_prepare'): sys.exit(13)
        s['hidden'] = False
elif cmd == 'update':
    # Version B needs a branch not installed by version A. Discovery must be open.
    if s['exists'] and s['hidden']: sys.exit(21)
    if s.get('hold'):
        Path(os.environ['FP_READY']).touch()
        while not Path(os.environ['FP_RELEASE']).exists(): time.sleep(.01)
    if s.get('fail_update'): sys.exit(22)
    s['required'] = 'runtime/B'
    s['installed'] = sorted(set(s['installed']) | {'runtime/B'})
elif cmd == 'uninstall':
    assert a == ['uninstall', '--unused', '-y', '--noninteractive'], a
    if s.get('fail_cleanup'): sys.exit(23)
    s['installed'] = [r for r in s['installed'] if r == s['required'] or r in s['pins']]
elif cmd == 'repair':
    if s.get('fail_repair'): sys.exit(24)
elif cmd == 'list': pass
else: raise AssertionError(a) # A pin mutation, explicit runtime install, or unknown operation fails.
state.write_text(json.dumps(s))
'''


def write_executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def recipe(name):
    lines = RECIPES.read_text().splitlines()
    start = lines.index(name + ':') + 1
    body = []
    for line in lines[start:]:
        if line and not line.startswith(' '): break
        if line: body.append(line[4:])
    return '\n'.join(body) + '\n'


class Transaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.state = self.d / 'state.json'
        self.log = self.d / 'log'
        self.env = dict(os.environ, FP_STATE=str(self.state), FP_LOG=str(self.log),
                        FP_READY=str(self.d / 'ready'), FP_RELEASE=str(self.d / 'release'))
        self.save(exists=True, hidden=True, required='runtime/A',
                  installed=['runtime/A', 'runtime/unused', 'runtime/admin'], pins=['runtime/admin'])
        self.mock = self.d / 'flatpak'
        write_executable(self.mock, MOCK)
        self.setup = self.d / 'setup'
        write_executable(self.setup, '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['FP_STATE'])
s = json.loads(p.read_text())
assert not s['exists'] or not s['hidden']
s['exists'] = True
s['hidden'] = False
p.write_text(json.dumps(s))
sys.exit(25 if s.get('fail_setup') else 0)
''')
        self.helper = self.d / 'helper'
        source = HELPER.read_text().replace('/usr/bin/flatpak', str(self.mock))
        source = source.replace('/run/current-flatpak-maintenance.lock', str(self.d / 'lock'))
        source = source.replace('/usr/libexec/bluebuild/default-flatpaks/system-flatpak-setup', str(self.setup))
        # Permit the isolated fixture to run in unprivileged CI; test the real gate separately.
        source = source.replace('[ "$EUID" -eq 0 ]', '[ "0" -eq 0 ]')
        write_executable(self.helper, source)

    def save(self, **changes):
        s = json.loads(self.state.read_text()) if self.state.exists() else {}
        s.update(changes)
        self.state.write_text(json.dumps(s))

    def read(self):
        return json.loads(self.state.read_text())

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_helper(self, operation):
        return subprocess.run([str(self.helper), operation], env=self.env, capture_output=True, text=True, timeout=10)

    def test_branch_transition_and_pins(self):
        r = self.run_helper('update')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read()['installed'], ['runtime/B', 'runtime/admin'])
        self.assertEqual(self.read()['pins'], ['runtime/admin'])
        self.assertTrue(self.read()['hidden'])
        calls = self.calls()
        self.assertLess(next(i for i,a in enumerate(calls) if '--enumerate' in a),
                        next(i for i,a in enumerate(calls) if a[0] == 'update'))
        self.assertIn('--no-enumerate', calls[-1])

    def test_required_eol_runtime_and_admin_pin_survive_cleanup(self):
        r = self.run_helper('cleanup')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read()['installed'], ['runtime/A', 'runtime/admin'])

    def test_stage_failures_restore(self):
        for failure, code in [('fail_update',22), ('fail_cleanup',23), ('fail_prepare',13)]:
            with self.subTest(failure=failure):
                self.save(**dict.fromkeys(['fail_update','fail_cleanup','fail_prepare'], False))
                self.save(**{failure:True})
                r = self.run_helper('update')
                self.assertEqual(r.returncode, code, r.stderr)
                self.assertTrue(self.read()['hidden'])
        self.assertNotIn('pin', [a[0] for a in self.calls()])

    def test_restore_failure_reported_and_original_failure_preserved(self):
        self.save(fail_restore=True)
        r = self.run_helper('update')
        self.assertEqual(r.returncode, 12)
        self.assertIn('FAILED to restore', r.stderr)
        self.save(fail_update=True)
        self.assertEqual(self.run_helper('update').returncode, 22)

    def test_absent_remote(self):
        self.save(exists=False)
        self.assertEqual(self.run_helper('update').returncode, 0)
        self.assertFalse(any(a[0] == 'remote-modify' for a in self.calls()))

    def test_bad_remote_rejected(self):
        for change in [dict(url='https://untrusted.invalid/'), dict(options=['disabled']),
                       dict(options=['no-gpg-verify']), dict(fail_list=True)]:
            with self.subTest(change=change):
                self.save(url='https://dl.flathub.org/repo/', options=[], fail_list=False)
                self.save(**change)
                self.log.unlink(missing_ok=True)
                self.assertNotEqual(self.run_helper('update').returncode, 0)
                self.assertFalse(any(a[0] == 'update' for a in self.calls()))

    def test_setup_creation_and_failure_restore(self):
        for exists, fail in itertools.product([False,True], repeat=2):
            with self.subTest(exists=exists, fail=fail):
                self.save(exists=exists, hidden=True, fail_setup=fail)
                self.assertEqual(self.run_helper('setup').returncode, 25 if fail else 0)
                self.assertTrue(self.read()['hidden'])

    def test_repair_failure_restore(self):
        self.save(fail_repair=True)
        self.assertEqual(self.run_helper('repair').returncode, 24)
        self.assertTrue(self.read()['hidden'])

    def start_held(self):
        self.save(hold=True)
        p = subprocess.Popen([str(self.helper),'update'], env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: p.kill() if p.poll() is None else None)
        deadline = time.monotonic() + 5
        while not (self.d / 'ready').exists():
            if time.monotonic() > deadline: self.fail('update did not reach barrier')
            time.sleep(.01)
        self.assertFalse(self.read()['hidden'])
        return p

    def test_catchable_signals_restore(self):
        for sig in [signal.SIGTERM, signal.SIGHUP, signal.SIGINT]:
            with self.subTest(signal=sig):
                (self.d / 'ready').unlink(missing_ok=True)
                p = self.start_held()
                p.send_signal(sig)
                self.assertEqual(p.wait(timeout=5), 128 + sig)
                self.assertTrue(self.read()['hidden'])

    def test_lock_serializes_setup_cleanup_repair_and_ensure(self):
        for operation in ['setup','cleanup','repair','ensure']:
            with self.subTest(operation=operation):
                (self.d / 'ready').unlink(missing_ok=True)
                (self.d / 'release').unlink(missing_ok=True)
                p = self.start_held()
                calls_before = self.calls()
                q = subprocess.Popen([str(self.helper),operation], env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.addCleanup(lambda q=q: q.kill() if q.poll() is None else None)
                time.sleep(.1)
                self.assertIsNone(q.poll())
                self.assertEqual(self.calls(), calls_before)
                (self.d / 'release').touch()
                self.assertEqual(p.wait(timeout=5), 0)
                self.assertEqual(q.wait(timeout=5), 0)
                self.assertTrue(self.read()['hidden'])

    def test_ensure_recovers_exposed_remote(self):
        self.save(hidden=False)
        self.assertEqual(self.run_helper('ensure').returncode, 0)
        self.assertTrue(self.read()['hidden'])
        self.assertFalse(any(a[0] in ['update','install','uninstall'] for a in self.calls()))

    def test_lock_permissions_do_not_change_flatpak_umask(self):
        r = subprocess.run(['/bin/bash', '-c', 'umask 022; exec "$1" update',
                            'test', str(self.helper)],
                           env=dict(self.env, FP_EXPECT_UMASK='022'),
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.d / 'lock').stat().st_mode & 0o777, 0o600)

    def test_missing_flatpak_fails(self):
        self.mock.unlink()
        self.assertEqual(self.run_helper('update').returncode, 127)

    def test_status_does_not_mutate(self):
        self.assertEqual(self.run_helper('status').returncode, 0)
        self.assertTrue(all(a[0] in ['remotes','list'] for a in self.calls()))

    def test_root_gate(self):
        # Run the actual gate, substituting only the required executable location.
        source = HELPER.read_text().replace('/usr/bin/flatpak', '/usr/bin/true')
        args = {}
        if os.geteuid() == 0:
            args.update(user=65534, group=65534, extra_groups=[])
        try:
            r = subprocess.run(['/bin/bash','-c',source,'helper','update'], capture_output=True, text=True, **args)
        except PermissionError:
            self.skipTest('container forbids dropping UID; run as an ordinary CI user to test root gate')
        self.assertEqual(r.returncode, 77, r.stderr)


class UserWrapper(unittest.TestCase):
    def test_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'flatpak'
            write_executable(p, '#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            cases = [(['install','APP'],True), (['update'],True), (['--verbose','install','APP'],True),
                     (['-v','update'],True), (['-vv','--ostree-verbose','update'],True),
                     (['list'],False), (['info','APP'],False), (['remotes'],False), ([],False)]
            for scope in [['--system'],['--user'],['-u'],['--installation=foo'],['--installation','foo']]:
                cases.extend([(scope + ['install','APP'],False), (['install'] + scope + ['APP'],False)])
            for args, inject in cases:
                with self.subTest(args=args):
                    script = '. "$1"; shift; flatpak "$@"'
                    r = subprocess.run(['/bin/bash','--noprofile','--norc','-ic',script,'test',str(WRAPPER),*args],
                                       env=dict(os.environ, PATH=td+':'+os.environ['PATH']), capture_output=True, text=True)
                    self.assertEqual(r.returncode,0,r.stderr)
                    self.assertEqual(json.loads(r.stdout), (['--user'] if inject else []) + args)


class Orchestration(unittest.TestCase):
    def test_system_matrix(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            write_executable(d/'sudo', '''#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$1" in
  /usr/libexec/current-flatpak-system-maintenance) exit "$FP_RESULT" ;;
  bootc) exit "$BOOTC_RESULT" ;;
  *) exit 99 ;;
esac
''')
            for fp, bootc in itertools.product([0,7],repeat=2):
                with self.subTest(flatpak=fp,bootc=bootc):
                    log = d/'calls'; log.write_text('')
                    r = subprocess.run(['/bin/bash'],input=recipe('update-system'),text=True,capture_output=True,
                        env=dict(os.environ,PATH=td+':'+os.environ['PATH'],CALL_LOG=str(log),FP_RESULT=str(fp),BOOTC_RESULT=str(bootc)))
                    self.assertEqual(r.returncode,int(bool(fp or bootc)))
                    self.assertEqual(len(log.read_text().splitlines()),2)
                    self.assertIn('System Flatpaks:',r.stdout)
                    self.assertIn('OS image:',r.stdout)

    def test_all_matrix(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            write_executable(d/'current', '''#!/bin/bash
printf '%s\\n' "$1" >> "$CALL_LOG"
case ",$FAILURES," in *,"$1",*) exit 8 ;; esac
''')
            categories = ['update-system','update-user','update-podman','update-firmware']
            for failures in itertools.product([False,True],repeat=4):
                log=d/'calls'; log.write_text('')
                r=subprocess.run(['/bin/bash'],input=recipe('update-all'),text=True,capture_output=True,
                    env=dict(os.environ,PATH=td+':'+os.environ['PATH'],CALL_LOG=str(log),
                             FAILURES=','.join(c for c,f in zip(categories,failures) if f)))
                self.assertEqual(r.returncode,int(any(failures)),r.stderr)
                self.assertEqual(log.read_text().splitlines(),categories)
                self.assertEqual(r.stdout.count('FAILED'),sum(failures))

    def test_recipe_syntax(self):
        for name in ['update-system','update-all','update-user','update-podman','update']:
            r=subprocess.run(['bash','-n'],input=recipe(name),text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr)


class Policy(unittest.TestCase):
    def test_policy(self):
        r=subprocess.run(['node',str(ROOT/'scripts/test-flatpak-policy.js'),str(POLICY)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
