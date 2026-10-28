"""Command line: `meridian [gui|headless|setup|status|url|halt|resume|backtest|token|version]`.

With no command, macOS/Windows open the desktop app; Linux runs headless.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import signal
import sys
import urllib.error
import urllib.request

from . import APP_NAME, __version__, paths

log = logging.getLogger("meridian.cli")


# ---- headless server ---------------------------------------------------------------------------
def cmd_headless(args) -> int:
    from aiohttp import web

    from .app import AlreadyRunning, acquire_instance_lock, build
    from .server import Server

    try:
        lock = acquire_instance_lock()
    except AlreadyRunning as e:
        print(e, file=sys.stderr)
        return 1
    engine = build("headless", console_logs=True)
    host = args.host or engine.settings.get("server.host", "127.0.0.1")
    port = args.port or engine.settings.get("server.port", 8765)
    token = engine.secrets.ui_token()
    server = Server(engine, token)

    async def main():
        runner = web.AppRunner(server.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        engine.start()
        shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        print(f"\n{APP_NAME} {__version__} running headless", flush=True)
        print(f"  Dashboard: http://{shown}:{port}/#token={token}", flush=True)
        if host in ("127.0.0.1", "localhost", "::1"):
            print(f"  From another computer: ssh -L {port}:127.0.0.1:{port} <this-server>, "
                  f"then open the link above.", flush=True)
        else:
            print("  WARNING: listening on a network interface over plain HTTP. Prefer an SSH "
                  "tunnel or a VPN such as Tailscale.", flush=True)
        print(f"  Data folder: {paths.home()}\n", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:   # Windows
                pass
        engine.on_quit = lambda: loop.call_soon_threadsafe(stop.set)
        await stop.wait()
        log.info("Stopping")
        await loop.run_in_executor(None, engine.stop)
        await runner.cleanup()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        engine.stop()
    finally:
        lock.close()
    return 0


# ---- talking to a running instance ------------------------------------------------------------
def _settings():
    from .config import Settings
    return Settings()


def _local_url(path: str) -> tuple[str, str]:
    from .secrets_store import Secrets
    s = _settings()
    port = s.get("server.port", 8765)
    host = s.get("server.host", "127.0.0.1")
    host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{host}:{port}{path}", Secrets(use_keyring=False).ui_token()


def _api(path: str, body: dict | None = None):
    url, token = _local_url(path)
    req = urllib.request.Request(url, method="POST" if body is not None else "GET",
                                 headers={"X-Token": token, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def cmd_url(args) -> int:
    from .secrets_store import Secrets
    s = _settings()
    port, host = s.get("server.port", 8765), s.get("server.host", "127.0.0.1")
    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    print(f"http://{shown}:{port}/#token={Secrets(use_keyring=False).ui_token()}")
    return 0


def cmd_token(args) -> int:
    from .secrets_store import Secrets
    tok = Secrets(use_keyring=False).ui_token(regenerate=args.regenerate)
    print(tok)
    if args.regenerate:
        print("Restart Meridian for the new token to take effect.", file=sys.stderr)
    return 0


def cmd_status(args) -> int:
    try:
        st = _api("/api/state")
    except (urllib.error.URLError, OSError):
        print(f"{APP_NAME} is not running (no server on the configured port).")
        s = _settings()
        print(f"  Data: {s['data_mode']}  Execution: {s['execution_mode']}  "
              f"Halted: {s['halted'] or paths.kill_file().exists()}")
        return 3
    app, acct, status = st["app"], st["account"], st["status"]
    print(f"{APP_NAME} {app['version']}  data={'demo' if app['demo'] else 'Tradernet'}  "
          f"account={app['acct']}  AI={'on' if app['ai_enabled'] else 'off'}  "
          f"{'HALTED' if app['halted'] else 'trading enabled'}")
    print(f"Equity {acct.get('equity', 0):,.2f}  Day P&L {acct.get('day_pnl', 0):+,.2f}  "
          f"Open positions {acct.get('open_positions', 0)}")
    m = status["market"]
    print(f"Market data: {'ok' if m['ok'] else 'ERROR ' + (m['error'] or '')}")
    for src in status.get("sources", []):
        print(f"  {src['label']:<20} {'ok' if src['ok'] else ('error: ' + src['error']) if src['ok'] is False else 'waiting'}")
    print(f"AI spend today: ${st['usage'].get('cost', 0):.2f} of ${st['usage'].get('budget', 0):.2f}")
    if st["positions"]:
        print("Positions:")
        for p in st["positions"]:
            q = st["quotes"].get(p["ticker"], {})
            print(f"  {p['ticker']:<10} {p['qty']:>8g} @ {p['entry']:<10.2f} last {q.get('last', 0):.2f}")
    return 0


def cmd_halt(args) -> int:
    try:
        _api("/api/control", {"action": "halt", "reason": "command line"})
        print("Trading halted. Working orders cancelled; positions kept.")
    except (urllib.error.URLError, OSError):
        paths.kill_file().touch()
        print(f"Meridian isn't running; created {paths.kill_file()} so it starts halted.")
    return 0


def cmd_resume(args) -> int:
    if paths.kill_file().exists():
        paths.kill_file().unlink()
    try:
        _api("/api/control", {"action": "resume"})
    except (urllib.error.URLError, OSError):
        from .config import Settings
        Settings().set_path("halted", False)
    print("Trading resumed.")
    return 0


# ---- interactive setup (for servers without a screen) -----------------------------------------
def _ask(prompt: str, default: str = "") -> str:
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def _yes(prompt: str, default: bool = True) -> bool:
    v = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not v else v.startswith("y")


def cmd_setup(args) -> int:
    from .config import Settings, SettingsError
    from .secrets_store import Secrets
    try:
        _api("/api/state")
        print(f"{APP_NAME} is running. Stop it first so it doesn't overwrite these settings:\n"
              "  sudo systemctl stop meridian      (then run setup, then start it again)")
        return 4
    except (urllib.error.URLError, OSError):
        pass
    s, sec = Settings(), Secrets(use_keyring=False)
    print(f"{APP_NAME} setup. Data folder: {paths.home()}\nPress Enter to keep the current value.\n")
    for name, label in (("anthropic_api_key", "Anthropic API key"),
                        ("tradernet_public_key", "Tradernet public key"),
                        ("tradernet_private_key", "Tradernet private key"),
                        ("finnhub_api_key", "Finnhub API key (optional)")):
        cur = sec.masked(name)
        v = getpass.getpass(f"{label}{f' [{cur}]' if cur else ''}: ").strip()
        if v:
            sec.set(name, v)
    data_mode = "live" if (sec.has("tradernet_public_key") and
                           _yes("Use live Tradernet market data?", s["data_mode"] == "live")) else "demo"
    tickers = _ask("Watchlist (comma separated Tradernet tickers)", ",".join(s.tickers))
    old_kw = s.keywords()
    watch = [{"ticker": t.strip().upper(), "keywords": old_kw.get(t.strip().upper(), [])}
             for t in tickers.split(",") if t.strip()]
    budget = float(_ask("Daily AI budget in USD", str(s.get("ai.daily_budget_usd"))))
    rpt = float(_ask("Risk per trade in USD (loss if the stop is hit)",
                     str(s.get("risk.risk_per_trade_usd"))))
    cap = float(_ask("Max position size in USD", str(s.get("risk.max_usd_per_trade"))))
    loss = float(_ask("Max daily loss in USD", str(s.get("risk.max_daily_loss_usd"))))
    try:
        s.update({"data_mode": data_mode, "watchlist": watch, "onboarded": True,
                  "ai": {"daily_budget_usd": budget},
                  "risk": {"risk_per_trade_usd": rpt, "max_usd_per_trade": cap,
                           "max_daily_loss_usd": loss}})
    except SettingsError as e:
        print(f"Not saved: {e}")
        return 2
    mode = _ask("Execution mode: off (signals only), paper, or live", s["execution_mode"]).lower()
    if mode == "live":
        if data_mode != "live":
            print("Live trading needs live Tradernet data; keeping paper.")
        elif input("Type LIVE to confirm real-money trading: ").strip() == "LIVE":
            s.set_path("execution_mode", "live")
        else:
            print("Not confirmed; keeping paper.")
    elif mode in ("off", "paper"):
        s.set_path("execution_mode", mode)
    if data_mode == "live":
        try:
            from .engine.tradernet_api import TradernetData
            print(TradernetData(sec.get("tradernet_public_key"),
                                sec.get("tradernet_private_key")).test())
        except Exception as e:
            print(f"Tradernet test failed: {e}")
    if sec.has("anthropic_api_key"):
        try:
            import anthropic
            anthropic.Anthropic(api_key=sec.get("anthropic_api_key")).models.list(limit=1)
            print("Connected to the Claude API")
        except Exception as e:
            print(f"Claude API test failed: {e}")
    _fix_owner()
    print(f"\nSaved. Data: {data_mode}, execution: {s['execution_mode']}. "
          "Restart the service to apply: sudo systemctl restart meridian")
    return 0


def _fix_owner():
    """When run with sudo for the system service, hand the files to the service user."""
    if os.name != "posix" or os.geteuid() != 0:
        return
    try:
        import pwd
        pw = pwd.getpwnam("meridian")
    except KeyError:
        return
    for root, dirs, files in os.walk(paths.home()):
        for name in dirs + files:
            try:
                os.chown(os.path.join(root, name), pw.pw_uid, pw.pw_gid)
            except OSError:
                pass
    os.chown(paths.home(), pw.pw_uid, pw.pw_gid)


# ---- offline backtest ------------------------------------------------------------------------------
def cmd_backtest(args) -> int:
    from . import logs
    from .config import Settings
    from .engine import backtest as bt
    from .engine.demo import DemoMarket
    from .secrets_store import Secrets
    logs.setup(console=False)
    s, sec = Settings(), Secrets(use_keyring=False)
    live = s["data_mode"] == "live" and sec.has("tradernet_public_key")
    data = market = None
    if live:
        from .engine.tradernet_api import TradernetData
        data = TradernetData(sec.get("tradernet_public_key"), sec.get("tradernet_private_key"))
    else:
        market = DemoMarket()
        market.sync({t: [t] for t in args.tickers})
        print("Using simulated demo prices (set data to Tradernet for real history).\n")
    for t in args.tickers:
        t = t.upper()
        d = data.candles(t, "1D", days=int(args.years * 365) + 400) if live else \
            market.candles(t, "1D").tail(int(args.years * 252) + 260)
        res = bt.run(t, d, None, s.get("risk"), args.cost_bps / 10000)
        if "error" in res:
            print(f"{t}: {res['error']}")
            continue
        print(f"=== {t}  {res['bars']} days, cost {args.cost_bps:g} bps/side ===")
        print(f"{'rule':16}{'trades':>7}{'win%':>7}{'avg':>8}{'total':>9}{'maxDD':>8}{'in mkt':>8}")
        for r in res["results"]:
            print(f"{r['rule']:16}{r['trades']:>7}{r['win_rate'] * 100:>6.0f}%"
                  f"{r['avg_trade'] * 100:>7.2f}%{r['total'] * 100:>8.1f}%"
                  f"{r['max_dd'] * 100:>7.1f}%{r['exposure'] * 100:>7.0f}%")
        bh = res["buy_hold"]
        print(f"{'buy & hold':16}{'':>22}{bh['total'] * 100:>8.1f}%{bh['max_dd'] * 100:>7.1f}%\n")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="meridian", description=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="open the desktop app")
    g.add_argument("--debug", action="store_true")
    h = sub.add_parser("headless", help="run without a window; dashboard over HTTP")
    h.add_argument("--host")
    h.add_argument("--port", type=int)
    sub.add_parser("setup", help="interactive setup for servers")
    sub.add_parser("status", help="show the running instance's status")
    sub.add_parser("url", help="print the dashboard link (with access token)")
    sub.add_parser("halt", help="halt trading (kill switch)")
    sub.add_parser("resume", help="resume trading")
    t = sub.add_parser("token", help="print or regenerate the dashboard access token")
    t.add_argument("--regenerate", action="store_true")
    b = sub.add_parser("backtest", help="backtest the rules from the command line")
    b.add_argument("tickers", nargs="+")
    b.add_argument("--years", type=float, default=3)
    b.add_argument("--cost-bps", type=float, default=10)
    sub.add_parser("version")
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if not a.startswith("-psn_")]
    args = p.parse_args(argv)

    try:
        return _dispatch(p, args)
    except BrokenPipeError:      # output piped into `head` etc.
        return 0
    except KeyboardInterrupt:
        return 130


def _dispatch(p, args) -> int:
    cmd = args.cmd
    if cmd is None:
        cmd = "headless" if sys.platform.startswith("linux") else "gui"
        args = p.parse_args([cmd])
    if cmd == "gui":
        from .desktop import run
        return run(debug=getattr(args, "debug", False))
    if cmd == "version":
        print(f"{APP_NAME} {__version__}")
        return 0
    return {"headless": cmd_headless, "setup": cmd_setup, "status": cmd_status,
            "url": cmd_url, "halt": cmd_halt, "resume": cmd_resume, "token": cmd_token,
            "backtest": cmd_backtest}[cmd](args)
