"""API keys. macOS Keychain / Windows Credential Manager when available, otherwise a
0600 file in the data folder (headless Linux). Environment variables override both."""
from __future__ import annotations

import json
import logging
import os
import secrets as pysecrets
import sys
import threading

from . import BUNDLE_ID, paths

log = logging.getLogger(__name__)

KEYS = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "tradernet_public_key": "TRADERNET_PUBLIC_KEY",
    "tradernet_private_key": "TRADERNET_PRIVATE_KEY",
    "finnhub_api_key": "FINNHUB_API_KEY",
}


def _os_keyring():
    """Pick the platform backend explicitly (entry-point discovery is fragile when frozen)."""
    if sys.platform.startswith("linux"):
        return None          # headless servers: keys live in a 0600 file
    try:
        if sys.platform == "darwin":
            from keyring.backends import macOS
            return macOS.Keyring()
        if sys.platform == "win32":
            from keyring.backends import Windows
            return Windows.WinVaultKeyring()
    except Exception as e:  # pragma: no cover - platform specific
        log.warning("OS keychain unavailable, using file storage: %s", e)
    return None


class Secrets:
    def __init__(self, use_keyring: bool = True):
        self.file = paths.secrets_file()
        self._lock = threading.Lock()
        self._kr = _os_keyring() if use_keyring else None
        self._cache: dict[str, str] = {}

    # ---- file backend ------------------------------------------------------
    def _read_file(self) -> dict:
        try:
            return json.loads(self.file.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_file(self, data: dict):
        tmp = self.file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.file)
        try:
            os.chmod(self.file, 0o600)
        except OSError:
            pass

    # ---- public API --------------------------------------------------------
    def get(self, name: str) -> str:
        env = KEYS.get(name)
        if env and os.environ.get(env):
            return os.environ[env].strip()
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            value = ""
            if self._kr is not None and name in KEYS:
                try:
                    value = self._kr.get_password(BUNDLE_ID, name) or ""
                except Exception as e:
                    log.warning("Keychain read failed for %s: %s", name, e)
            if not value:
                value = self._read_file().get(name, "")
            self._cache[name] = value
            return value

    def set(self, name: str, value: str):
        value = (value or "").strip()
        with self._lock:
            stored = False
            if self._kr is not None and name in KEYS:
                try:
                    if value:
                        self._kr.set_password(BUNDLE_ID, name, value)
                    else:
                        try:
                            self._kr.delete_password(BUNDLE_ID, name)
                        except Exception:
                            pass
                    stored = True
                except Exception as e:
                    log.warning("Keychain write failed for %s, using file: %s", name, e)
            data = self._read_file()
            if stored:
                data.pop(name, None)
            elif value:
                data[name] = value
            else:
                data.pop(name, None)
            self._write_file(data)
            self._cache[name] = value

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    def masked(self, name: str) -> str:
        v = self.get(name)
        if not v:
            return ""
        return v[:6] + "…" + v[-4:] if len(v) > 14 else "•" * 8

    def status(self) -> dict:
        return {k: {"set": self.has(k), "masked": self.masked(k),
                    "from_env": bool(os.environ.get(env))} for k, env in KEYS.items()}

    @property
    def backend(self) -> str:
        if self._kr is None:
            return "file"
        return "macOS Keychain" if sys.platform == "darwin" else "Windows Credential Manager"

    # ---- UI access token (always file based so the CLI can read it) ---------
    def ui_token(self, regenerate: bool = False) -> str:
        with self._lock:
            data = self._read_file()
            if regenerate or not data.get("ui_token"):
                data["ui_token"] = pysecrets.token_urlsafe(24)
                self._write_file(data)
            return data["ui_token"]
