# Battop

Automatic battery saving for Windows 10/11 laptops. When you unplug, Battop applies the
power-saving changes you've chosen. When you plug back in, it undoes them.

## Running it

Requires Python 3.10+ on Windows. The tray icon is optional:

```powershell
pip install -r requirements.txt   # optional: pystray + Pillow for the tray icon
python -m battop                  # or double-click battop.pyw (no console window)
python -m battop --debug          # verbose logging to the console and the log file
```

No admin rights are needed. Settings, the log, and undo data are stored in `%APPDATA%\Battop`.

## What it does while unplugged

| Action | How | Undo rule |
|---|---|---|
| Best power efficiency mode | `PowerSetActiveOverlayScheme` (powrprof) | Restored only if the mode is still the one Battop set |
| Dim the screen | WMI `WmiMonitorBrightnessMethods` (built-in panels only) | Only dims, never brightens. Skipped if you changed brightness yourself |
| Limit processor speed (off by default) | Battery-side `PROCTHROTTLEMAX` of the active scheme | Previous value written back |
| Turn on battery saver earlier | Battery-side `ESBATTTHRESHOLD` | Previous value written back |
| Apps in efficiency mode | `SetProcessInformation(ProcessPowerThrottling)` + idle priority, the same as Task Manager's Efficiency mode | Throttling and priority restored. Newly launched apps are caught on each check |

## Layout

```
battop/
  app.py         entry point: single-instance guard, logging, wiring
  engine.py      background thread: polls power status, applies/undoes actions
  power.py       ctypes wrappers for kernel32/powrprof (battery status, power mode, scheme values)
  config.py      Settings dataclass + JSON store (validated and clamped)
  gui.py         tkinter window (Overview / Power saving / Apps / General)
  tray.py        optional pystray icon (Open / Pause / Quit)
  autostart.py   "Start with Windows" via the HKCU Run key
  actions/       one module per battery-saving action
tests/           unit tests for config and engine (fake actions, nothing touches the system)
```

### How undo works

Each `Action.apply()` returns a small JSON-serialisable dict describing how to undo the
change. The engine keeps these in `state.json` while unplugged. If Battop crashes or the PC
shuts down on battery, the leftovers are undone the next time Battop starts.

### Adding a new action

1. Add the toggle (and any parameters) to `Settings` in `config.py`, with ranges in `_RANGES`.
2. Subclass `Action` in `battop/actions/`. Set `key`, `title`, and `settings_keys` (the toggle
   comes first), then implement `apply()` and `restore()`. Optionally implement `refresh()`.
3. Register it in `actions/__init__.py:default_actions()`.
4. Add a card for it in `gui.py` using `_toggle_card` or `_slider_card`.

## Tests

```powershell
python -m unittest discover -s tests -t .
```

## Ideas for next steps

- React to power changes instantly with `RegisterPowerSettingNotification` instead of polling.
- More actions: lower refresh rate on battery, turn off keyboard backlight, pause sync apps.
- Package as a single `.exe` with PyInstaller. `autostart.py` already handles frozen builds.
