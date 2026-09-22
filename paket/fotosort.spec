# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec fuer das eigenstaendige Paket (paket/bauen.py).

Zwei Programme auf einem gemeinsamen Ordner _internal:
  fotosort.exe          das Fenster (PySide6) - ohne Konsole, mit Symbol; oeffnet
                        ohne Angaben die Oberflaeche
  fotosort-konsole.exe  Befehle mit Ausgabe (fotosort.bat), Arbeitsprozesse der
                        Oberflaeche, Paketpruefung
Beide starten dasselbe Skript (paket/fotosort_start.py).
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

WURZEL = Path(SPECPATH).resolve().parent   # noqa: F821 - SPECPATH setzt PyInstaller
WINDOWS = sys.platform.startswith("win")
ICON = str(WURZEL / "paket" / "fotosort.ico") if WINDOWS else None

datas, binaries, hiddenimports = [], [], []
# Zeitzonen (Video-Umrechnung); PySide6 (Qt) kommt ueber die PyInstaller-Hooks.
d, b, h = collect_all("tzdata")
datas += d
binaries += b
hiddenimports += h
hiddenimports += collect_submodules("rich") + collect_submodules("uvicorn") + collect_submodules("anyio")
hiddenimports += ["PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore"]
# Die Seite der Browser-Fassung, Schriften (woff2 fuer den Browser, ttf fuer Qt), Symbol.
datas.append((str(WURZEL / "src" / "fotosort" / "oberflaeche" / "static"), "fotosort/oberflaeche/static"))

a = Analysis(
    [str(WURZEL / "paket" / "fotosort_start.py")],
    pathex=[str(WURZEL / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtMultimedia",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_fenster = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True, name="fotosort", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, icon=ICON,
)
exe_konsole = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True, name="fotosort-konsole", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, icon=ICON,
)
coll = COLLECT(exe_fenster, exe_konsole, a.binaries, a.datas, strip=False, upx=False, name="fotosort")
