import sys
import unittest
from unittest import mock

if sys.platform == "win32":
    from battop.platforms.windows import WindowsPlatform, power
    from battop.platforms.windows.actions import power_mode

CUSTOM = "11111111-2222-3333-4444-555555555555"


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class PowerPlanActionTests(unittest.TestCase):
    def setUp(self):
        # A pure mock (no `wraps=`): nothing here may reach the real Windows power APIs.
        patcher = mock.patch.object(power_mode, "power")
        self.power = patcher.start()
        self.addCleanup(patcher.stop)
        self.power.SCHEME_BALANCED = power.SCHEME_BALANCED
        self.power.SCHEME_POWER_SAVER = power.SCHEME_POWER_SAVER
        self.action = power_mode.PowerPlanAction()

    def test_custom_plan_switches_to_power_saver_and_back(self):
        self.power.get_active_scheme.return_value = CUSTOM
        self.assertEqual(self.action.apply(None), {"previous": CUSTOM})
        self.power.set_active_scheme.assert_called_with(power.SCHEME_POWER_SAVER)

        self.power.get_active_scheme.return_value = power.SCHEME_POWER_SAVER
        self.action.restore({"previous": CUSTOM})
        self.power.set_active_scheme.assert_called_with(CUSTOM)

    def test_balanced_plan_is_left_to_the_power_mode_action(self):
        self.power.get_active_scheme.return_value = power.SCHEME_BALANCED
        self.assertIsNone(self.action.apply(None))
        self.power.set_active_scheme.assert_not_called()

    def test_missing_power_saver_plan_is_not_an_error(self):
        self.power.get_active_scheme.return_value = CUSTOM
        self.power.set_active_scheme.side_effect = OSError("no such plan")
        self.assertIsNone(self.action.apply(None))

    def test_restore_respects_a_plan_the_user_picked(self):
        self.power.get_active_scheme.return_value = CUSTOM
        self.action.restore({"previous": "other"})
        self.power.set_active_scheme.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class PowerModeAvailabilityTests(unittest.TestCase):
    def reason(self, scheme, dc_overlay):
        with mock.patch.object(power, "get_active_scheme", return_value=scheme), \
             mock.patch.object(power, "get_dc_overlay", return_value=dc_overlay):
            return WindowsPlatform().unavailable_reason("power_mode")

    def test_usable_without_per_source_modes(self):
        self.assertIsNone(self.reason(power.SCHEME_BALANCED, None))

    def test_blocked_when_battery_mode_is_already_efficient(self):
        self.assertIn("already", self.reason(power.SCHEME_BALANCED, power.MODE_BEST_EFFICIENCY))

    def test_blocked_when_battery_mode_is_something_else(self):
        self.assertIn("separate power mode", self.reason(power.SCHEME_BALANCED, power.MODE_BALANCED))

    def test_custom_plan_uses_the_power_saver_fallback_instead(self):
        self.assertIsNone(self.reason(CUSTOM, power.MODE_BALANCED))


if __name__ == "__main__":
    unittest.main()
