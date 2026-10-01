#!/usr/bin/env python3
"""Exercise the real helper and offline systemctl; never contact host PID 1."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = REPO / "files/workstation/shared"
HELPER = PAYLOAD / "usr/libexec/current-workstation-dm-apply"
FIXTURES = Path(__file__).parent / "fixtures/workstation"
UNITS = ("gdm.service", "cosmic-greeter.service", "greetd.service")


class Reconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.system = self.root / "etc/systemd/system"
        shutil.copytree(PAYLOAD / "usr", self.root / "usr")
        for path in ("etc/systemd/system", "etc/gdm", "etc/greetd", "usr/bin",
                     "usr/lib/pam.d", "usr/share/wayland-sessions", "mock-bin"):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        for unit in UNITS + ("graphical.target",):
            shutil.copyfile(FIXTURES / unit, self.root / "usr/lib/systemd/system" / unit)
        for binary in ("gdm", "gnome-session", "greetd", "start-cosmic", "cosmic-comp",
                       "cosmic-greeter-start", "cosmic-greeter-daemon"):
            self.write("usr/bin/" + binary, "#!/bin/sh\nexit 0\n", executable=True)
        self.write("etc/gdm/custom.conf", "[daemon]\n")
        shutil.copyfile(REPO / "files/cosmic/shared/etc/greetd/cosmic-greeter.toml",
                        self.root / "etc/greetd/cosmic-greeter.toml")
        self.write("usr/lib/pam.d/cosmic-greeter", "auth optional pam_gnome_keyring.so\n")
        for desktop, binary in (("gnome", "gnome-session"), ("cosmic", "start-cosmic")):
            self.write(f"usr/share/wayland-sessions/{desktop}.desktop",
                       f"[Desktop Entry]\nName={desktop.upper()}\n"
                       f"Exec=/usr/bin/{binary}\nDesktopNames={desktop.upper()}\n")
        # Forward only explicit --root operations to the real systemctl. Any
        # accidental start/stop/reload or host operation is a test failure.
        self.write("mock-bin/systemctl", """#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "--root=$TEST_ROOT" ]] || { echo 'unsafe systemctl call' >&2; exit 90; }
[[ "$2" == --no-reload ]] || exit 91
case "$3" in unmask|enable|disable|set-default) ;; *) exit 92 ;; esac
printf '%s\\n' "$*" >> "$TEST_ROOT/systemctl-calls"
if [[ "$3" == "${TEST_FAIL:-}" ]]; then
  echo "injected $3 failure" >&2; exit 1
fi
"$TEST_SYSTEMCTL" "$@"
if [[ "$3" == enable && -n "${TEST_BAD_ALIAS:-}" ]]; then
  ln -sfn "$TEST_BAD_ALIAS" "$TEST_ROOT/etc/systemd/system/display-manager.service"
