"""Geschwindigkeit der Analyse messen (PROMPTS.md Phase 2). Kein Test.

Erzeugt einen grossen Baum aus Kopien einer getaggten JPEG- und einer
MP4-Datei und misst "analyse" mit 1, 8, 16 und 32 ExifTool-Prozessen.

Aufruf:
    PYTHONPATH=src:tests .venv/bin/python tests/tempo_analyse.py [Anzahl] [Ordner]
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import testbaum
from fotosort import analyse, config, db, scan


def baum_erzeugen(wurzel: Path, anzahl: int) -> Path:
    quelle = wurzel / "Quelle"
    if quelle.exists():
        return quelle
    quelle.mkdir(parents=True)
    vorlagen = wurzel / "vorlagen"
    vorlagen.mkdir()
    jpg = vorlagen / "v.jpg"
    jpg.write_bytes(testbaum._JPEG)
    mp4 = vorlagen / "v.mp4"
    mp4.write_bytes(testbaum._mp4())
    testbaum._exiftool([
        ["-overwrite_original", "-EXIF:DateTimeOriginal=2026:01:01 12:30:00",
         "-EXIF:Model=ILCE-7CM2", "-EXIF:Make=SONY", str(jpg)],
        ["-overwrite_original", "-QuickTime:CreateDate=2026:01:01 23:30:00", str(mp4)],
    ])
    jpg_bytes, mp4_bytes = jpg.read_bytes(), mp4.read_bytes()
    je_ordner = 100
    for i in range(anzahl):
        ordner = quelle / f"ordner_{i // je_ordner:04d}"
        ordner.mkdir(exist_ok=True)
        if i % 10 == 9:
            (ordner / f"C{i:07d}.MP4").write_bytes(mp4_bytes)
        else:
            (ordner / f"DSC{i:07d}.JPG").write_bytes(jpg_bytes)
    return quelle


def messen(quelle: Path, arbeit: Path, prozesse: int) -> tuple[int, float]:
    ziel = arbeit / f"ziel_{prozesse}"
    archiv = arbeit / f"archiv_{prozesse}"
    shutil.rmtree(ziel, ignore_errors=True)
    shutil.rmtree(archiv, ignore_errors=True)
    ziel.mkdir()
    konf = config.Konfiguration()
    d = db.Datenbank.oeffnen(archiv)
    try:
        lauf = d.lauf_beginnen("tempo")
        scan.ausfuehren(quelle, ziel, konf, d, lauf)
        begonnen = time.monotonic()
        e = analyse.ausfuehren(ziel, konf, d, lauf, testbaum.exiftool_pfad(), None, prozesse)
        return e.bearbeitet, time.monotonic() - begonnen
    finally:
        d.schliessen()


def main() -> int:
    anzahl = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    wurzel = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/fotosort_tempo")
    print(f"Kerne im Container: {os.cpu_count()}")
    print(f"Baum mit {anzahl} Dateien unter {wurzel} ...", flush=True)
    quelle = baum_erzeugen(wurzel, anzahl)
    print("Prozesse  Dateien   Sekunden   Dateien/s")
    for prozesse in (1, 8, 16, 32):
        n, s = messen(quelle, wurzel, prozesse)
        print(f"{prozesse:>8}  {n:>7}   {s:>8.1f}   {n / s:>9.0f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
