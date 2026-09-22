"""Jede Phase am grossen Testbaum messen (PROMPTS.md Phase 6). Kein Test.

Erzeugt einen Baum aus mindestens 50.000 Dateien gemischter Groesse
(JPEG mit EXIF, RAW als TIFF, MP4, XMP-Sidecars), alle mit eigenem Inhalt,
und misst scan, analyse, kopieren, pruefen und aufraeumen nacheinander -
Dateien/s und MB/s je Phase. Wahlweise laeuft jede Phase unter dem
Profiler, die Auswertung landet als Textdatei im Arbeitsordner.

Aufruf:
    PYTHONPATH=src:tests .venv/bin/python tests/tempo_phasen.py [--anzahl N]
        [--ordner PFAD] [--profiler] [--szenario kopieren|verschieben]
        [--profil hdd|ssd|netzwerk]

Szenario "verschieben": kopieren --verschieben ueber den Kopierweg (so, als
laege die Quelle auf einem anderen Laufwerk) - misst die doppelte Lesezeit
aus docs/todo.md. Die Zahlen gelten fuer diesen Container mit
Dateisystem-Cache, nicht fuer eine echte Platte.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import shutil
import sys
import time
from pathlib import Path

import testbaum
from fotosort import analyse, aufraeumen, config, db, kopieren, loeschen, pfade, pruefen, scan

MODELLE = ["ILCE-7CM2", "ILCE-7C", "Canon EOS R5"]
JE_ORDNER = 100          # Dateien je Quellordner
VORLAGEN = 120           # verschiedene Aufnahmetage x Modelle


def _vorlagen(ordner: Path) -> list[tuple[bytes, bytes, bytes]]:
    """(JPEG, TIFF, MP4) je Aufnahmetag/Modell, getaggt mit ExifTool."""
    ordner.mkdir(parents=True, exist_ok=True)
    fertig = ordner / "fertig"
    befehle: list[list[str]] = []
    pfad_liste: list[tuple[Path, Path, Path]] = []
    for i in range(VORLAGEN):
        tag = 1 + (i * 3) % 28
        monat = 1 + (i // 10) % 12
        jahr = 2023 + (i // 120) % 3
        modell = MODELLE[i % len(MODELLE)]
        jpg, tif, mp4 = ordner / f"v{i}.jpg", ordner / f"v{i}.tif", ordner / f"v{i}.mp4"
        pfad_liste.append((jpg, tif, mp4))
        if fertig.exists():
            continue
        jpg.write_bytes(testbaum._JPEG)
        tif.write_bytes(testbaum._tiff())
        mp4.write_bytes(testbaum._mp4())
        zeit = f"{jahr}:{monat:02d}:{tag:02d} {8 + i % 12:02d}:{i % 60:02d}:00"
        befehle.append(["-overwrite_original", f"-EXIF:DateTimeOriginal={zeit}",
                        f"-EXIF:Model={modell}", "-EXIF:Make=SONY", str(jpg)])
        befehle.append(["-overwrite_original", f"-EXIF:DateTimeOriginal={zeit}",
                        f"-EXIF:Model={modell}", "-EXIF:Make=SONY", str(tif)])
        befehle.append(["-overwrite_original", f"-QuickTime:CreateDate={zeit}", str(mp4)])
    if not fertig.exists():
        testbaum._exiftool(befehle)
        fertig.write_text("ok")
    return [(j.read_bytes(), t.read_bytes(), m.read_bytes()) for j, t, m in pfad_liste]


def baum_erzeugen(wurzel: Path, anzahl: int) -> Path:
    """<wurzel>/Quelle mit ~anzahl Dateien; jede Datei hat eigenen Inhalt."""
    quelle = wurzel / "Quelle"
    if (wurzel / "quelle_fertig").exists():
        return quelle
    shutil.rmtree(quelle, ignore_errors=True)
    quelle.mkdir(parents=True)
    vorlagen = _vorlagen(wurzel / "vorlagen")
    zufall = os.urandom(4 * 1024 * 1024)
    xmp = b'<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>' + b" " * 3000
    n = 0
    ordner_nr = 0
    while n < anzahl:
        ordner = quelle / f"Karte_{ordner_nr // 50:02d}" / f"{100 + ordner_nr}MSDCF"
        ordner.mkdir(parents=True, exist_ok=True)
        for i in range(JE_ORDNER):
            jpg_v, tif_v, mp4_v = vorlagen[(ordner_nr * 7 + i) % len(vorlagen)]
            kennung = n.to_bytes(8, "big")
            r = (ordner_nr * 31 + i * 7) % 1000
            if i % 100 < 70:                       # 70 % JPEG 20-120 KB
                laenge = 20_000 + (r * 100) % 100_000
                (ordner / f"DSC{n:06d}.JPG").write_bytes(jpg_v + kennung + zufall[:laenge])
                if i % 7 == 0:                     # ein Teil davon mit XMP-Sidecar
                    (ordner / f"DSC{n:06d}.xmp").write_bytes(xmp + kennung)
                    n += 1
            elif i % 100 < 88:                     # 18 % RAW 100-300 KB mit Sidecar
                laenge = 100_000 + (r * 200) % 200_000
                (ordner / f"DSC{n:06d}.ARW").write_bytes(tif_v + kennung + zufall[:laenge])
                (ordner / f"DSC{n:06d}.ARW.xmp").write_bytes(xmp + kennung)
                n += 1
            elif i % 100 < 98:                     # 10 % kleine Sidecar-lose JPEGs
                laenge = 5_000 + (r * 10) % 10_000
                (ordner / f"IMG{n:06d}.jpg").write_bytes(jpg_v + kennung + zufall[:laenge])
            else:                                  # 2 % Video 0,5-1,5 MB
                laenge = 500_000 + (r * 1000) % 1_000_000
                (ordner / f"C{n:04d}.MP4").write_bytes(mp4_v + kennung + zufall[:laenge])
            n += 1
        ordner_nr += 1
    (wurzel / "quelle_fertig").write_text(str(n))
    return quelle


def _zaehlen(pfad: Path) -> tuple[int, int]:
    n = b = 0
    for wurzel, _o, dateien in os.walk(pfad):
        for d in dateien:
            n += 1
            b += os.stat(os.path.join(wurzel, d)).st_size
    return n, b


class Messung:
    def __init__(self, arbeit: Path, profiler: bool) -> None:
        self.arbeit = arbeit
        self.profiler = profiler
        self.zeilen: list[str] = []

    def phase(self, name: str, fn, dateien_fn, bytes_fn) -> object:
        prof = cProfile.Profile() if self.profiler else None
        begonnen = time.monotonic()
        if prof:
            prof.enable()
        try:
            e = fn()
        finally:
            if prof:
                prof.disable()
        s = time.monotonic() - begonnen
        n, b = dateien_fn(e), bytes_fn(e)
        zeile = (f"{name:<12} {n:>8} Dateien  {b / 1e6:>9.1f} MB  {s:>7.1f} s"
                 f"  {n / s if s else 0:>8.0f} Dateien/s  {b / 1e6 / s if s else 0:>7.1f} MB/s")
        print(zeile, flush=True)
        self.zeilen.append(zeile)
        if prof:
            aus = io.StringIO()
            st = pstats.Stats(prof, stream=aus)
            aus.write(f"=== {name}: nach eigener Zeit (tottime) ===\n")
            st.sort_stats("tottime").print_stats(35)
            aus.write(f"\n=== {name}: nach Gesamtzeit (cumtime) ===\n")
            st.sort_stats("cumtime").print_stats(45)
            (self.arbeit / f"profil_{name}.txt").write_text(aus.getvalue(), encoding="utf-8")
        return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anzahl", type=int, default=50_000)
    ap.add_argument("--ordner", type=Path, default=Path("/tmp/fotosort_tempo_phasen"))
    ap.add_argument("--profiler", action="store_true")
    ap.add_argument("--szenario", choices=["kopieren", "verschieben"], default="kopieren")
    ap.add_argument("--profil", choices=sorted(kopieren.PROFILE), default="ssd")
    ap.add_argument("--nur-baum", action="store_true")
    args = ap.parse_args()
    wurzel: Path = args.ordner
    print(f"Kerne: {os.cpu_count()}  Szenario: {args.szenario}  Profil: {args.profil}", flush=True)
    t = time.monotonic()
    quelle = baum_erzeugen(wurzel, args.anzahl)
    n, b = _zaehlen(quelle)
    print(f"Quelle: {n} Dateien, {b / 1e6:.0f} MB unter {quelle} ({time.monotonic() - t:.0f} s)", flush=True)
    if args.nur_baum:
        return 0

    ziel = wurzel / "Ziel"
    archiv = wurzel / "archiv"
    shutil.rmtree(ziel, ignore_errors=True)
    shutil.rmtree(archiv, ignore_errors=True)
    ziel.mkdir()
    konf = config.Konfiguration()
    m = Messung(wurzel, args.profiler)
    if args.szenario == "verschieben":
        pfade.gleiches_laufwerk = lambda a, b: False   # wie ein anderes Laufwerk
    d = db.Datenbank.oeffnen(archiv)
    try:
        lauf = d.lauf_beginnen("tempo")
        m.phase("scan", lambda: scan.ausfuehren_mehrere([quelle], ziel, konf, d, lauf),
                lambda g: g.gesamt.dateien, lambda g: g.gesamt.bytes_gesamt)
        m.phase("analyse", lambda: analyse.ausfuehren(ziel, konf, d, lauf, testbaum.exiftool_pfad(), None, None),
                lambda e: e.bearbeitet, lambda e: 0)
        verschieben = args.szenario == "verschieben"
        name = "verschieben" if verschieben else "kopieren"
        e = m.phase(name, lambda: kopieren.ausfuehren(ziel, konf, d, lauf, None, profil=args.profil, verschieben=verschieben),
                    lambda e: e.kopiert, lambda e: e.bytes_kopiert)
        if verschieben:
            print(f"  davon Quelle geloescht: {e.quelle_geloescht}, verweigert: {e.loeschung_verweigert}, "
                  f"Fehler: {e.fehler}", flush=True)
        else:
            m.phase("pruefen", lambda: pruefen.ausfuehren(ziel, konf, d, lauf, None, profil=args.profil),
                    lambda e: e.bearbeitet, lambda e: e.bytes_gelesen)
            m.phase("aufraeumen", lambda: aufraeumen.ausfuehren(
                ziel, konf, d, lauf, None, weise=loeschen.WEISE_ENDGUELTIG,
                bestaetigen=lambda *a: True, profil=args.profil),
                lambda e: e.bearbeitet, lambda e: e.bytes_gelesen)
        d.lauf_beenden(lauf)
    finally:
        d.schliessen()
    (wurzel / f"ergebnis_{args.szenario}.txt").write_text("\n".join(m.zeilen) + "\n", encoding="utf-8")
    # Der Baum ist verbraucht (Quelle geloescht) - beim naechsten Aufruf neu.
    (wurzel / "quelle_fertig").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
