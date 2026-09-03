# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the single-file Windows build.

Why this file is not the PyInstaller default
    A default one-file PySide6 build is around 90 MB because it bundles all of
    Qt. This app uses QtCore, QtGui and QtWidgets and nothing else, so the rest
    is dropped in three passes:

    1. `excludes` keeps the unused PySide6 *Python* modules out.
    2. That is not enough: the Qt *DLLs* behind them are still pulled in by
       dependency analysis, so `_DROP_BINARIES` prunes them by name. Every
       entry there was checked against the PE import tables of Qt6Core,
       Qt6Gui, Qt6Widgets, Qt6Svg and qwindows.dll. Nothing the app loads
       references any of them.
    3. Qt's translations are stripped.

    The converter binaries in `tools/` are bundled as data and extracted next
    to the exe on first run, because a one-file build unpacks into a temporary
    directory that is deleted on exit (see `core.runtime`).

    nsz is bundled as a Python package rather than an exe: its pip console
    script is a launcher stub that only works next to the environment it was
    installed into. The app re-invokes itself with `--nsz-cli` instead.

    nsz must be >= 5.0.0. Version 4.x calls sys.exit(1) at import time when no
    keys file is present, which kills PyInstaller's isolated dependency probe
    and fails the build on any machine without prod.keys, CI included.

Run it through `python packaging/build_exe.py`, which checks the tools are
present first.
"""

from pathlib import Path

# SPECPATH is packaging/; everything else is relative to the project root.
ROOT = Path(SPECPATH).parent
TOOLS = ROOT / "tools"
PACKAGE = ROOT / "src" / "aynthor"
ASSETS = PACKAGE / "ui" / "assets"

# External converter binaries, extracted to tools/ next to the exe on first run.
# Not bundled: nsz runs in-process, and rom-converto's `ctr` commands supersede
# z3ds_compressor (which drags in four MinGW DLLs for a 200 KB tool).
SKIP_TOOLS = {
    "nsz.exe",
    "z3ds_compressor.exe",
    "libgcc_s_seh-1.dll",
    "libstdc++-6.dll",
    "libwinpthread-1.dll",
    "libzstd.dll",
}

tool_files: list[tuple[str, str]] = []
for pattern in ("*.exe", "*.dll", "*.bin"):
    for path in sorted(TOOLS.glob(pattern)):
        if path.name.startswith("_download") or path.name in SKIP_TOOLS:
            continue
        tool_files.append((str(path), "tools"))

asset_files = [(str(p), "aynthor/ui/assets") for p in ASSETS.glob("*") if p.is_file()]

QT_EXCLUDES = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtConcurrent",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
]

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=tool_files + asset_files,
    hiddenimports=["zstandard"],  # ZCCI "Open" decompresses in-process
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["kivy", "matplotlib", "numpy", "pandas", "tkinter", *QT_EXCLUDES],
    noarchive=False,
    optimize=2,
)

# Strip the Qt payloads a plain QtWidgets app never touches (about 24 MB raw).
# Verified against the PE import tables: none of Qt6Core / Qt6Gui / Qt6Widgets /
# Qt6Svg / qwindows.dll / qmodernwindowsstyle.dll reference any of these.
_DROP_BINARIES = {
    # software GL + shader compiler
    "opengl32sw.dll", "d3dcompiler_47.dll",
    # QML / Quick runtime
    "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll",
    "qt6qmlmeta.dll", "qt6qmlworkerscript.dll",
    # unused Qt libraries
    "qt6pdf.dll", "qt6network.dll", "qt6opengl.dll", "qt6virtualkeyboard.dll",
    # alternative Windows platform plugin (qwindows.dll is the one used)
    "qdirect2d.dll",
    # image formats the UI never loads (it needs .ico and .svg only)
    "qjpeg.dll", "qwebp.dll", "qtiff.dll", "qicns.dll",
    "qgif.dll", "qtga.dll", "qwbmp.dll", "qpdf.dll",
    # touch / on-screen keyboard input plugins
    "qtvirtualkeyboardplugin.dll", "qtuiotouchplugin.dll",
}
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in _DROP_BINARIES]
a.datas = [
    d for d in a.datas
    if not d[0].replace("\\", "/").lower().startswith("pyside6/translations")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AynThorCompression",
    icon=str(ASSETS / "app.ico") if (ASSETS / "app.ico").is_file() else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
