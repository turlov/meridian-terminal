"""Desktop app: engine + local server + a native window (WKWebView on macOS, WebView2 on
Windows) via pywebview. Falls back to the default browser if no web view is available."""
from __future__ import annotations

import logging
import sys
import threading
import webbrowser

from . import APP_NAME, paths
from .app import AlreadyRunning, acquire_instance_lock, build
from .server import Server, ServerThread

log = logging.getLogger("meridian.desktop")


def _message_box(text: str):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x40)
    else:
        print(text, file=sys.stderr)


def run(debug: bool = False) -> int:
    try:
        lock = acquire_instance_lock()
    except AlreadyRunning as e:
        _message_box(f"{e}\nSwitch to its window, or quit it first.")
        return 1

    engine = build("desktop", console_logs=debug)
    token = engine.secrets.ui_token()
    srv = ServerThread(Server(engine, token), "127.0.0.1", 0)
    port = srv.start()
    engine.start()
    url = f"http://127.0.0.1:{port}/#token={token}"
    log.info("UI at http://127.0.0.1:%s (data folder %s)", port, paths.home())

    quit_event = threading.Event()
    try:
        import webview
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True          # CSV exports
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        except Exception:
            pass
        window = webview.create_window(
            APP_NAME, url, width=1500, height=940, min_size=(1100, 700),
            background_color="#000000", text_select=True, confirm_close=True)

        def on_quit():
            quit_event.set()
            try:
                window.destroy()
            except Exception:
                pass

        engine.on_quit = on_quit
        webview.start(debug=debug, private_mode=False,
                      storage_path=str(paths.home() / "webview"),
                      localization={"global.quitConfirmation":
                                    "Quit Meridian Terminal? Scans, AI reviews and new orders stop "
                                    "until you open it again. Stops already placed at the broker "
                                    "stay active."})
    except Exception as e:   # no web view available: use the browser instead
        log.warning("Native window unavailable (%s); opening the browser", e)
        engine.on_quit = quit_event.set
        webbrowser.open(url)
        try:
            quit_event.wait()
        except KeyboardInterrupt:
            pass
    finally:
        log.info("Shutting down")
        engine.stop()
        srv.stop()
        lock.close()
    return 0
