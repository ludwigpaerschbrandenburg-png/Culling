"""Zielpfad berechnen (SPEC Abschnitt 3, "Zielstruktur").

Ordner-Vorlage anwenden, bestehende Ordner mit Zusatz wiederverwenden
(z. B. "2026-01-01 Geburtstag Oma"), Originaldateinamen beibehalten. Der
Anhang _1, _2 bei Namenskonflikten ist Sache von Phase 3 (SPEC Abschnitt 5).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import datum as datum_modul
from . import kamera as kamera_modul
from . import pfade, strukturen

#: Dateien, die nicht als "hier liegen schon Bilder" zaehlen.
_KEINE_BILDER = frozenset({"thumbs.db", "desktop.ini", ".ds_store"})

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
    flach: bool = False     # Bilder direkt in einen vorhandenen Datumsordner (Schema des Archivs, v0.9)


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
            teil = stueck.format(**werte)
        except (KeyError, IndexError, ValueError):
            teil = stueck
        teil = kamera_modul.windows_sicher(teil)
        if teil:
            teile.append(teil)
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
        self._mit_dateien: dict[Path, bool] = {}
        self._mit_bildern: dict[Path, bool] = {}

    def _ordner_in(self, eltern: Path) -> list[str]:
        if eltern not in self._inhalt:
            namen: list[str] = []
            dateien = False
            bilder = False
            try:
                with os.scandir(pfade.lang(eltern)) as es:
                    for e in es:
                        try:
                            if e.is_dir(follow_symlinks=True):
                                namen.append(e.name)
                            elif not e.name.startswith(".") and e.name.casefold() not in _KEINE_BILDER:
                                dateien = True
                                if not bilder and _bildendung(e.name):
                                    bilder = True
                        except OSError:
                            continue
            except OSError:
                pass
            self._inhalt[eltern] = sorted(namen)
            self._mit_dateien[eltern] = dateien
            self._mit_bildern[eltern] = bilder
        return self._inhalt[eltern]

    def hat_dateien(self, ordner: Path) -> bool:
        """Liegen in diesem Ordner schon Dateien direkt drin (nicht nur Unterordner)?"""
        self._ordner_in(ordner)
        return self._mit_dateien.get(ordner, False)

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

    def finden(self, teile: list[str], zusatz_erlaubt: list[bool] | None = None,
               tag: date | None = None) -> Zielort:
        """Den Zielordner bestimmen; vorhandene Ordner mit Zusatz vorziehen.

        zusatz_erlaubt: je Ebene, ob ein Ordner mit Zusatz benutzt werden
        darf (Datumsebenen). Ohne Angabe gilt es fuer alle Ebenen.

        tag (seit v0.9): das Datum der Datei. Damit werden auch vorhandene
        Ordner in anderer Schreibweise benutzt ("2021.01", "01.2021",
        "Januar 2021", "01" unter "2021"; strukturen.py) - auch ein feinerer
        Ordner direkt auf dieser Ebene ("20210115 Hochzeit" im Archiv selbst).
        Danach entfallen Datumsebenen der Vorlage, die er schon abdeckt; und
        liegen in ihm schon Bilder direkt drin, ist das das Schema dieses
        Archivs: Die Datei kommt dazu, ohne weitere Unterordner.
        """
        aktuell = self.ziel
        mehrdeutig = False
        wiederverwendet = False
        erlaubt_je = [True if zusatz_erlaubt is None or i >= len(zusatz_erlaubt) else zusatz_erlaubt[i]
                      for i in range(len(teile))]
        # Der Zeitraum, den jede Datumsebene der Vorlage meint (im Zusammenhang).
        soll: list[strukturen.Zeitraum | None] = []
        z_vorher: strukturen.Zeitraum | None = None
        for i, teil in enumerate(teile):
            z = strukturen.zeitraum(teil, z_vorher) if erlaubt_je[i] else None
            soll.append(z)
            if z is not None:
                z_vorher = z
        z_aktuell: strukturen.Zeitraum | None = None   # Zeitraum des Ordners, in dem wir stehen
        flach = False
        i = 0
        while i < len(teile):
            gewuenscht = teile[i]
            erlaubt = erlaubt_je[i]
            vorhanden = self._ordner_in(aktuell)
            # Verglichen in einer Unicode-Form (NFC): macOS-Freigaben liefern
            # "März" zerlegt (NFD) - sonst entstuende ein zweiter, gleich
            # aussehender Ordner. Benutzt wird der vorhandene Name, wie er ist.
            gleich = _nfc(gewuenscht)
            name = next((n for n in vorhanden if n == gewuenscht or _nfc(n) == gleich), None)
            if name is None:
                # Auch ohne Gross-/Kleinschreibung (seit v0.8, wie bei Dateinamen):
                # "CANON EOS 5D" landet im vorhandenen "Canon EOS 5D" - zwei
                # Ordner, die sich nur darin unterscheiden, waeren ueber SMB
                # unter Windows nicht beide erreichbar.
                name = next((n for n in sorted(vorhanden) if _nfc(n).casefold() == gleich.casefold()), None)
            vorhanden_genutzt = name is not None
            if name is None and erlaubt:
                kandidaten = [n for n in vorhanden if self.passt(_nfc(n), gleich)]
                if tag is not None and soll[i] is not None:
                    # Seit v0.11: Ein Ordner "mit Zusatz" muss auch als Datum
                    # dasselbe meinen - "2021_01" oder "2021 Januar" ist ein
                    # Monat, kein Jahresordner "2021" mit Zusatz; ein
                    # Jahresbereich ("2021 - 2022 Schule") gar kein Datum.
                    kandidaten = [n for n in kandidaten
                                  if (z := strukturen.zeitraum(_nfc(n), z_aktuell)) is not None
                                  and z.rang == soll[i].rang and z.umfasst(tag)]
                if kandidaten:
                    if len(kandidaten) > 1:
                        mehrdeutig = True
                    name = sorted(kandidaten)[0]
                    wiederverwendet = vorhanden_genutzt = True
            if name is None and erlaubt and tag is not None and soll[i] is not None:
                name, mehr = self._nach_datum(vorhanden, z_aktuell, soll[i], tag)
                if name is not None:
                    mehrdeutig = mehrdeutig or mehr
                    wiederverwendet = vorhanden_genutzt = True
            if name is None:
                name = gewuenscht
            aktuell = aktuell / name
            if erlaubt:
                z_neu = strukturen.zeitraum(name, z_aktuell)
                if z_neu is not None:
                    z_aktuell = z_neu
            i += 1
            if z_aktuell is not None and tag is not None and z_aktuell.umfasst(tag):
                # Datumsebenen, die dieser Ordner schon abdeckt, entfallen.
                while i < len(teile) and soll[i] is not None and soll[i].rang <= z_aktuell.rang:
                    i += 1
                if vorhanden_genutzt and z_aktuell.rang >= 2 and self.flach(aktuell, z_aktuell):
                    flach = True
                    break   # Schema dieses Archivs: Bilder direkt im Monats- oder Tagesordner
        return Zielort(aktuell, mehrdeutig=mehrdeutig, wiederverwendet=wiederverwendet, flach=flach)

    def flach(self, ordner: Path, z: "strukturen.Zeitraum") -> bool:
        """Legt dieses Archiv Bilder direkt in den Datumsordner? Nur, wenn darin
        Foto-, RAW- oder Videodateien liegen (nicht irgendeine Datei) und kein
        Unterordner selbst ein Datum nennt (sonst gilt dessen Ordnung)."""
        if not self.hat_dateien(ordner):
            return False
        if any(strukturen.zeitraum(n, z) is not None for n in self._ordner_in(ordner)):
            return False
        return self._mit_bildern.get(ordner, False)

    def _nach_datum(self, vorhanden: list[str], eltern: "strukturen.Zeitraum | None",
                    soll: "strukturen.Zeitraum", tag: date) -> tuple[str | None, bool]:
        """Ein vorhandener Ordner, der das Datum der Datei nennt - in gleicher
        Feinheit wie die Vorlagenebene (bevorzugt) oder feiner. (Name, mehrdeutig)."""
        passende: list[tuple[int, str]] = []
        for n in vorhanden:
            z = strukturen.zeitraum(n, eltern)
            if z is None or not z.umfasst(tag) or z.rang < soll.rang:
                continue
            if z.art == "jahr" and _nfc(n).strip() != f"{z.jahr:04d}":
                continue   # "2001 Odyssee" ist kein anders geschriebener Jahresordner
            passende.append((z.rang, n))
        if not passende:
            return None, False
        bester = min(r for r, _n in passende)
        namen = sorted(n for r, n in passende if r == bester)
        return namen[0], len(namen) > 1


def _bildendung(name: str) -> bool:
    """Foto, RAW oder Video nach der Standardliste (config.py) - nur fuer die
    Frage, ob ein Ordner schon Bilder enthaelt."""
    from . import config
    global _ENDUNGEN
    if _ENDUNGEN is None:
        k = config.Konfiguration()
        _ENDUNGEN = frozenset(str(e).lower().lstrip(".") for g in ("foto", "raw", "video")
                              for e in k.wert(f"dateitypen.{g}"))
    stelle = name.rfind(".")
    return stelle > 0 and name[stelle + 1:].lower() in _ENDUNGEN


_ENDUNGEN: frozenset[str] | None = None


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def zielpfad(struktur: Zielstruktur, d: datum_modul.Datum, kamera: str, name: str, konf) -> tuple[Path, Zielort]:
    """Vollstaendiger Zielpfad einer Datei (Ordner plus Originalname)."""
    vorlage, tag = _vorlage_fuer(d, konf)
    teile = teile_aus_vorlage(vorlage, tag, kamera)
    ort = struktur.finden(teile, zusatz_ebenen(vorlage), tag)
    return ort.ordner / name, ort


def zeit_text(zeit: datetime | None, uhrzeit_bekannt: bool = True) -> str:
    """Aufnahmezeit fuer die Datenbank. Ohne bekannte Uhrzeit nur das Datum
    ("2026-01-02"), damit sich spaeter erkennen laesst, dass die Tagesgrenze
    nicht anzuwenden ist (SPEC Abschnitt 3)."""
    if zeit is None:
        return ""
    if not uhrzeit_bekannt:
        return zeit.strftime("%Y-%m-%d")
    return zeit.strftime("%Y-%m-%dT%H:%M:%S")


def zeit_aus_text(text: str) -> tuple[datetime | None, bool]:
    """Umkehrung von zeit_text: (Zeit, Uhrzeit bekannt)."""
    if not text:
        return None, True
    if "T" in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S"), True
    return datetime.strptime(text, "%Y-%m-%d"), False
