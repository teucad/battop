# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Battop: a tray app (tkinter GUI + optional pystray icon) for Windows and Linux laptops. When unplugged it applies the battery-saving changes the user chose; when plugged in it undoes them.
## Commands

```powershell
pip install -r requirements.txt            # pystray + Pillow (both required)
python -m battop                           # run (battop.pyw = no console window); add --debug for verbose logs
python -m unittest discover -s tests -t .  # all tests
python -m unittest tests.test_engine       # one module (or tests.test_engine.ClassName.test_name)
```

A `.venv` exists in the repo root. No linter is configured.

## Architecture

- **`engine.py`** runs on a background thread: reads `PowerStatus`, applies actions on unplug, restores on plug-in, and re-runs an action when any of its `settings_keys` change. Undo data returned by `Action.apply()` is persisted to `state.json` so leftovers are undone on the next start after a crash or shutdown on battery.
- **`actions/base.py`** defines the stateless `Action` contract (`key`, `title`, `settings_keys` with the on/off toggle first, `apply` → JSON-serialisable undo dict, `restore`, optional `refresh`). Concrete actions live per platform.
- **`platforms/`** isolates everything OS-specific behind the `Platform` protocol (`platforms/base.py`); `platforms.current()` picks `windows/` or `linux/`. The rest of the code (engine, gui, tray, config, i18n) is platform-neutral — keep OS calls out of it and add a hook to `Platform` instead. `supported_keys` decides which action cards the GUI shows; `unavailable_reason` / `warning` / `fix_action` drive per-card status.
  - Windows: ctypes/powrprof, WMI, PowerShell (`ps.py`), HID for the ASUS AniMe Matrix battery display (`anime.py`).
  - Linux: sysfs + external commands (`commands.py`), with privileged operations going through a root helper (`helper.py`, polkit policy, installed by `setup.py`, called via `helper_client.py` using `pkexec`).
- **`config.py`**: `Settings` dataclass + validated/clamped JSON store (ranges in `_RANGES`). Data dir is `%APPDATA%\Battop` on Windows, XDG on Linux.
- **`gui.py` / `gui_theme.py` / `theme.py`**: tkinter UI with light/dark following the OS theme; cards built with `_toggle_card` / `_slider_card`.
- **`i18n.py`**: wrap every user-facing string as `_("English text")`; use `N_()` for strings translated later (class-level titles, tables). Translations are English→text maps in `locales/<lang>.json` (currently `tr`); unknown strings fall back to English. Add new strings to `tr.json`.

### Adding an action

1. Add toggle/params to `Settings` in `config.py` (with `_RANGES`).
2. Subclass `Action` in the platform's `actions/` package and register it in that package's `default_actions()` (order matters: applied in order, undone in reverse).
3. Add its key to the platform's `supported_keys` and a card in `gui.py`.

## Testing rules

Tests must be pure mocks and never touch the real system (a `wraps=` test once switched the real Windows power plan). Use fake actions/platforms; patch every OS call.
