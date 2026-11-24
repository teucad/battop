"""One Battop per user: an abstract unix socket that a second launch uses to say "show your window"."""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable

_socket: socket.socket | None = None  # Held for the life of the process.


def _address() -> str:
    return f"\0battop-single-instance-{os.getuid()}"  # Abstract namespace: no file to clean up.


def acquire() -> bool:
    """True if we're the only instance."""
    global _socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(_address())
        sock.listen(4)
    except OSError:
        sock.close()
        return False
    _socket = sock
    return True


def serve(on_show: Callable[[], None]) -> Callable[[], None]:
    """Call `on_show` whenever another launch asks for the window. Returns a function that stops listening."""
    sock = _socket
    if sock is None:
        return lambda: None

    def loop() -> None:
        while True:
            try:
                connection, _ = sock.accept()
            except OSError:  # Closed by stop().
                return
            with connection:
                try:
                    if connection.recv(16).startswith(b"show"):
                        on_show()
                except OSError:
                    pass

    threading.Thread(target=loop, name="battop-single-instance", daemon=True).start()

    def stop() -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    return stop


def signal_existing() -> bool:
    """Ask a running Battop to show its window. False if none was found."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        sock.connect(_address())
        sock.sendall(b"show")
        return True
    except OSError:
        return False
    finally:
        sock.close()
