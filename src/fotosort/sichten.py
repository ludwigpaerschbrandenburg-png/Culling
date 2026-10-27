"""Reiter „Sichten“ (SPEC §8 seit v0.8, zweiter Ausbau v0.11): Bilder im
Archiv ansehen, mit Sternen bewerten, als Auswahl oder Ausschuss markieren
und mit einer Farbe versehen.

Was hier nie geschieht: Eine vorhandene Datei im Archiv wird weder veraendert
noch verschoben noch geloescht. Ausschuss ist nur eine Markierung. Einzige
Ausnahme vom reinen Lesen (seit v0.11, Entscheidung des Nutzers vom
28.10.2026): Auf Knopfdruck legt xmp_anlegen() NEUE XMP-Dateien mit der
Bewertung an - nur dort, wo zu einem Bild noch keine XMP-Datei liegt, ueber
eine .part-Datei und ein Umbenennen, das nie ueberschreibt.

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
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from . import FotosortFehler, dateitypen, meldungen, pfade

DATEINAME = "bewertungen.db"
MARKIERUNGEN = ("", "auswahl", "ausschuss")
#: Farbmarken wie in Lightroom (Tasten 6-9; Lila nur ueber den Knopf).
FARBEN = ("", "rot", "gelb", "gruen", "blau", "lila")
FILTER = ("alle", "unbewertet", "auswahl", "ausschuss", "ab1", "ab2", "ab3", "ab4", "ab5",
          *(f"farbe_{f}" for f in FARBEN if f))

#: Fotos, die die Oberflaeche selbst lesen kann; alles andere (RAW, HEIC)
#: zeigt sie ueber die eingebettete Vorschau (vorschau.py).
QT_LESBAR = frozenset({"jpg", "jpeg", "jfif", "png", "tif", "tiff", "webp", "bmp", "gif"})
#: Live-Photo: Foto dieses Formats plus .mov gleichen Namens (iPhone).
_LIVE_FOTO = frozenset({"heic", "heif"})
_LIVE_VIDEO = frozenset({"mov"})

#: Ordner, die nie zum Archiv gehoeren (Systemordner von Windows).
_SYSTEMORDNER = frozenset({"$recycle.bin", "system volume information"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bewertungen (
    schluessel  TEXT PRIMARY KEY,
    sterne      INTEGER NOT NULL DEFAULT 0 CHECK (sterne BETWEEN 0 AND 5),
    markierung  TEXT    NOT NULL DEFAULT '' CHECK (markierung IN ('', 'auswahl', 'ausschuss')),
    geaendert   REAL    NOT NULL DEFAULT 0,
    farbe       TEXT    NOT NULL DEFAULT ''
);
"""


class Bewertung(NamedTuple):
    sterne: int = 0
    markierung: str = ""
    farbe: str = ""


def _als_bewertung(wert) -> Bewertung:
    """Bewertung aus None, (Sterne, Markierung) oder (Sterne, Markierung, Farbe)."""
    if not wert:
        return Bewertung()
    teile = tuple(wert) + ("", "")
    return Bewertung(int(teile[0] or 0), str(teile[1] or ""), str(teile[2] or ""))


@dataclass(frozen=True)
class Bild:
    """Eine Aufnahme in einem Ordner des Archivs: RAW und JPG gleichen
    Namens sind ein Bild, ein Live-Photo (HEIC und MOV) auch. Bewertet wird
    die Hauptdatei (RAW vor Foto, wie beim Gruppieren), gezeigt die Datei, die
    sich am schnellsten lesen laesst. xmp: vorhandene XMP-Dateien dazu."""
    schluessel: str
    haupt: Path
    anzeige: Path
    art: str
    dateien: tuple[Path, ...]
    xmp: tuple[Path, ...] = field(default=())

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


def _xmp_zu(haupt: Path, namen: dict[str, str]) -> tuple[Path, ...]:
    """Vorhandene XMP-Dateien einer Aufnahme: "<Stamm>.xmp" (Lightroom, Capture
    One) oder "<Name>.<Endung>.xmp" (darktable), in jeder Schreibweise."""
    stamm = haupt.stem.casefold()
    treffer = [n for k, n in namen.items()
               if k.endswith(".xmp") and (k == stamm + ".xmp" or (k.startswith(stamm + ".") and k.count(".") == stamm.count(".") + 2))]
    return tuple(haupt.parent / n for n in sorted(treffer, key=str.casefold))


def _xmp_vorhanden(haupt: Path, namen: dict[str, str]) -> bool:
    return bool(_xmp_zu(haupt, namen))


