# Battop

Automatic battery saving for laptops on Windows 10/11 and Linux. When you unplug, Battop
applies the power-saving changes you've chosen. When you plug back in, it undoes them.

It runs as a tray icon with a small settings window (light and dark, English and Turkish).
Every change is optional, and everything it changes is put back, even after a crash or a
shutdown on battery.

## Install and run

### Windows

Python 3.10+ is required. No admin rights are needed.

```powershell
pip install -r requirements.txt   # pystray + Pillow (both required)
python -m battop                  # or double-click battop.pyw (no console window)
python -m battop --debug          # verbose logging to the console and the log file
```

**Prebuilt exe.** To build a single `dist\Battop.exe` instead:

```powershell
.\tools\build_windows.ps1
```

This creates a separate `.venv-build` with PyInstaller. The exe is unsigned, so SmartScreen
warns on first run ("More info" → "Run anyway").

Settings, the log, and undo data live in `%APPDATA%\Battop`. "Start with Windows" uses the
`HKCU\...\Run` key.

### Linux

Needs Python 3.10+, tkinter, and (for the tray icon) an AppIndicator-capable shell.

```bash
sudo apt install python3-tk                      # Debian/Ubuntu; package names differ elsewhere
pipx install --system-site-packages git+https://github.com/teucad/battop
battop --install-desktop-entry                   # optional: add Battop to the application menu
battop                                           # or run from a checkout: python -m battop
```

- **Tray on GNOME / Wayland:** GNOME has no tray by default. Install the AppIndicator
  extension (`gnome-shell-extension-appindicator`) or use the window without a tray icon.
- **Data:** settings, log and undo data live in `$XDG_CONFIG_HOME/battop` (`~/.config/battop`).
- **Optional root helper.** Limiting the processor's speed and lowering other apps' priority
  need root. Battop asks for these through polkit (`pkexec`) via a small helper:

  ```bash
  sudo "$(command -v battop)" --setup-linux-helper     # install (or use "Set up…" in the window)
  sudo "$(command -v battop)" --remove-linux-helper    # remove
  ```

  (`command -v` is there because root's `PATH` usually doesn't include pipx's bin directory.)

  The helper is `/usr/local/libexec/battop-helper` plus a polkit policy. It is a small
  standard-library script that does exactly three things and validates every argument:
  `set-cpu-max <30-100>` (only ever lowers the limit), `restore-cpu`, and `renice` (only for
  processes owned by the user who asked). The policy allows only someone at an active local
  session to use it. Without the helper, the other actions still work.

## What it does while unplugged

| Action | Windows | Linux |
|---|---|---|
| Power mode | Best power efficiency overlay (powrprof), or the Power saver plan when the Balanced scheme isn't active | Power Saver profile (`powerprofilesctl`, needs power-profiles-daemon) |
| Dim the screen | WMI brightness, built-in panels only | Backlight via logind |
| Limit processor speed (off by default) | Battery-side `PROCTHROTTLEMAX` of the active scheme | sysfs max frequency, through the root helper |
| Turn on battery saver earlier | Battery-side `ESBATTTHRESHOLD` | — |
| Lower screen refresh rate (off by default) | Display mode change | — |
| Shorter screen-off and sleep times (off by default) | Battery-side power-plan timeouts | GNOME only (gsettings) |
| Bluetooth off (off by default) | Windows radio API (via PowerShell) | `bluetoothctl` |
| Apps in efficiency mode (off by default) | Process power throttling + idle priority, like Task Manager's Efficiency mode | `renice`, through the root helper |
| Battery level on the AniMe Matrix (off by default) | ASUS ROG lids with an AniMe Matrix, over HID | — |

Notes:

- Brightness only dims, never brightens, and is skipped if you changed it yourself.
- Power mode is restored only if it is still the one Battop set.
- A second, stronger tier kicks in when the battery is low (default 20%) with its own
  brightness and processor limits.
- Each card is shown only if the platform and hardware support it, and says why when it can't
  be used.

### How undo works

Each `Action.apply()` returns a small JSON-serialisable dict describing how to undo the
change. The engine keeps these in `state.json` while unplugged. If Battop crashes or the PC
shuts down on battery, the leftovers are undone the next time Battop starts.
`python -m battop --uninstall` (or "Remove Battop from this PC" in the window) undoes
everything, removes the startup entry and deletes Battop's data.

## Known limitations

- Timeouts on Linux work on GNOME only.
- Tray icon on GNOME/Wayland needs the AppIndicator extension.
- The Turkish translation was written without a native-speaker review.
- The AniMe Matrix display and the Linux GUI/tray/polkit path have only been tested in part;
  `tools/anime_probe.py` helps check the lid pattern on real hardware.
- The Windows exe is unsigned.

## For developers

```
battop/
  app.py        entry point: single-instance guard, logging, wiring
  engine.py     background thread: polls power status, applies/undoes actions
  config.py     Settings dataclass + JSON store (validated and clamped)
  gui.py        tkinter window; gui_theme.py / theme.py for light and dark
  tray.py       pystray icon (Open / Pause / Quit)
  i18n.py       _() / N_() and locales/<lang>.json (English → text maps)
  actions/      the Action base class (stateless apply/restore contract)
  platforms/    everything OS-specific behind the Platform protocol
    windows/    powrprof, WMI, PowerShell, HID (AniMe Matrix), actions/
    linux/      sysfs, external commands, root helper + polkit policy, actions/
tools/          build_windows.ps1, anime_probe.py, make_icon.py
tests/          unit tests, pure mocks (nothing touches the real system)
```

```powershell
python -m unittest discover -s tests -t .
```

### Adding an action

1. Add the toggle (and any parameters) to `Settings` in `config.py`, with ranges in `_RANGES`.
2. Subclass `Action` in the platform's `actions/` package. Set `key`, `title`, and
   `settings_keys` (the toggle comes first), then implement `apply()` and `restore()`.
   Optionally implement `refresh()`. Register it in that package's `default_actions()`.
3. Add the key to the platform's `supported_keys` and a card in `gui.py` using
   `_toggle_card` or `_slider_card`.
4. Wrap user-facing strings in `_()` / `N_()` and add translations to `locales/tr.json`.

## Credits

The ASUS AniMe Matrix protocol details come from the
[G-Helper](https://github.com/seerge/g-helper) project.
