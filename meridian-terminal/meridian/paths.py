"""Where Meridian keeps its files.

  macOS    ~/Library/Application Support/Meridian Terminal
  Windows  %LOCALAPPDATA%\\Meridian Terminal
  Linux    ~/.local/share/meridian   (the Fedora service uses /var/lib/meridian)

Set MERIDIAN_HOME to override.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_data_dir

from . import APP_ID, APP_NAME


def home() -> Path:
    env = os.environ.get("MERIDIAN_HOME")
    if env:
        p = Path(env).expanduser()
    elif sys.platform.startswith("linux"):
        p = Path(user_data_dir(APP_ID, appauthor=False))
    else:
        p = Path(user_data_dir(APP_NAME, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    return home() / "settings.json"


def secrets_file() -> Path:
    return home() / "secrets.json"


def db_file() -> Path:
    return home() / "meridian.sqlite"


def log_dir() -> Path:
    p = home() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def kill_file() -> Path:
    """Creating this file halts trading (works even if the UI is unreachable)."""
    return home() / "STOP"


def web_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "meridian" / "web"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "web"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