def bilder(ordner_: Path, ziel: Path, konf) -> list[Bild]:
    """Die Bilder eines Ordners (nicht der Unterordner), nach Namen."""
    ordner_ = Path(ordner_)
    _im_archiv(ordner_, ziel)
    typen: dict[Path, str] = {}
    namen: dict[str, str] = {}
    for e in _eintraege(ordner_):
        try:
            if not e.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        namen[e.name.casefold()] = e.name
        typ = dateitypen.typ_von(e.name, konf)
        if typ in (dateitypen.FOTO, dateitypen.RAW, dateitypen.VIDEO):
            typen[ordner_ / e.name] = typ
    # RAW und Foto gleichen Stammnamens sind eine Aufnahme. Videos und weitere
    # Dateien gleichen Namens bleiben eigene Bilder - nichts wird verdeckt;
    # nur das Video eines Live-Photos (HEIC + MOV) gehoert zum Foto.
    fotos: dict[str, list[Path]] = {}
    for p, typ in typen.items():
        if typ == dateitypen.FOTO:
            fotos.setdefault(p.stem.casefold(), []).append(p)
    for liste in fotos.values():
        liste.sort(key=lambda p: (_endung(p) not in QT_LESBAR, p.name.casefold()))
    vergeben: set[Path] = set()
    ergebnis: list[Bild] = []

    def bild(haupt: Path, anzeige: Path, art: str, dateien: tuple[Path, ...]) -> Bild:
        return Bild(schluessel(haupt, ziel), haupt, anzeige, art, dateien, _xmp_zu(haupt, namen))

    for p in sorted((p for p, t in typen.items() if t == dateitypen.RAW), key=lambda p: p.name.casefold()):
        partner = next((f for f in fotos.get(p.stem.casefold(), []) if f not in vergeben), None)
        if partner is not None:
            vergeben.add(partner)
            ergebnis.append(bild(p, partner, dateitypen.FOTO, (p, partner)))
        else:
            ergebnis.append(bild(p, p, dateitypen.RAW, (p,)))
    live: dict[str, Path] = {}
    for p, typ in typen.items():
        if typ == dateitypen.VIDEO and _endung(p) in _LIVE_VIDEO:
            live.setdefault(p.stem.casefold(), p)
    for p, typ in sorted(typen.items(), key=lambda x: x[0].name.casefold()):
        if typ != dateitypen.FOTO or p in vergeben:
            continue
        video = live.get(p.stem.casefold()) if _endung(p) in _LIVE_FOTO else None
        if video is not None and video not in vergeben:
            vergeben.add(video)
            ergebnis.append(bild(p, p, dateitypen.FOTO, (p, video)))
        else:
            ergebnis.append(bild(p, p, typ, (p,)))
        vergeben.add(p)
    for p, typ in typen.items():
        if typ != dateitypen.RAW and p not in vergeben:
            ergebnis.append(bild(p, p, typ, (p,)))
    ergebnis.sort(key=lambda b: b.name.casefold())
    return ergebnis


