"""Logging: rotating file in the data folder, ring buffer for the UI, stdout when headless."""
from __future__ import annotations

import collections
import logging
import logging.handlers
import sys
import threading
import time

from . import paths


class RingHandler(logging.Handler):
    def __init__(self, capacity: int = 1000):
        super().__init__()
        self.buffer: collections.deque = collections.deque(maxlen=capacity)
        self.listeners: list = []
        self._lock_ = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "ts": record.created,
                "level": record.levelname,
                "name": record.name.replace("meridian.", ""),
                "msg": self.format(record),
            }
        except Exception:
            return
        with self._lock_:
            self.buffer.append(entry)
            listeners = list(self.listeners)
        for fn in listeners:
            try:
                fn(entry)
            except Exception:
                pass

    def tail(self, n: int = 300) -> list[dict]:
        with self._lock_:
            return list(self.buffer)[-n:]


RING = RingHandler()


def setup(console: bool = False, level: int = logging.INFO):
    root = logging.getLogger()
    if getattr(root, "_meridian", False):
        return RING
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fmt.converter = time.localtime

    fileh = logging.handlers.RotatingFileHandler(
        paths.log_dir() / "meridian.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fileh.setFormatter(fmt)
    root.addHandler(fileh)

    RING.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(RING)

    if console:
        con = logging.StreamHandler(sys.stdout)
        con.setFormatter(fmt)
        root.addHandler(con)

    for noisy in ("aiohttp.access", "urllib3", "httpx", "httpcore", "anthropic",
                  "Tradernet", "TradernetSymbol", "asyncio", "pywebview"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._meridian = True  # type: ignore[attr-defined]
    return RING
