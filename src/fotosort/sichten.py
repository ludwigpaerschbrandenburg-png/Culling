"""Reiter „Sichten“, erster Ausbau (SPEC §8 seit v0.8): Bilder im Archiv
ansehen, mit Sternen bewerten und als Auswahl oder Ausschuss markieren.

Was hier nie geschieht: Eine Datei im Archiv wird weder veraendert noch
verschoben noch geloescht. Ausschuss ist nur eine Markierung. Gelesen wird
nur - Ordnerlisten und, in der Oberflaeche, der Inhalt der Bilder.

Die Bewertungen stehen in einer eigenen kleinen Datenbank (bewertungen.db)
im lokalen Archiv-Ordner, nicht in fotosort.db: Die Hauptdatenbank bleibt
einstraengig (ein Arbeitsprozess schreibt, die Oberflaeche liest nur, wenn
keiner laeuft, §8). So laesst sich auch sichten, waehrend kopiert wird.
Schluessel ist der Pfad der Hauptdatei relativ zum Zielordner, mit "/" -
er bleibt gueltig, wenn das Laufwerk unter einem anderen Buchstaben kommt.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import FotosortFehler, dateitypen, meldungen, pfade

DATEINAME = "bewertungen.db"
MARKIERUNGEN = ("", "auswahl", "ausschuss")
FILTER = ("alle", "auswahl", "ausschuss", "ab1", "ab2", "ab3", "ab4", "ab5")

#: Fotos, die die Oberflaeche selbst lesen kann; alles andere (RAW, HEIC)
#: zeigt sie ueber die eingebettete Vorschau (vorschau.py).
QT_LESBAR = frozenset({"jpg", "jpeg", "jfif", "png", "tif", "tiff", "webp", "bmp", "gif"})

#: Ordner, die nie zum Archiv gehoeren (Systemordner von Windows).
_SYSTEMORDNER = frozenset({"$recycle.bin", "system volume information"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bewertungen (
    schluessel  TEXT PRIMARY KEY,
    sterne      INTEGER NOT NULL DEFAULT 0 CHECK (sterne BETWEEN 0 AND 5),
    markierung  TEXT    NOT NULL DEFAULT '' CHECK (markierung IN ('', 'auswahl', 'ausschuss')),
    geaendert   REAL    NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class Bild:
    """Eine Aufnahme in einem Ordner des Archivs: RAW und JPG gleichen
    Namens sind ein Bild. Bewertet wird die Hauptdatei (RAW vor Foto, wie
    beim Gruppieren), gezeigt die Datei, die sich am schnellsten lesen laesst."""
    schluessel: str
    haupt: Path
    anzeige: Path
    art: str
    dateien: tuple[Path, ...]

    @property
    def name(self) -> str:
        return self.haupt.name


def _verknuepfung(eintrag: os.DirEntry) -> bool:
    """Verknuepfung oder Windows-Junction? Aus den Angaben der Ordnerliste
    (DirEntry.is_junction, Python 3.12) - ohne je Datei die Platte oder das
    Netz zu fragen."""
    try:
        return eintrag.is_symlink() or bool(getattr(eintrag, "is_junction", lambda: False)())
    except OSError:
        return True


def _im_archiv(ordner: Path, ziel: Path) -> None:
    """Nur Ordner innerhalb des Zielordners - nie ueber eine Verknuepfung hinaus."""
    try:
        pfade.aufloesen(Path(ordner)).relative_to(pfade.aufloesen(Path(ziel)))
    except ValueError:
        raise FotosortFehler(meldungen.sichten_ausserhalb(ordner, ziel)) from None
    except OSError as fehler:   # Netzlaufwerk nicht erreichbar
        raise FotosortFehler(meldungen.sichten_nicht_lesbar(ordner, str(fehler.strerror or fehler))) from None


def _eintraege(ordner: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(pfade.lang(Path(ordner))) as it:
            return [e for e in it if not _verknuepfung(e)]
    except OSError:
        return []


def ordner(ziel: Path, eltern: Path | None = None) -> list[Path]:
    """Unterordner: die mit Datum (Vorlage: Jahr, Tag) neueste zuerst, danach
    die uebrigen (_Ohne_Datum, Kameraordner) nach Namen. Ohne Programm- und
    Systemordner, ohne Verknuepfungen."""
    eltern = Path(ziel) if eltern is None else Path(eltern)
    _im_archiv(eltern, ziel)
    namen = []
    for e in _eintraege(eltern):
        if e.name.startswith(".") or e.name.casefold() in _SYSTEMORDNER:
            continue
        try:
            if e.is_dir(follow_symlinks=False):
                namen.append(e.name)
        except OSError:
            continue
    mit_datum = sorted((n for n in namen if n[:1].isdigit()), key=str.casefold, reverse=True)
    uebrige = sorted((n for n in namen if not n[:1].isdigit()), key=lambda n: (n.startswith("_"), n.casefold()))
    return [eltern / n for n in mit_datum + uebrige]


def schluessel(pfad: Path, ziel: Path) -> str:
    return PurePosixPath(*Path(pfad).relative_to(Path(ziel)).parts).as_posix()


def _endung(p: Path) -> str:
    return p.suffix.lower().lstrip(".")


def bilder(ordner_: Path, ziel: Path, konf) -> list[Bild]:
    """Die Bilder eines Ordners (nicht der Unterordner), nach Namen."""
    ordner_ = Path(ordner_)
    _im_archiv(ordner_, ziel)
    typen: dict[Path, str] = {}
    for e in _eintraege(ordner_):
        try:
            if not e.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        typ = dateitypen.typ_von(e.name, konf)
        if typ in (dateitypen.FOTO, dateitypen.RAW, dateitypen.VIDEO):
            typen[ordner_ / e.name] = typ
    # RAW und Foto gleichen Stammnamens sind eine Aufnahme. Videos und weitere
    # Dateien gleichen Namens bleiben eigene Bilder - nichts wird verdeckt.
    fotos: dict[str, list[Path]] = {}
    for p, typ in typen.items():
        if typ == dateitypen.FOTO:
            fotos.setdefault(p.stem.casefold(), []).append(p)
    for liste in fotos.values():
        liste.sort(key=lambda p: (_endung(p) not in QT_LESBAR, p.name.casefold()))
    vergeben: set[Path] = set()
    ergebnis: list[Bild] = []
    for p in sorted((p for p, t in typen.items() if t == dateitypen.RAW), key=lambda p: p.name.casefold()):
        partner = next((f for f in fotos.get(p.stem.casefold(), []) if f not in vergeben), None)
        if partner is not None:
            vergeben.add(partner)
            ergebnis.append(Bild(schluessel(p, ziel), p, partner, dateitypen.FOTO, (p, partner)))
        else:
            ergebnis.append(Bild(schluessel(p, ziel), p, p, dateitypen.RAW, (p,)))
    for p, typ in typen.items():
        if typ != dateitypen.RAW and p not in vergeben:
            ergebnis.append(Bild(schluessel(p, ziel), p, p, typ, (p,)))
    ergebnis.sort(key=lambda b: b.name.casefold())
    return ergebnis


def passt(bewertung: tuple[int, str] | None, filter_: str) -> bool:
    """Zeigt der Filter dieses Bild? bewertung: (Sterne, Markierung) oder None."""
    if filter_ not in FILTER:
        raise FotosortFehler(meldungen.sichten_filter_ungueltig(filter_, FILTER))
    sterne, markierung = bewertung or (0, "")
    if filter_ == "alle":
        return True
    if filter_ in ("auswahl", "ausschuss"):
        return markierung == filter_
    return sterne >= int(filter_[2:])


class Bewertungen:
    """Die Datei bewertungen.db im lokalen Archiv-Ordner. Jede Anfrage oeffnet
    und schliesst die Verbindung: Nichts haelt die Datei offen (Archiv
    verwerfen muss sie unter Windows entfernen koennen)."""

    def __init__(self, archiv_ordner: Path) -> None:
        self.datei = Path(archiv_ordner) / DATEINAME

    @contextlib.contextmanager
    def _verbindung(self):
        try:
            v = sqlite3.connect(str(pfade.lang(self.datei)), timeout=10.0)
        except sqlite3.Error as fehler:
            raise FotosortFehler(meldungen.sichten_datei_fehler(self.datei, str(fehler))) from fehler
        try:
            v.execute("PRAGMA synchronous = NORMAL")
            v.executescript(_SCHEMA)
            with v:
                yield v
        except sqlite3.Error as fehler:
            raise FotosortFehler(meldungen.sichten_datei_fehler(self.datei, str(fehler))) from fehler
        finally:
            v.close()

    def lesen(self, schluessel_: list[str]) -> dict[str, tuple[int, str]]:
        """Nur Bilder mit Bewertung oder Markierung stehen im Ergebnis."""
        if not self.datei.exists():
            return {}
        ergebnis: dict[str, tuple[int, str]] = {}
        with self._verbindung() as v:
            for anfang in range(0, len(schluessel_), 500):
                teil = schluessel_[anfang:anfang + 500]
                for s, sterne, markierung in v.execute(
                    f"SELECT schluessel, sterne, markierung FROM bewertungen WHERE schluessel IN ({','.join('?' * len(teil))})",
                    teil,
                ):
                    ergebnis[s] = (int(sterne), str(markierung))
        return ergebnis

    def setzen(self, schluessel_: list[str], sterne: int | None = None, markierung: str | None = None) -> None:
        if sterne is not None and (isinstance(sterne, bool) or not isinstance(sterne, int) or not 0 <= sterne <= 5):
            raise FotosortFehler(meldungen.sichten_wert_ungueltig(sterne))
        if markierung is not None and markierung not in MARKIERUNGEN:
            raise FotosortFehler(meldungen.sichten_wert_ungueltig(markierung))
        if not schluessel_:
            return
        jetzt = time.time()
        with self._verbindung() as v:
            for s in schluessel_:
                alt = v.execute("SELECT sterne, markierung FROM bewertungen WHERE schluessel = ?", (s,)).fetchone()
                neu_sterne = sterne if sterne is not None else (alt[0] if alt else 0)
                neu_mark = markierung if markierung is not None else (alt[1] if alt else "")
                if neu_sterne == 0 and neu_mark == "":
                    v.execute("DELETE FROM bewertungen WHERE schluessel = ?", (s,))
                else:
                    v.execute(
                        "INSERT INTO bewertungen (schluessel, sterne, markierung, geaendert) VALUES (?, ?, ?, ?)"
                        " ON CONFLICT(schluessel) DO UPDATE SET sterne = excluded.sterne,"
                        " markierung = excluded.markierung, geaendert = excluded.geaendert",
                        (s, neu_sterne, neu_mark, jetzt),
                    )