def passt(bewertung, filter_: str) -> bool:
    """Zeigt der Filter dieses Bild? bewertung: Bewertung, (Sterne, Markierung)
    oder None."""
    if filter_ not in FILTER:
        raise FotosortFehler(meldungen.sichten_filter_ungueltig(filter_, FILTER))
    b = _als_bewertung(bewertung)
    if filter_ == "alle":
        return True
    if filter_ == "unbewertet":
        return b.sterne == 0 and b.markierung == ""
    if filter_ in ("auswahl", "ausschuss"):
        return b.markierung == filter_
    if filter_.startswith("farbe_"):
        return b.farbe == filter_[len("farbe_"):]
    return b.sterne >= int(filter_[2:])


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
            spalten = {z[1] for z in v.execute("PRAGMA table_info(bewertungen)")}
            if "farbe" not in spalten:
                # Datei aus v0.8 bis v0.10: Farbe kam in v0.11 dazu.
                v.execute("ALTER TABLE bewertungen ADD COLUMN farbe TEXT NOT NULL DEFAULT ''")
            with v:
                yield v
        except sqlite3.Error as fehler:
            raise FotosortFehler(meldungen.sichten_datei_fehler(self.datei, str(fehler))) from fehler
        finally:
            v.close()

    def lesen(self, schluessel_: list[str]) -> dict[str, Bewertung]:
        """Nur Bilder mit Bewertung, Markierung oder Farbe stehen im Ergebnis."""
        if not self.datei.exists():
            return {}
        ergebnis: dict[str, Bewertung] = {}
        with self._verbindung() as v:
            for anfang in range(0, len(schluessel_), 500):
                teil = schluessel_[anfang:anfang + 500]
                for s, sterne, markierung, farbe in v.execute(
                    "SELECT schluessel, sterne, markierung, farbe FROM bewertungen"
                    f" WHERE schluessel IN ({','.join('?' * len(teil))})",
                    teil,
                ):
                    ergebnis[s] = Bewertung(int(sterne), str(markierung), str(farbe))
        return ergebnis

    def alle(self) -> dict[str, Bewertung]:
        if not self.datei.exists():
            return {}
        with self._verbindung() as v:
            return {s: Bewertung(int(st), str(m), str(f))
                    for s, st, m, f in v.execute("SELECT schluessel, sterne, markierung, farbe FROM bewertungen")}

    def setzen(self, schluessel_: list[str], sterne: int | None = None, markierung: str | None = None,
               farbe: str | None = None) -> None:
        if sterne is not None and (isinstance(sterne, bool) or not isinstance(sterne, int) or not 0 <= sterne <= 5):
            raise FotosortFehler(meldungen.sichten_wert_ungueltig(sterne))
        if markierung is not None and markierung not in MARKIERUNGEN:
            raise FotosortFehler(meldungen.sichten_wert_ungueltig(markierung))
        if farbe is not None and farbe not in FARBEN:
            raise FotosortFehler(meldungen.sichten_wert_ungueltig(farbe))
        if not schluessel_:
            return
        jetzt = time.time()
        with self._verbindung() as v:
            for s in schluessel_:
                alt = v.execute("SELECT sterne, markierung, farbe FROM bewertungen WHERE schluessel = ?", (s,)).fetchone()
                neu = Bewertung(sterne if sterne is not None else (alt[0] if alt else 0),
                                markierung if markierung is not None else (alt[1] if alt else ""),
                                farbe if farbe is not None else (alt[2] if alt else ""))
                if neu == Bewertung():
                    v.execute("DELETE FROM bewertungen WHERE schluessel = ?", (s,))
                else:
                    v.execute(
                        "INSERT INTO bewertungen (schluessel, sterne, markierung, farbe, geaendert) VALUES (?, ?, ?, ?, ?)"
                        " ON CONFLICT(schluessel) DO UPDATE SET sterne = excluded.sterne,"
                        " markierung = excluded.markierung, farbe = excluded.farbe, geaendert = excluded.geaendert",
                        (s, *neu, jetzt),
                    )


# -- XMP (seit v0.11) ----------------------------------------------------------------

#: Farbnamen in XMP-Dateien (xmp:Label): englisch wie Lightroom, Bridge und
#: darktable sie schreiben, dazu die deutschen Namen eines deutschen Lightroom.
_LABEL_LESEN = {
    "red": "rot", "rot": "rot", "yellow": "gelb", "gelb": "gelb", "green": "gruen", "grün": "gruen",
    "gruen": "gruen", "blue": "blau", "blau": "blau", "purple": "lila", "lila": "lila", "violett": "lila",
}
_LABEL_SCHREIBEN = {"rot": "Red", "gelb": "Yellow", "gruen": "Green", "blau": "Blue", "lila": "Purple"}
_RATING = re.compile(r"""xmp:Rating\s*(?:=\s*["']\s*(-?\d+)\s*["']|>\s*(-?\d+)\s*<)""")
_LABEL = re.compile(r"""xmp:Label\s*(?:=\s*["']([^"'<>]*)["']|>([^<]*)<)""")
_XMP_HOECHSTENS = 1024 * 1024


def xmp_lesen(datei: Path) -> Bewertung | None:
    """Sterne, Ausschuss (Rating -1) und Farbe aus einer XMP-Datei - nur
    lesend; None, wenn darin nichts davon steht oder sie nicht lesbar ist."""
    try:
        with open(pfade.lang(Path(datei)), "rb") as f:
            text = f.read(_XMP_HOECHSTENS).decode("utf-8", errors="replace")
    except OSError:
        return None
    sterne, markierung, farbe = 0, "", ""
    m = _RATING.search(text)
    if m:
        wert = int(m.group(1) or m.group(2))
        if wert < 0:
            markierung = "ausschuss"
        elif 1 <= wert <= 5:
            sterne = wert
    m = _LABEL.search(text)
    if m:
        farbe = _LABEL_LESEN.get((m.group(1) or m.group(2) or "").strip().casefold(), "")
    b = Bewertung(sterne, markierung, farbe)
    return b if b != Bewertung() else None


