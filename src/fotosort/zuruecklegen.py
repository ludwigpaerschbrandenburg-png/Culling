"""Den Ordner _geloescht_<Datum> zuruecklegen (SPEC §4 Phase 5, seit v0.8).

Das Aufraeumen legt Quelldateien standardmaessig nicht ins Nichts, sondern in
einen Ordner _geloescht_<Datum> innerhalb der Quelle. "fotosort zuruecklegen"
macht das rueckgaengig: Jede Datei, deren Zeile im Status quelle_geloescht
steht und deren schreibpfad in diesem Ordner liegt, kommt an ihren alten Ort.

Was nie geschieht:
  - Nichts wird ueberschrieben. Ist der alte Name belegt, bleibt die Datei im
    Ordner _geloescht_ und wird genannt.
  - Die Datei im Ordner _geloescht_ wird nie geloescht. Zurueck geht sie nur
    durch dasselbe nicht ueberschreibende Umbenennen wie ueberall (§5). Kann
    das Dateisystem das nicht (exFAT), wird an den alten Ort kopiert, die Kopie
    zurueckgelesen - und das Original bleibt im Ordner liegen: Es steht im
    Status quelle_geloescht, und aus diesem Status darf nie geloescht werden
    (CLAUDE.md). Der Nutzer loescht den Ordner dann selbst.
  - Dateien im Ordner ohne passende Zeile bleiben unberuehrt.

Die zurueckgelegte Zeile geht auf "gefunden" (Groesse und Aenderungsdatum
frisch): Der naechste Durchgang erkennt sie wieder; ihr Inhalt liegt schon im
Archiv und wird dort als Duplikat erkannt. Leer gewordene Unterordner des
Ordners _geloescht_ (und er selbst) werden entfernt - nur Ordner, nie Dateien.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db, hashes, loeschen, meldungen, pfade

ART_ZURUECKGELEGT = "zurueckgelegt"
ART_BELEGT = "zuruecklegen_belegt"
ART_KOPIERT = "zuruecklegen_kopiert"
ART_FEHLER = "zuruecklegen_fehler"

SEITE = 2000


@dataclass
class Ergebnis:
    geplant: int = 0
    zurueckgelegt: int = 0
    kopiert: int = 0                                   # davon zurueckkopiert, Original bleibt im Ordner
    belegt: list[str] = field(default_factory=list)    # alter Ort inzwischen belegt
    fehlt: list[str] = field(default_factory=list)     # nicht mehr im Ordner _geloescht_
    fehler: list[tuple[str, str]] = field(default_factory=list)
    ordner_entfernt: int = 0
    ordner_uebrig: list[str] = field(default_factory=list)
    sekunden: float = 0.0
    dry_run: bool = False

    @property
    def nicht_zurueck(self) -> int:
        return len(self.belegt) + len(self.fehler)


def _korb_wurzel(quellwurzel: Path, im_korb: Path) -> Path | None:
    """Der Ordner _geloescht_<Datum> direkt in der Quellwurzel, in dem die Datei liegt."""
    try:
        teile = im_korb.relative_to(quellwurzel).parts
    except ValueError:
        return None
    if len(teile) < 2 or not loeschen.ist_papierkorb(teile[0]):
        return None
    return quellwurzel / teile[0]


def ausfuehren(dbank: db.Datenbank, lauf: int, konsole=None, *,
               quellwurzeln: list[str] | None = None, dry_run: bool = False) -> Ergebnis:
    begonnen = time.monotonic()
    e = Ergebnis(dry_run=dry_run)
    koerbe: dict[str, Path] = {}
    ab = ""
    while True:
        seite = dbank.zuruecklegbar(quellwurzeln, ab, SEITE)
        if not seite:
            break
        ab = seite[-1]["quellpfad"]
        for z in seite:
            wurzel = Path(db.text_pfad(z["quellwurzel"]))
            im_korb = Path(db.text_pfad(z["schreibpfad"]))
            ort = Path(db.text_pfad(z["quellpfad"]))
            korb = _korb_wurzel(wurzel, im_korb)
            if korb is None:
                continue   # kein Ordner _geloescht_ - nicht unsere Sache
            e.geplant += 1
            koerbe[db.pfad_text(korb)] = korb
            if not os.path.lexists(pfade.lang(im_korb)):
                e.fehlt.append(db.pfad_text(ort))
                continue
            if dry_run:
                if os.path.lexists(pfade.lang(ort)):
                    e.belegt.append(db.pfad_text(ort))
                else:
                    e.zurueckgelegt += 1
                continue
            _zuruck(z, im_korb, ort, dbank, lauf, e)
    if not dry_run:
        for korb in koerbe.values():
            _leere_ordner_entfernen(korb, e)
        dbank.stapel_schreiben()
    e.sekunden = time.monotonic() - begonnen
    return e


def _zuruck(z, im_korb: Path, ort: Path, dbank: db.Datenbank, lauf: int, e: Ergebnis) -> None:
    quellpfad = z["quellpfad"]
    if os.path.lexists(pfade.lang(ort)):
        _belegt(quellpfad, ort, dbank, lauf, e)
        return
    try:
        pfade.lang(ort.parent).mkdir(parents=True, exist_ok=True)
        pfade.umbenennen_ohne_ueberschreiben(im_korb, ort)
        art = ART_ZURUECKGELEGT
    except FileExistsError:
        _belegt(quellpfad, ort, dbank, lauf, e)
        return
    except pfade.KeinNoReplace:
        grund = _zurueckkopieren(im_korb, ort)
        if grund == "belegt":
            _belegt(quellpfad, ort, dbank, lauf, e)
            return
        if grund:
            _fehler(quellpfad, ort, grund, dbank, lauf, e)
            return
        art = ART_KOPIERT
        e.kopiert += 1
    except OSError as fehler:
        _fehler(quellpfad, ort, str(fehler.strerror or fehler), dbank, lauf, e)
        return
    try:
        st = os.stat(pfade.lang(ort))
    except OSError as fehler:   # pragma: no cover - eben angelegt
        _fehler(quellpfad, ort, str(fehler.strerror or fehler), dbank, lauf, e)
        return
    dbank.zurueck_auf_gefunden(quellpfad, st.st_size, st.st_mtime)
    dbank.ereignis(lauf, art, quellpfad, 1, db.pfad_text(im_korb))
    e.zurueckgelegt += 1


def _zurueckkopieren(im_korb: Path, ort: Path) -> str:
    """Exklusiv an den alten Ort kopieren und die Kopie zuruecklesen. Liefert
    "" (gut), "belegt" oder einen Fehlergrund. Eine misslungene Kopie ist die
    eigene, eben exklusiv angelegte Datei - sie wird wieder entfernt; die Datei
    im Ordner _geloescht_ bleibt in jedem Fall."""
    try:
        h, _n = hashes.kopieren_mit_hash(pfade.lang(im_korb), pfade.lang(ort))
    except FileExistsError:
        return "belegt"
    except OSError as fehler:
        return str(fehler.strerror or fehler)
    try:
        h2 = hashes.blake3_datei(pfade.lang(ort))
    except OSError:
        h2 = ""
    if h2 != h:
        try:
            os.unlink(pfade.lang(ort))
        except OSError:
            pass
        return meldungen.GRUND_ZURUECKLEGEN_KOPIE
    try:
        shutil.copystat(pfade.lang(im_korb), pfade.lang(ort))
    except OSError:
        pass
    return ""


def _belegt(quellpfad, ort: Path, dbank, lauf, e: Ergebnis) -> None:
    e.belegt.append(db.pfad_text(ort))
    dbank.ereignis(lauf, ART_BELEGT, quellpfad, 1, meldungen.EREIGNIS_ZURUECKLEGEN_BELEGT)


def _fehler(quellpfad, ort: Path, grund: str, dbank, lauf, e: Ergebnis) -> None:
    e.fehler.append((db.pfad_text(ort), grund))
    dbank.ereignis(lauf, ART_FEHLER, quellpfad, 1, grund)


def _leere_ordner_entfernen(korb: Path, e: Ergebnis) -> None:
    """Leer gewordene Ordner im Ordner _geloescht_ entfernen, von unten nach
    oben; nur Ordner (rmdir scheitert an allem, was nicht leer ist)."""
    if not pfade.lang(korb).is_dir() or pfade.lang(korb).is_symlink():
        return
    for oben, ordner, _dateien in os.walk(pfade.lang(korb), topdown=False):
        for name in ordner:
            pfad = Path(oben) / name
            if pfad.is_symlink():
                continue
            try:
                os.rmdir(pfad)
                e.ordner_entfernt += 1
            except OSError:
                pass
    try:
        os.rmdir(pfade.lang(korb))
        e.ordner_entfernt += 1
    except OSError:
        e.ordner_uebrig.append(db.pfad_text(korb))
