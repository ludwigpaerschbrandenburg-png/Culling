# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spec fuer das eigenstaendige Paket (paket/bauen.py).

Zwei Programme auf einem gemeinsamen Ordner _internal:
  fotosort.exe          Konsole (Befehle, Arbeitsprozess der Oberflaeche)
  fotosort-fenster.exe  ohne Konsole - oeffnet direkt das Fenster (Phase 7)
Beide starten dasselbe Skript; ohne Angaben oeffnet sich das Fenster.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

WURZEL = Path(SPECPATH).resolve().parent   # noqa: F821 - SPECPATH setzt PyInstaller
WINDOWS = sys.platform.startswith("win")

datas, binaries, hiddenimports = [], [], []
# Zeitzonen (Video-Umrechnung) und das Fenster samt seiner Bibliotheken.
for paket in ("tzdata", "webview"):
    d, b, h = collect_all(paket)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("rich") + collect_submodules("uvicorn") + collect_submodules("anyio")
if WINDOWS:
    hiddenimports += ["clr", "clr_loader", "pythonnet"]
    for paket in ("pythonnet", "clr_loader"):
        d, b, h = collect_all(paket)
        datas += d
        binaries += b
        hiddenimports += h
# Die Seite der Oberflaeche.
datas.append((str(WURZEL / "src" / "fotosort" / "oberflaeche" / "static"), "fotosort/oberflaeche/static"))

a = Analysis(
    [str(WURZEL / "paket" / "fotosort_start.py")],
    pathex=[str(WURZEL / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_konsole = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True, name="fotosort", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
exe_fenster = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True, name="fotosort-fenster", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
coll = COLLECT(exe_konsole, exe_fenster, a.binaries, a.datas, strip=False, upx=False, name="fotosort")