def xmp_text(b: Bewertung) -> str:
    """Eine kleine XMP-Datei mit Bewertung und Farbe (Adobe-Schreibweise).
    Ausschuss ist Rating -1 wie in Lightroom; "Auswahl" kennt XMP nicht."""
    rating = -1 if b.markierung == "ausschuss" else b.sterne
    label = f' xmp:Label="{_LABEL_SCHREIBEN[b.farbe]}"' if b.farbe else ""
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="fotosort">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        f'  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="{rating}"{label}/>\n'
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>\n'
    )


@dataclass
class XmpErgebnis:
    neu: int = 0            # neu angelegt
    vorhanden: int = 0      # es lag schon eine XMP-Datei da - nicht angefasst
    ohne: int = 0           # nur "Auswahl": in XMP nicht darstellbar
    fehlt: int = 0          # Bild nicht mehr da
    fehler: int = 0
    gruende: list[str] = field(default_factory=list)


def _im_ziel(ziel: Path, schluessel_: str) -> Path | None:
    """Der Pfad eines Schluessels - nur, wenn er sicher im Zielordner liegt."""
    teile = PurePosixPath(schluessel_).parts
    if not teile or PurePosixPath(schluessel_).is_absolute() or any(t in ("..", "") for t in teile):
        return None
    pfad = Path(ziel).joinpath(*teile)
    try:
        pfade.aufloesen(pfad.parent).relative_to(pfade.aufloesen(Path(ziel)))
    except (ValueError, OSError):
        return None
    return pfad


def _neu_schreiben(datei: Path, inhalt: bytes) -> bool:
    """Neue Datei ueber eine .part-Datei und ein Umbenennen, das nie
    ueberschreibt. False: Unter dem Namen liegt inzwischen etwas - es bleibt."""
    part = datei.with_name(datei.name + ".part")
    with open(pfade.lang(part), "xb") as f:      # nie eine vorhandene Datei
        f.write(inhalt)
        f.flush()
        os.fsync(f.fileno())
    try:
        pfade.umbenennen_ohne_ueberschreiben(part, datei)
        return True
    except FileExistsError:
        pfade.lang(part).unlink()                  # nur die eigene, eben angelegte .part
        return False
    except pfade.KeinNoReplace:
        # Dateisystem ohne sicheres Umbenennen (exFAT): exklusiv anlegen.
        try:
            with open(pfade.lang(datei), "xb") as f:
                f.write(inhalt)
                f.flush()
                os.fsync(f.fileno())
            return True
        except FileExistsError:
            return False
        finally:
            pfade.lang(part).unlink()
    except OSError:
        with contextlib.suppress(OSError):
            pfade.lang(part).unlink()
        raise


def xmp_anlegen(ziel: Path, bew: Bewertungen, konf, nur: list[str] | None = None) -> XmpErgebnis:
    """Fuer jedes bewertete Bild eine XMP-Datei "<Stamm>.xmp" neben der
    Hauptdatei anlegen - nur, wo zu diesem Bild noch keine liegt (in keiner
    Schreibweise, auch nicht "<Name>.<Endung>.xmp"). Vorhandene Dateien
    werden nie angefasst. nur: diese Schluessel (sonst alle bewerteten)."""
    e = XmpErgebnis()
    eintraege = bew.alle()
    if nur is not None:
        eintraege = {s: eintraege[s] for s in nur if s in eintraege}
    je_ordner: dict[Path, list[tuple[Path, Bewertung]]] = {}
    for s, b in sorted(eintraege.items()):
        pfad = _im_ziel(ziel, s)
        if pfad is None:
            e.fehler += 1
            continue
        je_ordner.setdefault(pfad.parent, []).append((pfad, b))
    for ordner_, liste in je_ordner.items():
        namen = {x.name.casefold(): x.name for x in _eintraege(ordner_)}
        for haupt, b in liste:
            if haupt.name.casefold() not in namen:
                e.fehlt += 1
                continue
            if b.sterne == 0 and b.farbe == "" and b.markierung != "ausschuss":
                e.ohne += 1
                continue
            if _xmp_vorhanden(haupt, namen):
                e.vorhanden += 1
                continue
            datei = haupt.with_name(haupt.stem + ".xmp")
            try:
                if _neu_schreiben(datei, xmp_text(b).encode("utf-8")):
                    e.neu += 1
                    namen[datei.name.casefold()] = datei.name
                else:
                    e.vorhanden += 1
            except OSError as fehler:
                e.fehler += 1
                e.gruende.append(f"{datei}: {fehler.strerror or fehler}")
    return e
