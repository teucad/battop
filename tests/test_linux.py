"""Linux platform tests. They use fake /sys trees, a fake command runner and temp directories,
so they run on any OS and can never touch the real system."""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from battop.platforms.linux import commands, desktop, helper, helper_client, setup, sysfs
from battop.platforms.linux.actions import app_priority, bluetooth, brightness, cpu_limit, power_profile, timeouts


def write(path: Path, text) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding="utf-8")


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class SysfsTests(TempDirTestCase):
    def supply(self, name, **files):
        for key, value in files.items():
            write(self.root / "class" / "power_supply" / name / key, value)

    def test_on_ac_and_charging(self):
        self.supply("AC", type="Mains", online=1)
        self.supply("BAT0", type="Battery", status="Charging", capacity=80)
        status = sysfs.read_power_status(self.root)
        self.assertEqual((status.on_battery, status.has_battery, status.percent, status.charging), (False, True, 80, True))
        self.assertIsNone(status.seconds_left)

    def test_on_battery_with_time_left_from_energy_and_power(self):
        self.supply("AC", type="Mains", online=0)
        self.supply("BAT0", type="Battery", status="Discharging", capacity=64, energy_now=40_000_000, power_now=10_000_000)
        status = sysfs.read_power_status(self.root)
        self.assertTrue(status.on_battery)
        self.assertEqual(status.seconds_left, 4 * 3600)

    def test_time_left_falls_back_to_charge_and_current(self):
        self.supply("AC", type="Mains", online=0)
        self.supply("BAT0", type="Battery", status="Discharging", capacity=50, charge_now=3_000_000, current_now=1_500_000)
        self.assertEqual(sysfs.read_power_status(self.root).seconds_left, 2 * 3600)

    def test_zero_power_draw_does_not_divide_by_zero(self):
        self.supply("AC", type="Mains", online=0)
        self.supply("BAT0", type="Battery", status="Discharging", capacity=50, energy_now=1, power_now=0)
        self.assertIsNone(sysfs.read_power_status(self.root).seconds_left)

    def test_usb_c_charger_counts(self):
        self.supply("ucsi-source-psy-USBC000-001", type="USB", online=1)
        self.supply("BAT0", type="Battery", status="Charging", capacity=40)
        self.assertFalse(sysfs.read_power_status(self.root).on_battery)

    def test_no_battery(self):
        self.supply("AC", type="Mains", online=1)
        status = sysfs.read_power_status(self.root)
        self.assertEqual((status.has_battery, status.on_battery, status.percent), (False, False, None))

    def test_missing_sysfs_is_not_an_error(self):
        self.assertFalse(sysfs.read_power_status(self.root / "nowhere").has_battery)

    def test_peripheral_batteries_are_ignored(self):
        self.supply("AC", type="Mains", online=1)
        self.supply("hid-mouse", type="Battery", scope="Device", status="Discharging", capacity=5)
        self.assertFalse(sysfs.read_power_status(self.root).has_battery)

    def test_without_any_charger_node_the_batterys_own_status_decides(self):
        self.supply("BAT0", type="Battery", status="Discharging", capacity=70)
        self.assertTrue(sysfs.read_power_status(self.root).on_battery)
        self.supply("BAT0", status="Full")
        self.assertFalse(sysfs.read_power_status(self.root).on_battery)

    def test_capacity_is_clamped_and_garbage_is_tolerated(self):
        self.supply("AC", type="Mains", online=0)
        self.supply("BAT0", type="Battery", status="Discharging", capacity=250)
        self.assertEqual(sysfs.read_power_status(self.root).percent, 100)
        self.supply("BAT0", capacity="n/a")
        self.assertIsNone(sysfs.read_power_status(self.root).percent)

    def test_root_can_be_overridden_by_environment(self):
        self.supply("BAT0", type="Battery", status="Discharging", capacity=33)
        with mock.patch.dict(os.environ, {"BATTOP_SYSFS_ROOT": str(self.root)}):
            self.assertEqual(sysfs.read_power_status().percent, 33)


class FakeRunner:
    """Replaces commands.run: records calls and answers from a handler."""

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def __call__(self, command, timeout=10):
        self.calls.append(command)
        return self.handler(command)


class PowerProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = "balanced"

        def handler(command):
            if command[:2] == ["powerprofilesctl", "get"]:
                return self.profile
            self.profile = command[2]
            return ""

        patcher = mock.patch.object(commands, "run", FakeRunner(handler))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.action = power_profile.PowerProfileAction()

    def test_switches_to_power_saver_and_back(self):
        saved = self.action.apply(None)
        self.assertEqual((saved, self.profile), ({"previous": "balanced"}, "power-saver"))
        self.action.restore(saved)
        self.assertEqual(self.profile, "balanced")

    def test_already_power_saver_is_left_alone(self):
        self.profile = "power-saver"
        self.assertIsNone(self.action.apply(None))

    def test_restore_respects_a_profile_changed_by_the_desktop(self):
        saved = self.action.apply(None)
        self.profile = "performance"
        self.action.restore(saved)
        self.assertEqual(self.profile, "performance")


class BacklightTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.backlight("intel_backlight", "raw", current=96000, maximum=96000)
        env = mock.patch.dict(os.environ, {"BATTOP_SYSFS_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

        def handler(command):  # What logind does: store the value.
            assert command[0] == "busctl" and command[-4:-2] == ["ssu", "backlight"], command
            write(self.root / "class" / "backlight" / command[-2] / "brightness", command[-1])
            return ""

        patcher = mock.patch.object(commands, "run", FakeRunner(handler))
        self.runner = patcher.start()
        self.addCleanup(patcher.stop)
        self.action = brightness.BacklightAction()
        self.settings = SimpleNamespace(brightness_percent=40)

    def backlight(self, name, kind, current, maximum):
        base = self.root / "class" / "backlight" / name
        write(base / "type", kind)
        write(base / "brightness", current)
        write(base / "max_brightness", maximum)

    def now(self):
        return int((self.root / "class" / "backlight" / "intel_backlight" / "brightness").read_text())

    def test_prefers_firmware_over_raw_and_ignores_unusable_devices(self):
        self.backlight("acpi_video0", "firmware", 50, 100)
        self.backlight("dead", "firmware", 0, 0)
        self.assertEqual(brightness.find_backlight(), "acpi_video0")

    def test_no_backlight(self):
        self.assertIsNone(brightness.find_backlight(self.root / "nowhere"))

    def test_dims_then_restores(self):
        saved = self.action.apply(self.settings)
        self.assertEqual(self.now(), 38400)  # 40% of 96000
        self.assertEqual(saved, {"device": "intel_backlight", "previous": 96000, "set_to": 38400})
        self.action.restore(saved)
        self.assertEqual(self.now(), 96000)

    def test_only_ever_dims(self):
        write(self.root / "class/backlight/intel_backlight/brightness", 20000)  # Already ~21%.
        self.assertIsNone(self.action.apply(self.settings))
        self.assertEqual(self.runner.calls, [])

    def test_never_dims_to_zero(self):
        self.action.apply(SimpleNamespace(brightness_percent=0))
        self.assertGreaterEqual(self.now(), 1)

    def test_restore_leaves_a_value_the_user_changed(self):
        saved = self.action.apply(self.settings)
        write(self.root / "class/backlight/intel_backlight/brightness", 50000)
        self.action.restore(saved)
        self.assertEqual(self.now(), 50000)

    def test_missing_device_does_nothing(self):
        for child in (self.root / "class" / "backlight" / "intel_backlight").iterdir():
            child.unlink()
        (self.root / "class" / "backlight" / "intel_backlight").rmdir()
        self.assertIsNone(self.action.apply(self.settings))


class GnomeTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.store = {
            ("org.gnome.desktop.session", "idle-delay"): "uint32 300",
            ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout"): "1800",
            ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type"): "'suspend'",
        }

        def handler(command):
            assert command[0] == "gsettings"
            if command[1] == "get":
                return self.store[(command[2], command[3])]
            self.store[(command[2], command[3])] = command[4]
            return ""

        patcher = mock.patch.object(commands, "run", FakeRunner(handler))
        self.runner = patcher.start()
        self.addCleanup(patcher.stop)
        self.action = timeouts.GnomeTimeoutsAction()
        self.settings = SimpleNamespace(screen_off_minutes=3, sleep_minutes=10)
        self.screen, self.sleep = timeouts.SCREEN, timeouts.SLEEP

    def test_shortens_both_and_restores_them(self):
        saved = self.action.apply(self.settings)
        self.assertEqual((self.store[self.screen], self.store[self.sleep]), ("180", "600"))
        self.action.restore(saved)
        self.assertEqual((self.store[self.screen], self.store[self.sleep]), ("300", "1800"))

    def test_only_ever_shortens(self):
        self.store[self.screen] = "uint32 60"
        self.store[self.sleep] = "300"
        self.assertIsNone(self.action.apply(self.settings))

    def test_zero_means_never_and_is_shortened(self):
        self.store[self.screen] = "uint32 0"
        saved = self.action.apply(self.settings)
        self.assertEqual(self.store[self.screen], "180")
        self.assertIn("org.gnome.desktop.session idle-delay", saved["changed"])

    def test_sleep_is_untouched_when_the_sleep_action_is_disabled(self):
        self.store[("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type")] = "'nothing'"
        self.action.apply(self.settings)
        self.assertEqual(self.store[self.sleep], "1800")

    def test_restore_leaves_values_the_user_changed_meanwhile(self):
        saved = self.action.apply(self.settings)
        self.store[self.screen] = "42"
        self.action.restore(saved)
        self.assertEqual(self.store[self.screen], "42")

    def test_availability_follows_gsettings(self):
        self.assertTrue(timeouts.available())
        with mock.patch.object(commands, "run", side_effect=OSError("no schema")):
            self.assertFalse(timeouts.available())


class BluetoothTests(unittest.TestCase):
    def setUp(self):
        self.powered, self.connected, self.log = True, 0, []

        def handler(command):
            if command[1] == "show":
                return "Controller AA:BB\n\tPowered: " + ("yes" if self.powered else "no")
            if command[1] == "devices":
                return "\n".join(f"Device 11:22:33:44:55:{i:02d} Thing {i}" for i in range(self.connected))
            self.powered = command[2] == "on"
            self.log.append(command[2])
            return ""

        patcher = mock.patch.object(commands, "run", FakeRunner(handler))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.action = bluetooth.BluetoothAction()

    def test_turns_off_only_when_nothing_is_connected(self):
        self.assertEqual(self.action.apply(None), {"was_on": True})
        self.assertEqual(self.log, ["off"])

    def test_stays_on_with_connected_devices(self):
        self.connected = 2
        self.assertIsNone(self.action.apply(None))
        self.assertEqual(self.log, [])

    def test_already_off_is_left_alone(self):
        self.powered = False
        self.assertIsNone(self.action.apply(None))

    def test_no_adapter(self):
        with mock.patch.object(commands, "run", return_value="No default controller available"):
            self.assertIsNone(bluetooth.read_status())

    def test_restore_turns_it_back_on_only_if_still_off(self):
        self.action.apply(None)
        self.action.restore({"was_on": True})
        self.assertEqual(self.log, ["off", "on"])
        self.action.restore({"was_on": True})
        self.assertEqual(self.log, ["off", "on"])


class HelperTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        for name, value in (("SYSFS", str(self.root / "sys")), ("PROC", str(self.root / "proc"))):
            patcher = mock.patch.object(helper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def cpu(self, *rest):
        return self.root / "sys" / "devices" / "system" / "cpu" / Path(*rest)

    def intel(self, value=100):
        write(self.cpu("intel_pstate", "max_perf_pct"), value)

    def cpufreq(self, index, current, highest=4_000_000):
        write(self.cpu(f"cpu{index}", "cpufreq", "scaling_max_freq"), current)
        write(self.cpu(f"cpu{index}", "cpufreq", "cpuinfo_max_freq"), highest)

    def limit(self, index=0):
        return int(self.cpu(f"cpu{index}", "cpufreq", "scaling_max_freq").read_text())

    # --- processor limit -----------------------------------------------------------

    def test_intel_pstate_is_lowered_and_restored(self):
        self.intel(100)
        answer = helper.set_cpu_max(80)
        self.assertEqual(answer, {"changed": True, "state": {"mode": "intel_pstate", "value": 100}})
        self.assertEqual(self.cpu("intel_pstate", "max_perf_pct").read_text(), "80")
        helper.restore_cpu(json.dumps(answer["state"]))
        self.assertEqual(self.cpu("intel_pstate", "max_perf_pct").read_text(), "100")

    def test_a_stricter_existing_limit_is_never_loosened(self):
        self.intel(50)
        self.assertEqual(helper.set_cpu_max(80), {"changed": False})
        self.assertEqual(self.cpu("intel_pstate", "max_perf_pct").read_text(), "50")

    def test_cpufreq_fallback_is_lowered_and_restored(self):
        self.cpufreq(0, 4_000_000)
        self.cpufreq(1, 4_000_000)
        self.cpufreq(2, 1_000_000)  # Already below 80%: untouched.
        answer = helper.set_cpu_max(80)
        self.assertEqual((self.limit(0), self.limit(1), self.limit(2)), (3_200_000, 3_200_000, 1_000_000))
        self.assertEqual(sorted(answer["state"]["value"]), ["cpu0", "cpu1"])
        helper.restore_cpu(answer["state"])
        self.assertEqual((self.limit(0), self.limit(1)), (4_000_000, 4_000_000))

    def test_no_cpu_control_at_all(self):
        self.assertEqual(helper.set_cpu_max(80), {"changed": False})

    def test_percent_is_validated(self):
        self.intel()
        for bad in ("29", "101", "abc", "", "80; rm -rf /", "-5", True):
            with self.assertRaises(helper.HelperError, msg=repr(bad)):
                helper.set_cpu_max(bad)

    def test_restore_rejects_anything_unexpected(self):
        self.intel()
        self.cpufreq(0, 1000)
        for bad in (
            "not json", "[]", {}, {"mode": "other", "value": 1},
            {"mode": "intel_pstate", "value": 0}, {"mode": "intel_pstate", "value": "x"},
            {"mode": "cpufreq", "value": {}}, {"mode": "cpufreq", "value": 5},
            {"mode": "cpufreq", "value": {"cpu0/../../../etc/passwd": 1000}},
            {"mode": "cpufreq", "value": {"../cpu0": 1000}},
            {"mode": "cpufreq", "value": {"cpu0": 10**12}},
            {"mode": "cpufreq", "value": {"cpu0": True}},
        ):
            with self.assertRaises(helper.HelperError, msg=repr(bad)):
                helper.restore_cpu(bad)
        self.assertEqual(self.limit(0), 1000, "nothing may be written for a rejected request")

    def test_a_bad_entry_prevents_all_writes(self):
        self.cpufreq(0, 1000)
        with self.assertRaises(helper.HelperError):
            helper.restore_cpu({"mode": "cpufreq", "value": {"cpu0": 2000, "bogus": 1}})
        self.assertEqual(self.limit(0), 1000)

    # --- renice ----------------------------------------------------------------------

    def process(self, pid, uid):
        write(self.root / "proc" / str(pid) / "status", f"Name:\tx\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")

    def test_renices_the_callers_own_process(self):
        self.process(4242, 1000)
        with mock.patch.object(os, "setpriority", create=True) as setpriority, \
             mock.patch.object(os, "PRIO_PROCESS", 0, create=True):
            self.assertEqual(helper.renice("4242", "0", 1000), {"reniced": True})
        setpriority.assert_called_once_with(0, 4242, 0)

    def test_refuses_other_peoples_processes_and_bad_arguments(self):
        self.process(4242, 0)  # Owned by root.
        self.process(77, 1000)
        with mock.patch.object(os, "setpriority", create=True) as setpriority, \
             mock.patch.object(os, "PRIO_PROCESS", 0, create=True):
            cases = [
                ("4242", "5", 1000),   # Not theirs.
                ("77", "-5", 1000),    # Negative nice would speed it up.
                ("77", "20", 1000),
                ("1", "5", 1000),      # init.
                ("0", "5", 1000),
                ("77; id", "5", 1000),
                ("99999", "5", 1000),  # No such process.
                ("77", "5", None),     # Not run through pkexec.
            ]
            for pid, nice, uid in cases:
                with self.assertRaises(helper.HelperError, msg=(pid, nice, uid)):
                    helper.renice(pid, nice, uid)
        setpriority.assert_not_called()

    # --- command line ----------------------------------------------------------------

    def test_only_the_three_operations_exist(self):
        for argv in ([], ["rm", "-rf", "/"], ["set-cpu-max"], ["set-cpu-max", "80", "extra"], ["renice", "1"]):
            with self.assertRaises(helper.HelperError, msg=argv):
                helper.run(argv, 1000)

    def test_main_prints_json_and_reports_errors_with_exit_codes(self):
        self.intel()
        with mock.patch("builtins.print") as printed:
            self.assertEqual(helper.main(["set-cpu-max", "70"], {"PKEXEC_UID": "1000"}), 0)
        self.assertEqual(json.loads(printed.call_args[0][0])["changed"], True)
        with mock.patch("builtins.print"):
            self.assertEqual(helper.main(["set-cpu-max", "5"], {}), 2)
            self.assertEqual(helper.main(["renice", "77", "5"], {"PKEXEC_UID": "not-a-number"}), 2)

    def test_the_helper_is_standard_library_only(self):
        import ast

        tree = ast.parse(Path(helper.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertLessEqual(imported, {"json", "os", "re", "sys"})


class SetupTests(TempDirTestCase):
    def test_install_and_remove(self):
        helper_path, policy_path = self.root / "libexec" / "battop-helper", self.root / "polkit" / "x.policy"
        setup.install(helper_path, policy_path)
        self.assertEqual(helper_path.read_bytes(), Path(helper.__file__).read_bytes())
        self.assertIn(b"org.battop.helper", policy_path.read_bytes())
        if os.name == "posix":
            self.assertEqual(helper_path.stat().st_mode & 0o777, 0o755)
            self.assertEqual(policy_path.stat().st_mode & 0o777, 0o644)
        self.assertEqual([p.name for p in helper_path.parent.iterdir()], ["battop-helper"], "no temp files left")
        setup.remove(helper_path, policy_path)
        setup.remove(helper_path, policy_path)  # Removing twice is fine.
        self.assertFalse(helper_path.exists() or policy_path.exists())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "running as root")
    def test_refuses_to_run_without_root(self):
        with mock.patch("builtins.print"):
            self.assertEqual(setup.main(["install"]), 1)
            self.assertEqual(setup.main(["nonsense"]), 2)

    def test_setup_has_no_imports_from_the_battop_package(self):
        import ast

        tree = ast.parse(Path(setup.__file__).read_text(encoding="utf-8"))
        relative = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.level or "battop" in (n.module or ""))]
        self.assertEqual(relative, [], "pkexec runs setup.py as a plain script")

    def test_policy_file_matches_the_installed_helper_path(self):
        policy = ET.parse(Path(setup.__file__).with_name("org.battop.helper.policy")).getroot()
        action = policy.find("action")
        self.assertEqual(action.get("id"), "org.battop.helper")
        defaults = {child.tag: child.text for child in action.find("defaults")}
        self.assertEqual(defaults, {"allow_any": "no", "allow_inactive": "no", "allow_active": "yes"})
        annotations = {a.get("key"): a.text for a in action.findall("annotate")}
        self.assertEqual(annotations["org.freedesktop.policykit.exec.path"], setup.HELPER_PATH)
        self.assertEqual(helper_client.HELPER_PATH, setup.HELPER_PATH)

    def test_client_availability_needs_helper_policy_and_pkexec(self):
        with mock.patch.object(os, "access", return_value=True), \
             mock.patch.object(os.path, "exists", return_value=True), \
             mock.patch.object(commands, "available", return_value=True):
            self.assertTrue(helper_client.available())
            with mock.patch.object(commands, "available", return_value=False):
                self.assertFalse(helper_client.available())
            with mock.patch.object(os.path, "exists", return_value=False):
                self.assertFalse(helper_client.available())

    def test_install_reports_cancel_and_failure(self):
        for code, text in ((126, "cancelled"), (127, "cancelled"), (1, "boom")):
            result = SimpleNamespace(returncode=code, stderr="boom")
            with mock.patch.object(commands, "run_raw", return_value=result):
                with self.assertRaises(OSError) as caught:
                    helper_client.install()
            self.assertIn(text, str(caught.exception).lower())
        with mock.patch.object(commands, "run_raw", return_value=SimpleNamespace(returncode=0, stderr="")):
            helper_client.install()


class HelperBackedActionTests(unittest.TestCase):
    def test_cpu_limit_uses_the_helper_and_restores_what_it_reported(self):
        calls = []

        def call(*args):
            calls.append(args)
            return {"changed": True, "state": {"mode": "intel_pstate", "value": 100}}

        with mock.patch.object(helper_client, "available", return_value=True), \
             mock.patch.object(helper_client, "call", call):
            action = cpu_limit.CpuLimitAction()
            saved = action.apply(SimpleNamespace(cpu_max_percent=80))
            action.restore(saved)
        self.assertEqual(calls[0], ("set-cpu-max", "80"))
        self.assertEqual(calls[1][0], "restore-cpu")
        self.assertEqual(json.loads(calls[1][1]), {"mode": "intel_pstate", "value": 100})

    def test_cpu_limit_is_skipped_without_the_helper_or_when_already_low(self):
        action = cpu_limit.CpuLimitAction()
        with mock.patch.object(helper_client, "available", return_value=False), \
             mock.patch.object(helper_client, "call") as call:
            self.assertIsNone(action.apply(SimpleNamespace(cpu_max_percent=80)))
        call.assert_not_called()
        with mock.patch.object(helper_client, "available", return_value=True), \
             mock.patch.object(helper_client, "call", return_value={"changed": False}):
            self.assertIsNone(action.apply(SimpleNamespace(cpu_max_percent=80)))


class AppPriorityTests(unittest.TestCase):
    def setUp(self):
        self.nice = {100: 0, 101: 0, 102: 12}
        self.procs = [(100, "Firefox", 1000), (101, "discord", 1000), (102, "steam", 1000), (103, "firefox", 999)]
        self.calls = []
        self.helper = mock.Mock(side_effect=lambda *args: self.calls.append(args) or {"reniced": True})

        def setpriority(which, pid, value):
            self.nice[pid] = value

        for patcher in (
            mock.patch.object(app_priority.processes, "iter_processes", lambda: iter(self.procs)),
            mock.patch.object(os, "getuid", lambda: 1000, create=True),
            mock.patch.object(os, "PRIO_PROCESS", 0, create=True),
            mock.patch.object(os, "getpriority", lambda which, pid: self.nice[pid], create=True),
            mock.patch.object(os, "setpriority", setpriority, create=True),
            mock.patch.object(app_priority.helper_client, "available", return_value=True),
            mock.patch.object(app_priority.helper_client, "call", self.helper),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.action = app_priority.AppPriorityAction()
        self.settings = SimpleNamespace(efficiency_apps=("firefox", "steam"))

    def test_lowers_matching_apps_of_the_current_user_only(self):
        saved = self.action.apply(self.settings)
        self.assertEqual(self.nice[100], 10)
        self.assertEqual(self.nice[101], 0, "not in the list")
        self.assertEqual(saved["processes"]["100"], {"name": "Firefox", "nice": 0})
        self.assertIsNone(saved["processes"]["102"], "already lower than the target: nothing to undo")
        self.assertNotIn("103", saved["processes"], "another user's process")

    def test_refresh_catches_apps_started_later_and_restore_renices_them_back(self):
        saved = self.action.apply(self.settings)
        self.procs.append((200, "steam", 1000))
        self.nice[200] = 5
        saved = self.action.refresh(self.settings, saved)
        self.assertEqual(self.nice[200], 10)
        self.action.restore(saved)
        self.assertIn(("renice", "100", "0"), self.calls)
        self.assertIn(("renice", "200", "5"), self.calls)
        self.assertNotIn(("renice", "102", "12"), self.calls)

    def test_restore_skips_apps_that_ended_or_pids_that_were_recycled(self):
        saved = self.action.apply(self.settings)
        self.procs[0] = (100, "something-else", 1000)  # Same pid, different program.
        self.action.restore(saved)
        self.assertEqual(self.calls, [])

    def test_nothing_happens_without_the_helper(self):
        with mock.patch.object(app_priority.helper_client, "available", return_value=False):
            self.assertIsNone(self.action.apply(self.settings))
        self.assertEqual(self.nice[100], 0)


class DesktopTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config"), "XDG_DATA_HOME": str(self.root / "data")})
        env.start()
        self.addCleanup(env.stop)

    def test_autostart_can_be_enabled_and_disabled(self):
        self.assertFalse(desktop.autostart_enabled())
        desktop.set_autostart(True)
        text = desktop.autostart_path().read_text(encoding="utf-8")
        self.assertTrue(desktop.autostart_enabled())
        self.assertIn("--startup", text)
        self.assertIn("-m battop", text)
        self.assertIn("X-GNOME-Autostart-enabled=true", text)
        desktop.set_autostart(False)
        desktop.set_autostart(False)  # Idempotent.
        self.assertFalse(desktop.autostart_enabled())

    def test_exec_arguments_with_spaces_are_quoted(self):
        self.assertEqual(desktop._quote("/usr/bin/python3"), "/usr/bin/python3")
        self.assertEqual(desktop._quote("/home/a b/python"), '"/home/a b/python"')
        self.assertEqual(desktop._quote('say "hi" $HOME'), r'"say \"hi\" \$HOME"')

    def test_menu_entry_and_icon_are_installed_and_removed(self):
        desktop.install_desktop_entry()
        self.assertTrue(desktop.icon_path().exists())
        entry = desktop.menu_entry_path().read_text(encoding="utf-8")
        self.assertIn("Name=Battop", entry)
        self.assertNotIn("--startup", entry)
        desktop.set_autostart(True)
        self.assertEqual(desktop.remove_entries(), [])
        self.assertFalse(any(p.exists() for p in (desktop.icon_path(), desktop.menu_entry_path(), desktop.autostart_path())))
        self.assertEqual(desktop.remove_entries(), [])


class ProcessTests(TempDirTestCase):
    def test_lists_processes_and_skips_non_numeric_entries(self):
        from battop.platforms.linux import processes

        write(self.root / "123" / "comm", "firefox\n")
        write(self.root / "456" / "comm", "Xorg\n")
        write(self.root / "self" / "comm", "ignored")
        found = {pid: name for pid, name, _uid in processes.iter_processes(self.root)}
        self.assertEqual(found, {123: "firefox", 456: "Xorg"})
        self.assertEqual(processes.running_process_names(self.root), ["firefox", "xorg"])


class EventWatcherTests(unittest.TestCase):
    def test_a_watched_commands_lines_reach_the_callback(self):
        import threading

        from battop.platforms.linux import events

        seen = threading.Event()
        watcher = events._LineWatcher([sys.executable, "-c", "print('power_supply change')"], lambda line: seen.set())
        self.assertTrue(watcher.start())
        self.assertTrue(seen.wait(10))
        watcher.stop()

    def test_a_missing_program_just_means_polling(self):
        from battop.platforms.linux import events

        self.assertFalse(events._LineWatcher(["definitely-not-installed-xyz"], lambda line: None).start())


@unittest.skipUnless(sys.platform.startswith("linux"), "uses Linux abstract unix sockets")
class SingleInstanceTests(unittest.TestCase):
    def test_second_launch_is_detected_and_can_ask_the_first_to_show(self):
        import threading

        from battop.platforms.linux import single_instance

        self.addCleanup(setattr, single_instance, "_socket", None)
        asked = threading.Event()
        with mock.patch.object(single_instance, "_address", lambda: f"\0battop-test-{os.getpid()}"):
            self.assertTrue(single_instance.acquire())
            stop = single_instance.serve(asked.set)
            self.addCleanup(stop)
            self.assertFalse(single_instance.acquire(), "a second instance must not get the lock")
            self.assertTrue(single_instance.signal_existing())
            self.assertTrue(asked.wait(5))

    def test_signalling_when_nobody_is_running_fails_cleanly(self):
        from battop.platforms.linux import single_instance

        with mock.patch.object(single_instance, "_address", lambda: f"\0battop-nobody-{os.getpid()}"):
            self.assertFalse(single_instance.signal_existing())


class PlatformTests(unittest.TestCase):
    def setUp(self):
        from battop.platforms.linux import LinuxPlatform

        self.platform = LinuxPlatform()

    def test_helper_features_offer_setup_until_the_helper_exists(self):
        with mock.patch.object(helper_client, "available", return_value=False):
            for key in ("cpu_limit", "app_efficiency"):
                self.assertIn("one-time setup", self.platform.unavailable_reason(key))
                label, callback = self.platform.fix_action(key)
                self.assertEqual(callback, helper_client.install)
        with mock.patch.object(helper_client, "available", return_value=True):
            self.assertIsNone(self.platform.unavailable_reason("cpu_limit"))
            self.assertIsNone(self.platform.fix_action("cpu_limit"))

    def test_missing_tools_explain_themselves(self):
        with mock.patch.object(commands, "available", return_value=False):
            self.assertIn("power-profiles-daemon", self.platform.unavailable_reason("power_mode"))
            self.assertIn("bluetoothctl", self.platform.unavailable_reason("bluetooth"))
        with mock.patch.object(brightness, "find_backlight", return_value=None):
            self.assertIn("backlight", self.platform.unavailable_reason("brightness"))
        with mock.patch.object(timeouts, "available", return_value=False):
            self.assertIn("GNOME", self.platform.unavailable_reason("timeouts"))

    def test_actions_only_include_what_can_work_here(self):
        with mock.patch.object(commands, "available", return_value=False), \
             mock.patch.object(brightness, "find_backlight", return_value=None), \
             mock.patch.object(timeouts, "available", return_value=False), \
             mock.patch.object(helper_client, "available", return_value=False):
            keys = [a.key for a in self.platform.actions()]
        self.assertEqual(sorted(keys), ["app_efficiency", "cpu_limit"], "helper-backed ones wait for the setup")

    def test_every_supported_key_has_an_action(self):
        with mock.patch.object(commands, "available", return_value=True), \
             mock.patch.object(brightness, "find_backlight", return_value="x"), \
             mock.patch.object(timeouts, "available", return_value=True):
            keys = {a.key for a in self.platform.actions()}
        self.assertEqual(keys, set(self.platform.supported_keys))

    def test_system_language_comes_from_the_locale_variables(self):
        cases = [({"LANG": "tr_TR.UTF-8"}, "tr"), ({"LC_ALL": "en_US.UTF-8", "LANG": "tr_TR.UTF-8"}, "en"),
                 ({"LANGUAGE": "tr:en"}, "tr"), ({"LANG": "C.UTF-8"}, "c"), ({}, "en")]
        for env, expected in cases:
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(self.platform.system_language(), expected, env)

    def test_system_theme(self):
        def fake(answers):
            def run(command, timeout=10):
                value = answers[command[3]]
                if isinstance(value, Exception):
                    raise value
                return value
            return run

        for answers, expected in (
            ({"color-scheme": "'prefer-dark'", "gtk-theme": "'Adwaita'"}, "dark"),
            ({"color-scheme": "'default'", "gtk-theme": "'Yaru-dark'"}, "dark"),
            ({"color-scheme": "'default'", "gtk-theme": "'Adwaita'"}, "light"),
            ({"color-scheme": OSError("no gsettings"), "gtk-theme": OSError("x")}, "light"),
        ):
            with mock.patch.object(commands, "run", fake(answers)):
                self.assertEqual(self.platform.system_theme(), expected, answers)

    def test_notify_falls_back_to_the_tray_when_notify_send_is_missing(self):
        with mock.patch.object(commands, "run_raw", side_effect=OSError("missing")):
            self.assertFalse(self.platform.notify("t", "m"))
        with mock.patch.object(commands, "run_raw", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(self.platform.notify("title", "message"))
        self.assertEqual(run.call_args[0][0][0], "notify-send")


if __name__ == "__main__":
    unittest.main()
