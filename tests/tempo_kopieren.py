"""Durchsatz des Kopierens messen (PROMPTS.md Phase 3). Kein Test.

Erzeugt einen grossen Baum aus Dateien mit je eigenem Inhalt (keine
Duplikate) und misst "kopieren" mit den drei Profilen hdd, ssd und
netzwerk in ein frisches Ziel. Ein Aufwaermlauf vorweg, damit alle drei
Profile dieselbe Ausgangslage haben (Quelle im Dateisystem-Cache).

Aufruf:
    PYTHONPATH=src:tests .venv/bin/python tests/tempo_kopieren.py [Anzahl] [KB je Datei] [Ordner]
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import testbaum
from fotosort import analyse, config, db, kopieren, scan


def baum_erzeugen(wurzel: Path, anzahl: int, kb: int) -> Path:
    quelle = wurzel / "Quelle"
    if quelle.exists():
        return quelle
    quelle.mkdir(parents=True)
    je_ordner = 200
    fuellung = os.urandom(kb * 1024)
    for i in range(anzahl):
        ordner = quelle / f"ordner_{i // je_ordner:04d}"
        ordner.mkdir(exist_ok=True)
        # Eigener Inhalt je Datei: die Nummer vorn, dann Fuellung.
        (ordner / f"DSC{i:07d}.JPG").write_bytes(testbaum._JPEG + i.to_bytes(8, "big") + fuellung)
    return quelle


def messen(quelle: Path, arbeit: Path, profil: str) -> tuple[int, int, float, int, int]:
    ziel = arbeit / f"ziel_{profil}"
    archiv = arbeit / f"archiv_{profil}"
    shutil.rmtree(ziel, ignore_errors=True)
    shutil.rmtree(archiv, ignore_errors=True)
    ziel.mkdir()
    konf = config.Konfiguration()
    d = db.Datenbank.oeffnen(archiv)
    try:
        lauf = d.lauf_beginnen("tempo")
        scan.ausfuehren(quelle, ziel, konf, d, lauf)
        analyse.ausfuehren(ziel, konf, d, lauf, testbaum.exiftool_pfad(), None, None)
        e = kopieren.ausfuehren(ziel, konf, d, lauf, None, profil=profil)
        return e.kopiert, e.bytes_kopiert, e.sekunden, e.kopier_worker, e.hash_worker
    finally:
        d.schliessen()
        shutil.rmtree(ziel, ignore_errors=True)
        shutil.rmtree(archiv, ignore_errors=True)


def main() -> int:
    anzahl = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    kb = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    wurzel = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/fotosort_tempo_kopieren")
    print(f"Kerne im Container: {os.cpu_count()}")
    print(f"Baum mit {anzahl} Dateien zu je {kb} KB unter {wurzel} ...", flush=True)
    quelle = baum_erzeugen(wurzel, anzahl, kb)
    messen(quelle, wurzel, "hdd")  # Aufwaermen
    print("Profil     Worker  Dateien      MB   Sekunden  Dateien/s    MB/s")
    for profil in ("hdd", "ssd", "netzwerk"):
        n, b, s, kw, hw = messen(quelle, wurzel, profil)
        mb = b / 1024 / 1024
        print(f"{profil:<9} {kw:>4}/{hw:<3} {n:>7} {mb:>7.0f} {s:>10.2f} {n / s:>10.0f} {mb / s:>7.0f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
