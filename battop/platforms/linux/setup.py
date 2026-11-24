"""Install or remove Battop's root helper and its polkit policy.

Must run as root. Battop runs it through pkexec ("Set up…" in the window) or you can run it
yourself:  sudo python3 setup.py install   |   sudo python3 setup.py remove

Standard library only and no imports from the battop package, so it works from any install layout.
"""

import os
import sys
from pathlib import Path

HELPER_PATH = "/usr/local/libexec/battop-helper"
POLICY_PATH = "/usr/share/polkit-1/actions/org.battop.helper.policy"
_HERE = Path(__file__).resolve().parent


def _install_file(source, destination, mode):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(Path(source).read_bytes())
    os.chmod(temporary, mode)
    os.replace(temporary, destination)  # Atomic: never leaves a half-written helper behind.


def install(helper_path=HELPER_PATH, policy_path=POLICY_PATH):
    _install_file(_HERE / "helper.py", helper_path, 0o755)
    _install_file(_HERE / "org.battop.helper.policy", policy_path, 0o644)


def remove(helper_path=HELPER_PATH, policy_path=POLICY_PATH):
    for path in (helper_path, policy_path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def main(argv):
    if len(argv) != 1 or argv[0] not in ("install", "remove"):
        print("usage: setup.py install|remove", file=sys.stderr)
        return 2
    if getattr(os, "geteuid", lambda: 1)() != 0:
        print("This must run as root (use sudo, or let Battop ask for your password).", file=sys.stderr)
        return 1
    try:
        install() if argv[0] == "install" else remove()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("Battop's helper was installed." if argv[0] == "install" else "Battop's helper was removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
