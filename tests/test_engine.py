import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from battop.actions.base import Action
from battop.config import Settings, SettingsStore
from battop.engine import Engine
from battop.status import PowerStatus


def status(on_battery: bool) -> PowerStatus:
    return PowerStatus(on_battery, True, 80, None, not on_battery, False)


class FakeAction(Action):
    def __init__(self, key, settings_key, fail=False):
        self.key = key
        self.title = key
        self.settings_keys = (settings_key,)
        self.fail = fail
        self.calls = []

    def apply(self, settings):
        self.calls.append("apply")
        if self.fail:
            raise OSError("boom")
        return {"previous": 1}

    def restore(self, saved):
        self.calls.append(("restore", saved["previous"]))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.store = SettingsStore(tmp / "settings.json")
        self.state_path = tmp / "state.json"
        self.on_battery = False
        self.mode = FakeAction("mode", "power_mode_enabled")
        self.cpu = FakeAction("cpu", "cpu_limit_enabled")  # Disabled by default.
        self.engine = self.make_engine([self.mode, self.cpu])

    def make_engine(self, actions, on_event=None):
        return Engine(
            self.store, actions, lambda: status(self.on_battery), self.state_path, on_event=on_event
        )

    def test_unplugging_applies_and_plugging_in_restores(self):
        self.engine.tick()
        self.assertEqual(self.mode.calls, [])

        self.on_battery = True
        self.engine.tick()
        self.assertTrue(self.engine.saving)
        self.assertEqual(self.mode.calls, ["apply"])
        self.assertEqual(self.cpu.calls, [], "disabled actions must not run")
        self.assertTrue(self.state_path.exists())

        self.engine.tick()  # Staying on battery doesn't re-apply.
        self.assertEqual(self.mode.calls, ["apply"])

        self.on_battery = False
        self.engine.tick()
        self.assertFalse(self.engine.saving)
        self.assertEqual(self.mode.calls, ["apply", ("restore", 1)])
        self.assertFalse(self.state_path.exists())

    def test_master_switch_pauses(self):
        self.on_battery = True
        self.engine.tick()
        self.engine.submit_settings(replace(Settings(), enabled=False))
        self.engine.tick()
        self.assertFalse(self.engine.saving)
        self.assertEqual(self.mode.calls, ["apply", ("restore", 1)])

    def test_settings_change_only_reruns_affected_actions(self):
        self.on_battery = True
        self.engine.tick()
        self.engine.submit_settings(replace(Settings(), cpu_limit_enabled=True))
        self.engine.tick()
        self.assertEqual(self.mode.calls, ["apply"])
        self.assertEqual(self.cpu.calls, ["apply"])

    def test_failing_action_does_not_block_others(self):
        broken = FakeAction("broken", "power_mode_enabled", fail=True)
        engine = self.make_engine([broken, self.mode])
        self.on_battery = True
        engine.tick()
        self.assertEqual(self.mode.calls, ["apply"])
        self.assertEqual(engine.active_titles(), ["mode"])

    def test_stop_restores(self):
        self.on_battery = True
        self.engine.tick()
        self.engine.stop()
        self.assertEqual(self.mode.calls, ["apply", ("restore", 1)])

    def test_leftovers_from_previous_session_are_undone_on_start(self):
        self.state_path.write_text(json.dumps({"active": {"mode": {"previous": 7}}}), encoding="utf-8")
        self.engine.start()
        self.engine.stop()
        self.assertEqual(self.mode.calls[0], ("restore", 7))
        self.assertFalse(self.state_path.exists())

    def test_events_are_emitted_and_can_be_silenced(self):
        events = []
        engine = self.make_engine([self.mode], on_event=events.append)
        self.on_battery = True
        engine.tick()
        self.on_battery = False
        engine.tick()
        self.assertEqual(events, ["saving_on", "saving_off"])

        events.clear()
        engine.submit_settings(replace(Settings(), notifications=False))
        self.on_battery = True
        engine.tick()
        self.assertEqual(events, [])

    def test_wake_reacts_immediately_despite_long_poll_interval(self):
        self.assertGreaterEqual(self.engine.settings.poll_interval_sec, 30)
        self.engine.start()
        self.addCleanup(self.engine.stop)
        time.sleep(0.2)  # Let the first (plugged-in) tick finish.
        self.on_battery = True
        self.engine.wake()
        deadline = time.monotonic() + 2
        while not self.engine.saving and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.engine.saving)


if __name__ == "__main__":
    unittest.main()
