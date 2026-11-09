"""Linux bundle; keep user settings, keys, macros and firmware out of the image."""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

root = Path(SPECPATH).parent
datas = [
    (str(root / "frontend/dist"), "frontend/dist"),
    (str(root / "frontend/public/icon-512.png"), "frontend/public"),
    (str(root / "config/pro_controller.json"), "config"),
    (str(root / "LICENSE"), "."),
]
datas += [
    (str(root / "presets" / f"{name}.json"), "presets")
    for name in ("xbox", "playstation", "switch_pro")
]
datas += (
    collect_data_files("webview")
    + collect_data_files("bumble")
    + collect_data_files("libusb_package")
)

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=datas,
    binaries=collect_dynamic_libs("libusb_package"),
    hiddenimports=[
        "webview.platforms.qt",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
    ]
    + collect_submodules("bumble.transport")
    + collect_submodules("bumble.drivers"),
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "gi",
        "webview.platforms.gtk",
        "webview.platforms.winforms",
        "webview.platforms.cocoa",
        "webview.platforms.cef",
    ],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Ounce-bt",
    console=True,
)
distribution = COLLECT(exe, analysis.binaries, analysis.datas, name="Ounce-bt")
