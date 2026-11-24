"""Tests for the Windows actions. The Windows APIs are replaced by pure mocks (no wraps=)."""

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

if sys.platform == "win32":
    from battop.platforms.windows import display, power
    from battop.platforms.windows.actions import bluetooth, power_settings, refresh_rate
    from battop.platforms.windows.display import DEVMODEW

SCHEME = "381b4222-f694-41f0-9685-ff5bb260df2e"


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class DcValueActionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(power_settings, "power")
        self.power = patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("SUB_VIDEO", "VIDEO_IDLE", "SUB_SLEEP", "STANDBY_IDLE", "SUB_PROCESSOR", "PROCESSOR_MAX_STATE"):
            setattr(self.power, name, getattr(power, name))
        self.power.get_active_scheme.return_value = SCHEME
        self.values = {}
        self.power.read_dc_value.side_effect = lambda scheme, sub, setting: self.values[setting]

    def test_timeouts_only_shorten_and_treat_zero_as_never(self):
        action = power_settings.TimeoutsAction()
        settings = SimpleNamespace(screen_off_minutes=3, sleep_minutes=10)
        self.values = {power.VIDEO_IDLE: 0, power.STANDBY_IDLE: 300}  # never / already shorter than 10 min
        saved = action.apply(settings)
        self.assertEqual(saved["previous"], {power.VIDEO_IDLE: [power.SUB_VIDEO, 0]})
        self.power.write_dc_value.assert_called_once_with(SCHEME, power.SUB_VIDEO, power.VIDEO_IDLE, 180)

    def test_restore_writes_every_previous_value_back(self):
        action = power_settings.TimeoutsAction()
        saved = {"scheme": SCHEME, "previous": {power.VIDEO_IDLE: [power.SUB_VIDEO, 600], power.STANDBY_IDLE: [power.SUB_SLEEP, 900]}}
        action.restore(saved)
        self.power.write_dc_value.assert_any_call(SCHEME, power.SUB_VIDEO, power.VIDEO_IDLE, 600)
        self.power.write_dc_value.assert_any_call(SCHEME, power.SUB_SLEEP, power.STANDBY_IDLE, 900)

    def test_nothing_to_do_returns_none(self):
        self.values = {power.VIDEO_IDLE: 60, power.STANDBY_IDLE: 120}
        settings = SimpleNamespace(screen_off_minutes=3, sleep_minutes=10)
        self.assertIsNone(power_settings.TimeoutsAction().apply(settings))
        self.power.write_dc_value.assert_not_called()

    def test_cpu_limit_never_loosens(self):
        self.values = {power.PROCESSOR_MAX_STATE: 50}
        self.assertIsNone(power_settings.CpuLimitAction().apply(SimpleNamespace(cpu_max_percent=80)))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class RefreshRateActionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(refresh_rate, "display")
        self.display = patcher.start()
        self.addCleanup(patcher.stop)
        self.display.primary_display.return_value = r"\.\DISPLAY1"
        self.display.supported_rates.return_value = [30, 48, 60, 120, 240]
        self.hz = 240
        self.display.current_mode.side_effect = lambda device: SimpleNamespace(dmDisplayFrequency=self.hz)

    def test_drops_to_lowest_rate_of_at_least_60(self):
        saved = refresh_rate.RefreshRateAction().apply(None)
        self.assertEqual(saved, {"device": r"\.\DISPLAY1", "previous": 240, "set_to": 60})
        self.display.set_refresh_rate.assert_called_once_with(r"\.\DISPLAY1", 60)

    def test_does_nothing_when_already_low(self):
        self.hz = 60
        self.assertIsNone(refresh_rate.RefreshRateAction().apply(None))
        self.display.set_refresh_rate.assert_not_called()

    def test_restore_only_if_rate_is_still_ours(self):
        action = refresh_rate.RefreshRateAction()
        saved = {"device": "d", "previous": 240, "set_to": 60}
        self.hz = 120  # Changed by something else (e.g. G-Helper).
        action.restore(saved)
        self.display.set_refresh_rate.assert_not_called()
        self.hz = 60
        action.restore(saved)
        self.display.set_refresh_rate.assert_called_once_with("d", 240)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class BluetoothActionTests(unittest.TestCase):
    def setUp(self):
        for name in ("read_status", "set_state"):
            patcher = mock.patch.object(bluetooth, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.action = bluetooth.BluetoothAction()

    def test_turns_off_only_when_nothing_is_connected(self):
        self.read_status.return_value = ("on", 0)
        self.assertEqual(self.action.apply(None), {"was_on": True})
        self.set_state.assert_called_once_with(False)

    def test_stays_on_with_connected_devices(self):
        self.read_status.return_value = ("on", 2)
        self.assertIsNone(self.action.apply(None))
        self.set_state.assert_not_called()

    def test_no_radio_or_already_off_is_left_alone(self):
        for status in (None, ("off", 0)):
            self.read_status.return_value = status
            self.assertIsNone(self.action.apply(None))
        self.set_state.assert_not_called()

    def test_restore_turns_it_back_on_only_if_still_off(self):
        self.read_status.return_value = ("off", 0)
        self.action.restore({"was_on": True})
        self.set_state.assert_called_once_with(True)
        self.set_state.reset_mock()
        self.read_status.return_value = ("on", 0)
        self.action.restore({"was_on": True})
        self.set_state.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class DevmodeTests(unittest.TestCase):
    def test_devmodew_matches_the_windows_abi_size(self):
        import ctypes

        self.assertEqual(ctypes.sizeof(DEVMODEW), 220)


if __name__ == "__main__":
    unittest.main()
