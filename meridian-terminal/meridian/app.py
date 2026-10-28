"""Wiring shared by the desktop app and headless mode."""
from __future__ import annotations

import logging
import socket
import sys

from . import logs, paths
from .config import Settings
from .engine.bus import EventBus
from .engine.core import Engine
from .engine.store import Store
from .secrets_store import Secrets

log = logging.getLogger("meridian")

LOCK_PORT = 47651   # one running instance per machine (two would double-trade)


class AlreadyRunning(RuntimeError):
    pass


def acquire_instance_lock() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
    except OSError:
        s.close()
        raise AlreadyRunning("Meridian Terminal is already running on this computer.")
    return s


def build(shell: str, console_logs: bool):
    logs.setup(console=console_logs)
    settings = Settings()
    secrets = Secrets(use_keyring=(shell == "desktop"))
    store = Store(paths.db_file())
    bus = EventBus()
    logs.RING.listeners.append(lambda entry: bus.publish("log", entry))
    engine = Engine(settings, secrets, store, bus, shell=shell)
    return engine
