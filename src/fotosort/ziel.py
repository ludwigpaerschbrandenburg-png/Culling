"""Zielpfad berechnen (SPEC Abschnitt 3, "Zielstruktur").

Ordner-Vorlage anwenden, bestehende Ordner mit Zusatz wiederverwenden
(z. B. "2026-01-01 Geburtstag Oma"), Originaldateinamen beibehalten. Der
Anhang _1, _2 bei Namenskonflikten ist Sache von Phase 3 (SPEC Abschnitt 5).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import datum as datum_modul
from . import pfade

MONATSNAMEN = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)

# Der Datumsanteil am Anfang eines Ordnernamens: 2026, 2026-01, 2026-01-01
_DATUMSANFANG = re.compile(r"^(\d{4}(?:-\d{2}(?:-\d{2})?)?)")
_TRENNER = " _-"


@dataclass
class Zielort:
    ordner: Path            # der Zielordner (ohne Dateiname)
    mehrdeutig: bool = False  # mehrere passende Ordner mit Zusatz, alphabetisch gewaehlt
    wiederverwendet: bool = False  # ein vorhandener Ordner mit Zusatz wurde benutzt


def teile_aus_vorlage(vorlage: str, tag: date | None, kamera: str) -> list[str]:
    """Die Vorlage in Ordner-Teile umsetzen."""
    werte = {"kamera": kamera}
    if tag is not None:
        werte.update(
            jahr=f"{tag.year:04d}",
            monat=f"{tag.month:02d}",
            tag=f"{tag.day:02d}",
            monatsname=MONATSNAMEN[tag.month - 1],
        )
    teile: list[str] = []
    for stueck in str(vorlage).replace("\\", "/").split("/"):
        stueck = stueck.strip()
        if not stueck:
            continue
        try:
            teile.append(stueck.format(**werte))
        except (KeyError, IndexError, ValueError):
            teile.append(stueck)
    return teile


def _vorlage_fuer(d: datum_modul.Datum, konf) -> tuple[str, "date | None"]:
    verhalten = str(konf.wert("datum.unsicheres_datum") or "ohne_datum")
    if d.zeit is None or (not d.sicher and verhalten != "mtime"):
        return str(konf.wert("ordner.vorlage_ohne_datum")), None
    tag = datum_modul.tagesdatum(d.zeit, konf.wert("datum.tagesgrenze"), d.uhrzeit_bekannt)
    return str(konf.wert("ordner.vorlage")), tag


def ordner_teile(d: datum_modul.Datum, kamera: str, konf) -> list[str]:
    """Ordner-Teile fuer eine Datei nach Datum und Konfiguration."""
    vorlage, tag = _vorlage_fuer(d, konf)
    return teile_aus_vorlage(vorlage, tag, kamera)


def zusatz_ebenen(vorlage: str) -> list[bool]:
    """Je Vorlagenteil: darf ein vorhandener Ordner mit Zusatz benutzt werden?

    SPEC Abschnitt 3 kennt den Zusatz nur fuer Tages-, Monats- und
    Jahresordner. Auf der Kamera-Ebene zaehlt nur der exakte Name - sonst
    landeten "iPhone 15"-Bilder im Ordner "iPhone 15 Pro".
    """
    return [
        any(feld in stueck for feld in ("{jahr}", "{monat}", "{tag}"))
        for stueck in str(vorlage).replace("\\", "/").split("/")
        if stueck.strip()
    ]


class Zielstruktur:
    """Kennt die vorhandenen Ordner im Ziel und findet passende mit Zusatz.

    Je Elternordner wird das Verzeichnis einmal gelesen und gemerkt.
    """

    def __init__(self, ziel: Path) -> None:
        self.ziel = pfade.aufloesen(Path(ziel))
        self._inhalt: dict[Path, list[str]] = {}

    def _ordner_in(self, eltern: Path) -> list[str]:
        if eltern not in self._inhalt:
            try:
                with os.scandir(pfade.lang(eltern)) as es:
                    namen = sorted(e.name for e in es if e.is_dir(follow_symlinks=True))
            except OSError:
                namen = []
            self._inhalt[eltern] = namen
        return self._inhalt[eltern]

    def vermerken(self, eltern: Path, name: str) -> None:
        """Einen (spaeter) angelegten Ordner in den Cache aufnehmen."""
        liste = self._ordner_in(eltern)
        if name not in liste:
            liste.append(name)
            liste.sort()

    @staticmethod
    def passt(vorhanden: str, gewuenscht: str) -> bool:
        """Beginnt der vorhandene Ordner mit dem gewuenschten Namen (plus Zusatz)?"""
        if vorhanden == gewuenscht:
            return True
        if vorhanden.startswith(gewuenscht) and len(vorhanden) > len(gewuenscht):
            rest = vorhanden[len(gewuenscht):]
            # "2026-01 Januar" ist kein Jahresordner "2026" mit Zusatz: Ein
            # Bindestrich gefolgt von einer Ziffer setzt das Datum fort.
            if rest[0] in _TRENNER and not (rest[0] == "-" and rest[1:2].isdigit()):
                return True
        m = _DATUMSANFANG.match(gewuenscht)
        if m:
            anfang = m.group(1)
            if vorhanden.startswith(anfang) and len(vorhanden) > len(anfang):
                rest = vorhanden[len(anfang):]
                # Ein Jahresordner "2026" darf keinen Monatsordner "2026-01 ..."
                # einfangen: nach dem Datumsanteil kommt Leerzeichen oder "_".
                if rest[0] in " _":
                    return True
        return False

    def finden(self, teile: list[str], zusatz_erlaubt: list[bool] | None = None) -> Zielort:
        """Den Zielordner bestimmen; vorhandene Ordner mit Zusatz vorziehen.

        zusatz_erlaubt: je Ebene, ob ein Ordner mit Zusatz benutzt werden
        darf (Datumsebenen). Ohne Angabe gilt es fuer alle Ebenen.
        """
        aktuell = self.ziel
        mehrdeutig = False
        wiederverwendet = False
        for i, gewuenscht in enumerate(teile):
            vorhanden = self._ordner_in(aktuell)
            if gewuenscht in vorhanden:
                aktuell = aktuell / gewuenscht
                continue
            erlaubt = True if zusatz_erlaubt is None or i >= len(zusatz_erlaubt) else zusatz_erlaubt[i]
            kandidaten = [n for n in vorhanden if self.passt(n, gewuenscht)] if erlaubt else []
            if not kandidaten:
                aktuell = aktuell / gewuenscht
                continue
            if len(kandidaten) > 1:
                mehrdeutig = True
            gewaehlt = sorted(kandidaten)[0]
            wiederverwendet = True
            aktuell = aktuell / gewaehlt
        return Zielort(aktuell, mehrdeutig=mehrdeutig, wiederverwendet=wiederverwendet)


def zielpfad(struktur: Zielstruktur, d: datum_modul.Datum, kamera: str, name: str, konf) -> tuple[Path, Zielort]:
    """Vollstaendiger Zielpfad einer Datei (Ordner plus Originalname)."""
    vorlage, tag = _vorlage_fuer(d, konf)
    teile = teile_aus_vorlage(vorlage, tag, kamera)
    ort = struktur.finden(teile, zusatz_ebenen(vorlage))
    return ort.ordner / name, ort


def zeit_text(zeit: datetime | None) -> str:
    return "" if zeit is None else zeit.strftime("%Y-%m-%dT%H:%M:%S")