fi
""", executable=True)
        self.env = dict(os.environ, TEST_ROOT=str(self.root),
                        TEST_SYSTEMCTL=shutil.which("systemctl"),
                        PATH=f"{self.root / 'mock-bin'}:{os.environ['PATH']}")
        self.marker("gnome")

    def write(self, path, content, executable=False):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
        if executable:
            file.chmod(0o755)

    def marker(self, desktop):
        self.write("usr/share/current/workstation/desktop.env", f"CURRENT_DESKTOP={desktop}\n")

    def link(self, name, target):
        path = self.system / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        path.symlink_to(target)

    def run_helper(self, *args, success=True, code=None):
        script = code or 'source "$1"; root_dir="$2"; main "${@:3}"'
        result = subprocess.run(["bash", "-c", script, "test", str(HELPER),
                                 str(self.root), *map(str, args)],
                                env=self.env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stderr

    def state(self):
        result = {}
        for prefix in ("etc", "var"):
            for file in (self.root / prefix).rglob("*"):
                if file.is_symlink():
                    result[str(file.relative_to(self.root))] = os.readlink(file)
                elif file.is_file():
                    result[str(file.relative_to(self.root))] = file.read_bytes()
        return result

    def assert_owner(self, unit):
        self.assertEqual(os.readlink(self.system / "display-manager.service"),
                         "/usr/lib/systemd/system/" + unit)

    def test_gnome_selects_gdm(self):
        self.run_helper()
        self.assert_owner("gdm.service")

    def test_cosmic_selects_native_greeter_with_vendor_pam(self):
        self.marker("cosmic")
        self.run_helper()
        self.assert_owner("cosmic-greeter.service")
        self.assertFalse((self.root / "etc/pam.d/cosmic-greeter").exists())

    def test_selected_masks_are_removed(self):
        for desktop, unit in (("gnome", "gdm.service"), ("cosmic", "cosmic-greeter.service")):
            with self.subTest(desktop=desktop):
                self.marker(desktop)
                self.link(unit, "/dev/null")
                self.link("display-manager.service", "/dev/null")
                self.assertIn("stale mask", self.run_helper())
                self.assertFalse((self.system / unit).is_symlink())
                self.assert_owner(unit)

    def test_competitors_and_absent_package_links_are_disabled(self):
        for target in ("graphical.target", "multi-user.target"):
            for unit in ("cosmic-greeter.service", "greetd.service"):
                self.link(f"{target}.wants/{unit}", "/usr/lib/systemd/system/" + unit)
        (self.root / "usr/lib/systemd/system/greetd.service").unlink()
        self.run_helper()
        for target in ("graphical.target", "multi-user.target"):
            for unit in ("cosmic-greeter.service", "greetd.service"):
                self.assertFalse((self.system / f"{target}.wants/{unit}").is_symlink())

    def test_wrong_dangling_and_masked_aliases_are_repaired(self):
        for target in ("/usr/lib/systemd/system/cosmic-greeter.service", "/dev/null"):
            self.link("display-manager.service", target)
            self.run_helper()
            self.assert_owner("gdm.service")
        (self.root / "usr/lib/systemd/system/cosmic-greeter.service").unlink()
        self.link("display-manager.service", "/usr/lib/systemd/system/cosmic-greeter.service")
        self.run_helper()
        self.assert_owner("gdm.service")

    def test_alias_verification_rejects_wrong_dangling_and_masked(self):
        for target, message in (("/usr/lib/systemd/system/greetd.service", "wrong or masked"),
                                ("/etc/systemd/system/gdm.service", "dangling"),
                                ("/dev/null", "wrong or masked")):
            self.link("display-manager.service", target)
            log = self.run_helper(success=False, code='source "$1"; root_dir="$2"; validate_destination; verify_alias')
            self.assertIn(message, log)

    def test_missing_destination_preserves_previous_state(self):
        self.link("display-manager.service", "/usr/lib/systemd/system/cosmic-greeter.service")
        (self.root / "usr/lib/systemd/system/gdm.service").unlink()
        before = self.state()
        self.assertIn("missing destination unit", self.run_helper(success=False))
        self.assertEqual(before, self.state())

    def test_invalid_marker_preserves_state_and_is_not_executed(self):
        self.link("display-manager.service", "/usr/lib/systemd/system/gdm.service")
        for value in ("", "kde", f"$(touch {self.root}/executed)"):
            self.marker(value)
            before = self.state()
            self.assertIn("invalid CURRENT_DESKTOP", self.run_helper(success=False))
            self.assertEqual(before, self.state())
        self.assertFalse((self.root / "executed").exists())

    def test_missing_marker_and_config_are_diagnosed_before_cleanup(self):
        self.link("display-manager.service", "/usr/lib/systemd/system/gdm.service")
        (self.root / "usr/share/current/workstation/desktop.env").unlink()
        before = self.state()
        self.assertIn("marker is missing", self.run_helper(success=False))
        self.assertEqual(before, self.state())
        self.marker("cosmic")
        (self.root / "etc/greetd/cosmic-greeter.toml").unlink()
        before = self.state()
        self.assertIn("missing COSMIC configuration", self.run_helper(success=False))
        self.assertEqual(before, self.state())

    def test_invalid_config_and_unit_command_preserve_state(self):
        self.marker("cosmic")
        self.link("display-manager.service", "/usr/lib/systemd/system/gdm.service")
        file = self.root / "etc/greetd/cosmic-greeter.toml"
        original = file.read_text()
        file.write_text(original.replace('command = "cosmic-greeter-start"', 'command = "gnome-session"'))
        before = self.state()
        self.assertIn("invalid COSMIC", self.run_helper(success=False))
        self.assertEqual(before, self.state())
        file.write_text(original)
        unit = self.root / "usr/lib/systemd/system/cosmic-greeter.service"
        unit.write_text(unit.read_text().replace("/etc/greetd/cosmic-greeter.toml", "/etc/greetd/config.toml"))
        self.assertIn("unexpected COSMIC ExecStart", self.run_helper(success=False))

    def test_failed_enable_and_bad_alias_restore_alias_and_mask(self):
        self.marker("cosmic")
        self.link("cosmic-greeter.service", "/dev/null")
        self.link("display-manager.service", "/usr/lib/systemd/system/gdm.service")
        for settings in ({"TEST_FAIL": "enable"}, {"TEST_BAD_ALIAS": "/dev/null"},
                         {"TEST_BAD_ALIAS": "/usr/lib/systemd/system/gdm.service"}):
            with self.subTest(settings=settings):
                self.env.update(settings)
                before = self.state()
                log = self.run_helper(success=False)
                self.assertIn("restoring previous alias", log)
                self.assertEqual(before, self.state())
                for key in settings:
                    self.env.pop(key)

    def test_disable_and_default_target_failures_are_visible(self):
        for operation in ("disable", "set-default"):
            self.env["TEST_FAIL"] = operation
            self.assertIn(f"injected {operation} failure", self.run_helper(success=False))

    def test_repeated_switches_are_idempotent_and_preserve_preferences(self):
        self.write("var/home/operator/.config/preference", "keep me\n")
        self.write("var/lib/AccountsService/users/operator", "[User]\nSession=gnome\n")
        self.write("var/lib/cosmic-greeter/.config/cosmic/com.system76.CosmicGreeter/v1/users", "remember COSMIC\n")
        for desktop, unit in (("gnome", "gdm.service"), ("cosmic", "cosmic-greeter.service"),
                              ("gnome", "gdm.service"), ("cosmic", "cosmic-greeter.service")):
            self.marker(desktop)
            self.link(unit, "/dev/null")
            self.run_helper()
            self.assert_owner(unit)
            before = self.state()
            self.run_helper()
            self.assertEqual(before, self.state())
        self.assertEqual((self.root / "var/home/operator/.config/preference").read_text(), "keep me\n")
        self.assertIn("Session=gnome", (self.root / "var/lib/AccountsService/users/operator").read_text())

    def test_opt_out_preserves_everything_and_generates_nothing(self):
        self.write("etc/current/workstation-dm-unmanaged", "")
        self.link("gdm.service", "/dev/null")
        self.link("display-manager.service", "/usr/lib/systemd/system/greetd.service")
        before = self.state()
        self.assertIn("administrator owns", self.run_helper())
        early = self.root / "early"
        self.run_helper("--generate", self.root / "normal", early, self.root / "late")
        self.assertFalse(early.exists())
        self.assertEqual(before, self.state())

    def test_unrelated_administrator_units_are_preserved(self):
        self.link("unrelated.service", "/dev/null")
        self.run_helper()
        self.assertEqual(os.readlink(self.system / "unrelated.service"), "/dev/null")
        self.link("display-manager.service", "/usr/lib/systemd/system/sddm.service")
        before = self.state()
        self.assertIn("administrator alias", self.run_helper(success=False))
        self.assertEqual(before, self.state())
        (self.system / "display-manager.service").unlink()
        self.write("etc/systemd/system/gdm.service", "[Service]\nExecStart=/custom\n")
        before = self.state()
        self.assertIn("administrator unit override", self.run_helper(success=False))
        self.assertEqual(before, self.state())

    def test_generator_selects_before_retained_state_and_gates_start(self):
        for desktop, unit in (("gnome", "gdm.service"), ("cosmic", "cosmic-greeter.service")):
            self.marker(desktop)
            self.link(unit, "/dev/null")
            self.link("display-manager.service", "/usr/lib/systemd/system/greetd.service")
            before = self.state()
            early = self.root / f"early-{desktop}"
            self.run_helper("--generate", self.root / "normal", early, self.root / "late")
            self.assertEqual(before, self.state())
            self.assertEqual(os.readlink(early / "display-manager.service"),
                             str(self.root / "usr/lib/systemd/system" / unit))
            for competitor in set(UNITS) - {unit}:
                self.assertEqual(os.readlink(early / competitor), "/dev/null")
            dropin = (early / (unit + ".d/50-current-workstation.conf")).read_text()
            self.assertIn("Requires=current-workstation-dm-apply.service", dropin)
            self.assertIn("After=current-workstation-dm-apply.service", dropin)

    def test_build_checks_validate_expected_family_and_wiring(self):
        for desktop in ("gnome", "cosmic"):
            self.marker(desktop)
            before = self.state()
            self.run_helper("--check", desktop)
            self.assertEqual(before, self.state())
            self.assertIn("expected desktop", self.run_helper("--check", "other", success=False))
        service = self.root / "usr/lib/systemd/system/current-workstation-dm-apply.service"
        service.write_text(service.read_text().replace("RemainAfterExit=yes", "RemainAfterExit=no"))
        self.assertIn("ordering contract", self.run_helper("--check", "cosmic", success=False))

    def test_real_systemd_dependency_graph_has_no_cycle(self):
        # Keep native DM/graphical units, with minimal dependency services for an
        # offline root. systemd-analyze performs the actual transaction check.
        for name in ("multi-user.target", "basic.target", "sysinit.target", "local-fs.target",
                     "shutdown.target", "network.target", "systemd-user-sessions.service",
                     "plymouth-quit-wait.service", "plymouth-quit.service", "plymouth-start.service",
                     "getty@.service", "kmscon@.service", "ksmcon@.service", "rc-local.service",
                     "cosmic-greeter-daemon.service"):
            content = "[Unit]\nDescription=Fixture dependency\n"
            if name.endswith(".service"):
                content += "[Service]\nExecStart=/usr/bin/gdm\n"
            self.write("usr/lib/systemd/system/" + name, content)
        self.link("multi-user.target.wants/current-workstation-dm-apply.service",
                  "/usr/lib/systemd/system/current-workstation-dm-apply.service")
        self.write("etc/os-release", "ID=fedora\n")
        for desktop in ("gnome", "cosmic"):
            self.marker(desktop)
            early = self.root / f"verify-{desktop}"
            self.run_helper("--generate", self.root / "normal", early, self.root / "late")
            # --root interprets each absolute load directory within the fixture.
            env = dict(os.environ, SYSTEMD_UNIT_PATH=f"/{early.name}:/etc/systemd/system:/usr/lib/systemd/system")
            result = subprocess.run(["systemd-analyze", "--root=" + str(self.root),
                                     "--generators=no", "--man=no", "verify", "graphical.target"],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("cycle", result.stderr.lower())
            # Prove this verification actually traverses the selected manager's
            # Requires/After edge, rather than just parsing graphical.target.
            service = self.root / "usr/lib/systemd/system/current-workstation-dm-apply.service"
            original = service.read_text()
            service.write_text(original.replace("After=local-fs.target", "After=graphical.target"))
            broken = subprocess.run(["systemd-analyze", "--root=" + str(self.root),
                                     "--generators=no", "--man=no", "verify", "graphical.target"],
                                    env=env, text=True, capture_output=True)
            self.assertIn("cycle", broken.stderr.lower())
            service.write_text(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
