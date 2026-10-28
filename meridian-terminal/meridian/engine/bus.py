"""Thread-safe event bus: engine threads publish, asyncio websocket handlers consume."""
from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from datetime import date, datetime
from typing import Any


def _default(o: Any):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if hasattr(o, "item"):           # numpy scalars
        return o.item()
    if hasattr(o, "tolist"):         # numpy arrays
        return o.tolist()
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


def _clean(o: Any):
    """Replace NaN/inf (invalid JSON) with None."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=_default, allow_nan=False)
    except ValueError:
        return json.dumps(_clean(json.loads(json.dumps(obj, default=_default))),
                          default=_default)


class EventBus:
    def __init__(self):
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def subscribe(self, loop: asyncio.AbstractEventLoop, maxsize: int = 2000) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue):
        with self._lock:
            self._subs = [(lp, qq) for lp, qq in self._subs if qq is not q]

    def publish(self, type_: str, data: Any = None):
        msg = dumps({"type": type_, "data": data, "ts": time.time()})
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put, q, msg)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)


def _put(q: asyncio.Queue, msg: str):
    if q.full():
        try:
            q.get_nowait()        # drop oldest for slow clients
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(msg)
