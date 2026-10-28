# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for all three targets. Build on the target OS:
#   macOS   -> dist/Meridian Terminal.app        (windowed, WKWebView)
#   Windows -> dist/Meridian Terminal/*.exe      (windowed app + console `meridian.exe`)
#   Linux   -> dist/meridian/meridian            (headless console binary)
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from meridian import APP_NAME, BUNDLE_ID, __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
ICONS = os.path.join(SPECPATH, "icons")

datas = [(os.path.join(ROOT, "meridian", "web"), "meridian/web")]
binaries = []
hidden = ["meridian.cli", "meridian.desktop", "meridian.server", "meridian.app",
          "tradernet", "tradernet.client", "aiohttp", "feedparser", "anthropic", "numpy"]
datas += copy_metadata("keyring")

if IS_MAC:
    hidden += ["keyring.backends.macOS", "keyring.backends.macOS.api", "webview.platforms.cocoa"]
if IS_WIN:
    hidden += ["keyring.backends.Windows", "webview.platforms.winforms",
               "webview.platforms.edgechromium", "clr"]
    hidden += collect_submodules("win32ctypes")
if not IS_LINUX:
    d, b, h = collect_all("webview")
    datas += d
    binaries += b
    hidden += [m for m in h if not any(x in m for x in ("gtk", "qt", "android", "cef", "mshtml"))]

excludes = ["tkinter", "matplotlib", "pandas", "IPython", "pytest", "PIL", "scipy"]
if IS_LINUX:   # headless: no window, no OS keychain (keys live in a 0600 file)
    excludes += ["webview", "gi", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy",
                 "keyring", "secretstorage", "jeepney", "cryptography"]

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_LINUX:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="meridian", console=True,
              strip=True, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, strip=True, upx=False, name="meridian")

elif IS_WIN:
    gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME, console=False,
              icon=os.path.join(ICONS, "meridian.ico"), upx=False)
    cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="meridian", console=True,
              icon=os.path.join(ICONS, "meridian.ico"), upx=False)
    coll = COLLECT(gui, cli, a.binaries, a.datas, upx=False, name=APP_NAME)

else:  # macOS
    sign = os.environ.get("MACOS_SIGN_IDENTITY") or None
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME, console=False,
              icon=os.path.join(ICONS, "meridian.icns"), upx=False, argv_emulation=False,
              codesign_identity=sign,
              entitlements_file=os.path.join(SPECPATH, "macos", "entitlements.plist") if sign else None)
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=os.path.join(ICONS, "meridian.icns"),
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": os.environ.get("MACOS_MIN_VERSION", "13.0"),
            "LSApplicationCategoryType": "public.app-category.finance",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "NSHumanReadableCopyright": "Personal use. Not financial advice.",
        },
    )
