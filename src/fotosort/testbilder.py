"""Testbilder: ein grosser kuenstlicher Testsatz mit beschrifteten Bildern
(Phase 13, Wunsch des Nutzers vom 28.10.2026: Testbilder mit verschiedenen
Daten und Geraeten; auf jedem Bild steht, was es ist und wo es landen soll).

Nie echte Fotos (CLAUDE.md): Jede Datei entsteht hier aus Code. Qt zeichnet
die Bilder; auf jedem steht Dateityp, Geraet, Aufnahmezeit, der erwartete
Platz im Archiv und warum. RAW- und HEIC-Dateien tragen dieselbe Beschriftung
als eingebettetes Vorschaubild (Reiter „Sichten“), Videos als Standbild.

erzeugen(ordner) legt an:
  Quelle/                     die unsortierten Testbilder (Standard: 5000)
  Ziel/                       ein vorbelegtes Archiv: andere Schreibweisen,
                              Zusaetze, flache Ordner, schon importierte Bilder,
                              belegte Namen
  Übersicht.html, Erwartung.csv, LIESMICH.txt
  .fotosort_testbilder.json   die Erwartung je Datei fuer pruefen()
  .fotosort_testbaum          Marke: kuenstlicher Testbaum (SPEC §11)

Die Erwartung wird hier aus den Regeln der SPEC (§3) berechnet - bewusst
nicht mit den Funktionen des Programms (datum.py, kamera.py, ziel.py): Sonst
bestaetigte sich das Programm nur selbst.

pruefen(ordner) vergleicht nach dem Sortieren das Ziel mit der Erwartung -
ueber die Dateien selbst (BLAKE3), nicht ueber die Datenbank - und stellt
fest, dass kein Inhalt verloren ging.

Angelegt wird nur Neues, jede Datei exklusiv ("xb"). Es wird nie etwas
ueberschrieben oder geloescht.
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import random
import subprocess
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import FotosortFehler, __version__, hashes, meldungen, pfade, prozesse
from . import testbilder_formate as formate

FORMAT = 1
MARKE = ".fotosort_testbilder.json"
TESTBAUM_MARKE = ".fotosort_testbaum"     # wie oberflaeche/desktop.py (--durchlauf)
QUELLE, ZIEL = "Quelle", "Ziel"
STANDARD_ANZAHL = 5000
MINDESTANZAHL = 300
SAAT = 20261028
HEIMAT = ZoneInfo("Europe/Berlin")
ENDE = date(2026, 9, 30)                  # juengstes Aufnahmedatum im Testsatz
UNBEKANNT = "Unbekannte_Kamera"
OHNE_DATUM = "_Ohne_Datum"

ARCHIV, DOPPELT, SCHON, BLEIBT, VORBELEGT = "archiv", "doppelt", "schon_im_archiv", "bleibt", "vorbelegt"

MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember")

#: Die Alias-Tabelle aus SPEC §9 (Standard der config.toml) - hier abgeschrieben,
#: nicht aus config.py geholt: Die Erwartung soll unabhaengig entstehen.
ALIASE = {k.lower(): v for k, v in {
    "ILCE-7CM2": "A7C2", "ILCE-7C": "A7C",
    "Noritsu Koki QSS-32_33": "Analog", "Noritsu Koki EZ Controller": "Analog",
    "SP-3000": "Analog", "Frontier SP-3000": "Analog", "Frontier SP-500": "Analog",
    "EPSON Perfection V600": "Analog", "EPSON Perfection V800": "Analog", "EPSON Perfection V850": "Analog",
    "PLUSTEK OpticFilm 8200i": "Analog", "PLUSTEK OpticFilm 120": "Analog",
}.items()}

_WINDOWS_GERAETE = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_RESTE = {"thumbs.db", ".ds_store", "desktop.ini"}

#: Monate und Tage, fuer die das vorbelegte Archiv eigene Ordner hat - Zufallsdaten meiden sie.
_RESERVIERT_MONATE = {(2019, 7), (2020, 8), (2021, 1), (2022, 3), (2018, 6), (2024, 2)}
_RESERVIERT_TAGE = {date(2023, 5, 20), date(2023, 6, 10), date(2024, 3, 2), date(2019, 4, 1)}


class Abgebrochen(FotosortFehler):
    """Erzeugen oder Pruefen wurde angehalten (Fenster zu, Strg+C)."""


# ------------------------------------------------------------- Geraete ----


@dataclass(frozen=True)
class Geraet:
    kennung: str
    make: str
    model: str
    ordner: str             # erwarteter Kameraordner (SPEC §3)
    alias: bool             # kommt aus der Alias-Liste
    von: int                # Jahre, in denen es Bilder macht
    bis: int
    quelle: str             # Ordner unter Quelle
    unterordner: str        # "{n}MSDCF" (n ab 100, je 500 Bilder einer) oder fester Name
    muster: str             # Dateiname: Format mit {z} oder "datum:<strftime>" oder "pxl"
    endung: str = ".JPG"
    raw: str = ""
    farbe: str = "#3b6ea5"
    objektiv: str = ""
    brennweite: int = 35

    @property
    def text(self) -> str:
        """Wie Hersteller und Modell in der Datei stehen, zum Lesen."""
        erstes = self.make.split()[0].lower() if self.make else ""
        if not self.make or self.model.lower().startswith(erstes):
            return self.model
        return f"{self.make} {self.model}"


_G = (
    Geraet("a7c2", "SONY", "ILCE-7CM2", "A7C2", True, 2023, 2026, "Kamera Sony A7C II/DCIM", "{n}MSDCF",
           "DSC{z:05d}", ".JPG", ".ARW", "#2f6f9f", "FE 28-60mm F4-5.6", 35),
    Geraet("a7c", "SONY", "ILCE-7C", "A7C", True, 2020, 2024, "Kamera Sony A7C/DCIM", "{n}MSDCF",
           "DSC{z:05d}", ".JPG", ".ARW", "#3f86b8", "FE 28-60mm F4-5.6", 28),
    Geraet("a7r4", "SONY", "ILCE-7RM4", "ILCE-7RM4", False, 2019, 2024, "Kamera Sony A7R IV/DCIM", "{n}MSDCF",
           "DSC{z:05d}", ".JPG", ".ARW", "#1d567f", "FE 24-105mm F4 G OSS", 50),
    Geraet("r5", "Canon", "Canon EOS R5", "Canon EOS R5", False, 2020, 2026, "Kamera Canon EOS R5/DCIM", "{n}EOSR5",
           "IMG_{z:04d}", ".JPG", "", "#a8323a", "RF24-105mm F4 L IS USM", 70),
    Geraet("5d4", "Canon", "Canon EOS 5D Mark IV", "Canon EOS 5D Mark IV", False, 2016, 2023,
           "Kamera Canon 5D Mark IV/DCIM", "{n}CANON", "IMG_{z:04d}", ".JPG", ".CR2", "#8c2a31", "EF24-70mm f/2.8L II USM", 50),
    Geraet("ixus", "Canon", "Canon IXUS 70", "Canon IXUS 70", False, 2007, 2011, "Alte Kamera Canon IXUS/DCIM",
           "{n}CANON", "IMG_{z:04d}", ".JPG", "", "#b8545b", "", 6),
    Geraet("z62", "NIKON CORPORATION", "NIKON Z 6_2", "NIKON Z 6_2", False, 2021, 2026, "Kamera Nikon Z6 II/DCIM",
           "{n}NZ6_2", "DSC_{z:04d}", ".JPG", ".NEF", "#c99a06", "NIKKOR Z 24-70mm f/4 S", 24),
    Geraet("d750", "NIKON CORPORATION", "NIKON D750", "NIKON D750", False, 2015, 2021, "Kamera Nikon D750/DCIM",
           "{n}ND750", "DSC_{z:04d}", ".JPG", ".NEF", "#a8800a", "AF-S NIKKOR 24-120mm f/4G ED VR", 85),
    Geraet("xt5", "FUJIFILM", "X-T5", "X-T5", False, 2022, 2026, "Kamera Fujifilm X-T5/DCIM", "{n}_FUJI",
           "DSCF{z:04d}", ".JPG", "", "#2e7d4f", "XF16-80mmF4 R OIS WR", 23),
    Geraet("em10", "OLYMPUS CORPORATION", "E-M10MarkII", "E-M10MarkII", False, 2015, 2020, "Kamera Olympus/DCIM",
           "{n}OLYMP", "P{z:07d}", ".JPG", ".ORF", "#4a5a6a", "M.12-42mm F3.5-5.6 II R", 17),
    Geraet("gh5", "Panasonic", "DC-GH5", "DC-GH5", False, 2017, 2022, "Kamera Panasonic GH5/DCIM", "{n}_PANA",
           "P{z:07d}", ".JPG", ".RW2", "#5b4a8a", "LUMIX G VARIO 12-60/F3.5-5.6", 25),
    Geraet("q2", "LEICA CAMERA AG", "LEICA Q2", "LEICA Q2", False, 2019, 2024, "Kamera Leica Q2/DCIM", "{n}LEICA",
           "L{z:07d}", ".JPG", ".DNG", "#6b6b6b", "SUMMILUX 1:1.7/28 ASPH.", 28),
    Geraet("gr3", "RICOH IMAGING COMPANY, LTD.", "RICOH GR III", "RICOH GR III", False, 2019, 2025,
           "Kamera Ricoh GR III/DCIM", "{n}RICOH", "R{z:07d}", ".JPG", ".DNG", "#3c3c3c", "GR LENS 18.3mm F2.8", 18),
    Geraet("w55", "SONY", "DSC-W55", "DSC-W55", False, 2006, 2010, "Alte Kamera Sony DSC-W55/DCIM", "{n}MSDCF",
           "DSC{z:05d}", ".JPG", "", "#5f8fb0", "", 6),
    Geraet("iphone15", "Apple", "iPhone 15 Pro", "iPhone 15 Pro", False, 2023, 2026, "Handy iPhone 15 Pro/DCIM",
           "{n}APPLE", "IMG_{z:04d}", ".JPG", "", "#555a64", "iPhone 15 Pro back triple camera 6.765mm f/1.78", 7),
    Geraet("iphone8", "Apple", "iPhone 8", "iPhone 8", False, 2017, 2021, "Handy iPhone 8/DCIM", "{n}APPLE",
           "IMG_{z:04d}", ".JPG", "", "#7a7f88", "iPhone 8 back camera 3.99mm f/1.8", 4),
    Geraet("s23", "samsung", "SM-S911B", "SM-S911B", False, 2023, 2026, "Handy Samsung S23/DCIM", "Camera",
           "datum:%Y%m%d_%H%M%S", ".jpg", "", "#1f4f9f", "", 6),
    Geraet("pixel8", "Google", "Pixel 8", "Pixel 8", False, 2023, 2026, "Handy Pixel 8/DCIM", "Camera", "pxl",
           ".jpg", "", "#2a8a8a", "", 7),
    Geraet("p30", "HUAWEI", "ELE-L29", "ELE-L29", False, 2019, 2022, "Handy Huawei P30/DCIM", "Camera",
           "datum:IMG_%Y%m%d_%H%M%S", ".jpg", "", "#b0302a", "", 6),
    Geraet("dji", "DJI", "FC3582", "FC3582", False, 2022, 2026, "Drohne DJI Mini 3 Pro/DCIM", "{n}MEDIA",
           "DJI_{z:04d}", ".JPG", ".DNG", "#40484f", "", 7),
    Geraet("gopro", "GoPro", "HERO11 Black", "HERO11 Black", False, 2022, 2026, "GoPro HERO11/DCIM", "{n}GOPRO",
           "GOPR{z:04d}", ".JPG", "", "#1a1a1a", "", 3),
    Geraet("nokia", "Nokia", "N95", "N95", False, 2007, 2010, "Altes Handy Nokia N95", "Videos", "Video({z:03d})",
           ".jpg", "", "#2b5797", "", 5),
)
GERAETE: dict[str, Geraet] = {g.kennung: g for g in _G}

#: Anteile der Kamerafotos (Kategorie "kamera") je Geraet.
_GEWICHTE = {"a7c2": 10, "a7c": 8, "a7r4": 5, "r5": 8, "5d4": 6, "ixus": 3, "z62": 6, "d750": 4, "xt5": 6,
             "em10": 3, "gh5": 3, "q2": 3, "gr3": 3, "w55": 2, "iphone15": 10, "iphone8": 6, "s23": 8,
             "pixel8": 6, "p30": 4, "dji": 3, "gopro": 3}

#: Kategorie -> (Anzahl bei 5000 Testbildern, mindestens). "kamera" fuellt auf.
_ANTEILE = {
    "schon_im_archiv": (80, 5), "konflikt": (24, 12), "archiv_struktur": (120, 14), "raw_paar": (500, 8),
    "raw_allein": (100, 3), "heic": (280, 10), "video": (270, 20), "dateiname": (380, 14), "xmp_datum": (40, 2),
    "ohne_datum": (150, 4), "kaputt": (60, 6), "zeitzone": (40, 8), "scan": (60, 3), "png_webp": (60, 4),
    "gruppe_getrennt": (20, 2), "pfade": (30, 8), "kameraname": (30, 8),
}


# ------------------------------------------------------- Erwartung (SPEC) --


def kameraordner(make: str, model: str) -> tuple[str, bool]:
    """(Ordnername, aus der Alias-Liste) nach SPEC §3 „Kamera-Ordner“ - eigene
    Rechnung, nicht kamera.py: Alias-Liste mit dem Modell, dann mit Hersteller
    und Modell (ohne Gross-/Kleinschreibung); sonst das Modell mit "_" statt
    verbotener Zeichen, ohne Leerraum doppelt und ohne ". _" am Rand; ein
    Windows-Geraetename bekommt "_" angehaengt; ohne Modell Unbekannte_Kamera."""
    model = (model or "").strip()
    if not model:
        return UNBEKANNT, False
    kandidaten = [model]
    if make and not model.lower().startswith(make.strip().lower()):
        kandidaten.append(f"{make.strip()} {model}")
    for k in kandidaten:
        if k.lower() in ALIASE:
            return ALIASE[k.lower()], True
    name = "".join("_" if z in '<>:"/\\|?*' or ord(z) < 32 else z for z in model)
    name = " ".join(name.split()).strip("._ ")
    vorne = name.split(".")[0].rstrip(" ")
    if vorne.upper() in _WINDOWS_GERAETE:
        name = f"{vorne}_{name[len(vorne):]}"
    return name or UNBEKANNT, False


def zielordner(tag: date, kamera: str) -> tuple[str, str]:
    """(Ordner relativ zum Ziel, Satz zum vorhandenen Ordner) fuer ein sicheres
    Datum. Vorlage der SPEC: {jahr}/{jahr}-{monat} {monatsname}/{jahr}-{monat}-{tag}/{kamera};
    das vorbelegte Archiv (_vorbelegen) hat fuer einige Monate und Tage eigene
    Ordner, die das Programm seit v0.9 wiederverwendet."""
    j, m = tag.year, tag.month
    if (j, m) == (2019, 7):
        o = "2019-07 Juli Sommerurlaub"
        return f"2019/{o}/{tag.isoformat()}/{kamera}", meldungen.TB_O_ZUSATZ_MONAT.format(ordner=o)
    if (j, m) == (2020, 8):
        return "2020.08", meldungen.TB_O_FLACH_MONAT.format(ordner="2020.08")
    if (j, m) == (2021, 1):
        return f"2021/01/{tag.isoformat()}/{kamera}", meldungen.TB_O_MONAT_ZAHL
    if (j, m) == (2022, 3):
        return f"2022/März 2022/{tag.isoformat()}/{kamera}", meldungen.TB_O_MONAT_NAME
    if tag == date(2023, 5, 20):
        o = "2023-05-20 Hochzeit Anna"
        return f"2023/2023-05 Mai/{o}/{kamera}", meldungen.TB_O_TAG_ZUSATZ.format(ordner=o)
    if tag == date(2023, 6, 10):
        o = "2023-06-10 Grillfest"
        return f"2023/2023-06 Juni/{o}", meldungen.TB_O_TAG_FLACH.format(ordner=o)
    return f"{j:04d}/{j:04d}-{m:02d} {MONATE[m - 1]}/{tag.isoformat()}/{kamera}", ""


def _reserviert(tag: date) -> bool:
    return (tag.year, tag.month) in _RESERVIERT_MONATE or tag in _RESERVIERT_TAGE


def nach_heimat(utc: datetime) -> datetime:
    """Weltzeit (naiv) -> deutsche Ortszeit (naiv)."""
    return utc.replace(tzinfo=timezone.utc).astimezone(HEIMAT).replace(tzinfo=None)


def von_heimat(ort: datetime) -> datetime:
    """Deutsche Ortszeit (naiv) -> Weltzeit (naiv)."""
    return ort.replace(tzinfo=HEIMAT).astimezone(timezone.utc).replace(tzinfo=None)


def zone_text(ort: datetime) -> str:
    """"+02:00" fuer eine deutsche Ortszeit."""
    versatz = ort.replace(tzinfo=HEIMAT).utcoffset() or timedelta(0)
    minuten = int(versatz.total_seconds() // 60)
    return f"{'+' if minuten >= 0 else '-'}{abs(minuten) // 60:02d}:{abs(minuten) % 60:02d}"


def _exif_zeit(zeit: datetime) -> str:
    return zeit.strftime("%Y:%m:%d %H:%M:%S")


def _schluessel(rel: str) -> str:
    """Vergleich von Pfaden wie unter Windows: Unicode-Form NFC, ohne Gross-/Kleinschreibung."""
    return unicodedata.normalize("NFC", rel).casefold()


# --------------------------------------------------------------- Datei -----


@dataclass
class Datei:
    rel: str                         # relativ zum Testordner, mit "/": "Quelle/..." oder "Ziel/..."
    art: str                         # foto | raw | video | sidecar | sonstiges
    form: str                        # jpg png tif webp heic raw mov mp4 3gp avi xmp xml aae thm bytes
    kategorie: str
    nr: int = 0                      # 1..anzahl fuer die gezaehlten Testbilder
    geraet: str = ""                 # Hersteller und Modell zum Lesen ("" = keine Angabe)
    kamera: str = ""                 # erwarteter Kameraordner
    alias: bool = False
    aufnahme: str = ""               # Aufnahmezeit, Text
    datumsquelle: str = ""
    erwartung: str = ARCHIV
    ziel: str = ""                   # erwarteter Pfad relativ zu Ziel
    warum: str = ""
    dazu: list = field(default_factory=list)
    exif: dict | None = None         # eigener EXIF-Block (jpg, raw, heic)
    exiftool: list = field(default_factory=list)   # ExifTool-Argumente
    mtime: datetime | None = None
    inhalt: bytes | None = None      # fertiger Inhalt (Text, Bytes)
    kopie_von: "Datei | None" = None
    etikett_von: "Datei | None" = None   # THM: zeigt die Beschriftung dieses Videos
    film: dict | None = None         # Video: marke, utc, sony_xml, idit
    rest: bool = False               # Reste-Datei (Thumbs.db ...): darf beim Aufraeumen mit dem leeren Ordner gehen
    blake3: str = ""

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def ordner(self) -> str:
        return self.rel.rsplit("/", 1)[0]


# --------------------------------------------------------------- Planen ----


def anteile(anzahl: int) -> dict[str, int]:
    """Wie viele Testbilder je Kategorie; "kamera" fuellt auf anzahl auf."""
    if anzahl < MINDESTANZAHL:
        raise FotosortFehler(meldungen.tb_anzahl_zu_klein(MINDESTANZAHL))
    teile = {k: max(mindestens, round(bei_5000 * anzahl / STANDARD_ANZAHL)) for k, (bei_5000, mindestens) in _ANTEILE.items()}
    return teile


class _Plan:
    """Plant jede Datei: Inhalt, Kameradaten, Aenderungszeit und Erwartung."""

    def __init__(self, anzahl: int, saat: int = SAAT) -> None:
        self.anzahl = anzahl
        self.rng = random.Random(saat)
        self.dateien: list[Datei] = []
        self.nr = 0
        self.belegt: dict[str, Datei] = {}          # erwarteter Zielpfad (Schluessel) -> Datei
        self.quellnamen: set[str] = set()            # angelegte Pfade (Schluessel)
        self.zaehler: dict[str, int] = {}
        self.lfd = 0                                 # fuer ausgedachte Namen
        self.vorbelegt_ordner: list[str] = []        # leere Ordner im Ziel

    # -- Grundbausteine ---------------------------------------------------

    def neu(self, rel: str, art: str, form: str, kategorie: str, gezaehlt: bool = True, **werte) -> Datei:
        s = _schluessel(rel)
        if s in self.quellnamen:
            raise AssertionError(f"Testbilder: Pfad doppelt geplant: {rel}")
        self.quellnamen.add(s)
        d = Datei(rel, art, form, kategorie, **werte)
        if gezaehlt:
            self.nr += 1
            d.nr = self.nr
        self.dateien.append(d)
        return d

    def tag(self, von: int, bis: int, frei: bool = True) -> date:
        anfang, ende = date(von, 1, 1), min(date(bis, 12, 31), ENDE)
        while True:
            t = anfang + timedelta(days=self.rng.randrange((ende - anfang).days + 1))
            if not (frei and _reserviert(t)):
                return t

    def uhrzeit(self, t: date, von: int = 8, bis: int = 21) -> datetime:
        return datetime(t.year, t.month, t.day, self.rng.randint(von, bis), self.rng.randint(0, 59), self.rng.randint(0, 59))

    def zeiten(self, g: Geraet, n: int) -> list[datetime]:
        """n Aufnahmezeiten in Aufnahmetagen (3-30 Bilder je Tag), aufsteigend, je eine Sekunde frei."""
        zeiten: list[datetime] = []
        while len(zeiten) < n:
            t = self.tag(g.von, g.bis)
            k = min(self.rng.randint(3, 30), n - len(zeiten))
            z = self.uhrzeit(t, 8, 19)
            for _ in range(k):
                zeiten.append(z)
                z += timedelta(seconds=self.rng.choice((2, 3, 5, 8, 15, 30, 60, 120, 300)))
        zeiten.sort()
        for i in range(1, len(zeiten)):
            if zeiten[i] <= zeiten[i - 1]:
                zeiten[i] = zeiten[i - 1] + timedelta(seconds=1)
        return [z for z in zeiten if not _reserviert(z.date()) and z.date() <= ENDE] or zeiten

    def zaehler_weiter(self, g: Geraet) -> int:
        if g.kennung not in self.zaehler:
            self.zaehler[g.kennung] = self.rng.randint(100, 1500)
        self.zaehler[g.kennung] += 1
        return self.zaehler[g.kennung]

    def stamm(self, g: Geraet, zeit: datetime | None, z: int) -> str:
        if g.muster.startswith("datum:"):
            return (zeit or datetime(2020, 1, 1)).strftime(g.muster[len("datum:"):])
        if g.muster == "pxl":
            return f"PXL_{(zeit or datetime(2020, 1, 1)):%Y%m%d_%H%M%S}{z % 1000:03d}"
        return g.muster.format(z=z)

    def quellordner(self, g: Geraet, z: int) -> str:
        unter = g.unterordner.format(n=100 + (z // 500) % 800) if "{n}" in g.unterordner else g.unterordner
        return f"{QUELLE}/{g.quelle}/{unter}"

    def ins_archiv(self, d: Datei, tag: date | None, kamera: str, warum: str, name: str | None = None,
                   ordner: str | None = None) -> None:
        """Erwartung: Die Datei landet im Archiv - unter einem freien Namen."""
        zusatz = ""
        if ordner is None:
            if tag is None:
                ordner = f"{OHNE_DATUM}/{kamera}"
            else:
                ordner, zusatz = zielordner(tag, kamera)
        d.erwartung = ARCHIV
        d.ziel = f"{ordner}/{name or d.name}"
        d.warum = " ".join(t for t in (warum, zusatz) if t)
        self.belegen(d)

    def belegen(self, d: Datei) -> None:
        s = _schluessel(d.ziel)
        if s in self.belegt:
            raise AssertionError(f"Testbilder: Zielname doppelt geplant: {d.ziel} ({d.rel}, {self.belegt[s].rel})")
        self.belegt[s] = d

    def frei(self, ziel: str) -> bool:
        return _schluessel(ziel) not in self.belegt

    def exif_werte(self, g: Geraet | None, zeit: datetime | None, *, dto: str | None = None,
                   create: str | None = None, offset: bool = True, make: str | None = None,
                   model: str | None = None) -> dict:
        werte: dict = {}
        if g is not None:
            werte.update(make=g.make, model=g.model, objektiv=g.objektiv, brennweite=g.brennweite,
                         belichtung=self.rng.choice((30, 60, 125, 250, 500, 1000, 2000)),
                         blende=self.rng.choice((18, 28, 40, 56, 80, 110)),
                         iso=self.rng.choice((100, 200, 400, 800, 1600, 3200)))
        if make is not None:
            werte["make"] = make
        if model is not None:
            werte["model"] = model
        if zeit is not None:
            werte["dto"] = _exif_zeit(zeit)
            werte["create"] = _exif_zeit(zeit)
            werte["geaendert"] = _exif_zeit(zeit)
            if offset:
                werte["offset"] = zone_text(zeit)
        if dto is not None:
            werte["dto"] = dto
        if create is not None:
            werte["create"] = create
        return werte

    def foto(self, kategorie: str, g: Geraet, zeit: datetime, *, ordner: str | None = None, stamm: str | None = None,
             endung: str | None = None, warum: str | None = None, gezaehlt: bool = True, form: str = "jpg",
             kamera: str | None = None, ziel_ordner: str | None = None) -> Datei:
        """Ein Kamerafoto mit Datum (DateTimeOriginal) und Modell in den Kameradaten.
        Ist der Name im Zielordner schon vergeben (zwei Geraete mit IMG_1234 im
        selben flachen Ordner), gilt die naechste Nummer des Zaehlers."""
        for _ in range(1000):
            z = self.zaehler_weiter(g)
            name = f"{stamm or self.stamm(g, zeit, z)}{endung or g.endung}"
            rel = f"{ordner or self.quellordner(g, z)}/{name}"
            ziel = ziel_ordner or zielordner(zeit.date(), kamera or g.ordner)[0]
            if stamm is not None or (self.frei(f"{ziel}/{name}") and _schluessel(rel) not in self.quellnamen):
                break
        d = self.neu(rel, "foto", form, kategorie, gezaehlt, geraet=g.text, kamera=kamera or g.ordner, alias=g.alias,
                     aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
        d.exif = self.exif_werte(g, zeit)
        d.mtime = zeit + timedelta(seconds=self.rng.randint(1, 20))
        grund = warum if warum is not None else (meldungen.TB_W_KAMERA + (" " + meldungen.TB_W_ALIAS if g.alias else ""))
        self.ins_archiv(d, zeit.date(), d.kamera, grund, ordner=ziel_ordner)
        return d

    def raw(self, kategorie: str, g: Geraet, zeit: datetime, stamm: str, ordner: str, warum: str,
            gezaehlt: bool = True) -> Datei:
        d = self.neu(f"{ordner}/{stamm}{g.raw}", "raw", "raw", kategorie, gezaehlt, geraet=g.text, kamera=g.ordner,
                     alias=g.alias, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
        d.exif = self.exif_werte(g, zeit)
        d.mtime = zeit + timedelta(seconds=self.rng.randint(1, 20))
        self.ins_archiv(d, zeit.date(), g.ordner, warum)
        return d

    def begleit(self, haupt: Datei, name: str, form: str, inhalt: bytes | None, warum: str,
                kategorie: str = "begleit") -> Datei:
        """Eine Begleitdatei neben haupt; sie landet neben dessen Ziel."""
        d = self.neu(f"{haupt.ordner}/{name}", "sidecar", form, kategorie, False, geraet=haupt.geraet,
                     kamera=haupt.kamera, alias=haupt.alias, aufnahme=haupt.aufnahme, datumsquelle=haupt.datumsquelle)
        d.inhalt = inhalt
        d.mtime = haupt.mtime
        if haupt.erwartung == ARCHIV:
            d.erwartung = ARCHIV
            d.ziel = f"{haupt.ziel.rsplit('/', 1)[0]}/{name}"
            d.warum = warum
            self.belegen(d)
        haupt.dazu.append(name)
        d.dazu.append(haupt.name)
        return d

    def ausgedacht(self, vorlage: str) -> str:
        self.lfd += 1
        return vorlage.format(n=self.lfd)

    # -- Vorbelegtes Archiv ------------------------------------------------

    def archivdatei(self, rel_ziel: str, warum: str = "", form: str = "jpg", inhalt: bytes | None = None) -> Datei:
        d = self.neu(f"{ZIEL}/{rel_ziel}", "foto" if form == "jpg" else "sonstiges", form, "vorbelegt", False)
        d.erwartung = VORBELEGT
        d.ziel = rel_ziel
        d.warum = warum or meldungen.TB_W_VORBELEGT
        d.inhalt = inhalt
        d.mtime = datetime(2024, 11, 3, 18, 0, 0)
        if form == "jpg":
            d.exif = {"make": "", "model": "", "software": "fotosort Testbild (vorbelegt)"}
        self.belegen(d)
        return d

    def vorbelegen(self) -> None:
        """Ein Archiv, in dem schon etwas liegt (SPEC §3 seit v0.9): Ordner mit
        Zusatz, andere Schreibweisen, flache Ordner, ein Zeitraum, ein belegter Name."""
        self.archivdatei("2019/2019-07 Juli Sommerurlaub/2019-07-14/Canon EOS 5D Mark IV/IMG_0815.JPG")
        self.archivdatei("2020.08/Urlaub_alt_001.jpg")
        self.archivdatei("2020.08/Urlaub_alt_002.jpg")
        self.archivdatei("2021/01/2021-01-02/Canon EOS R5/IMG_alt_0001.JPG")
        self.archivdatei("2022/März 2022/Liste.txt", form="bytes",
                         inhalt="Liste der Bilder vom März 2022 (keine Bilddatei)\n".encode("utf-8"))
        self.archivdatei("2023/2023-05 Mai/2023-05-20 Hochzeit Anna/Canon EOS R5/IMG_alt_0002.JPG")
        self.archivdatei("2023/2023-06 Juni/2023-06-10 Grillfest/Grill_alt_001.jpg")
        self.archivdatei("2015-2016 Schule/Klassenfahrt_alt.jpg")
        self.belegt_dsc09001 = self.archivdatei("2024/2024-02 Februar/2024-02-14/A7C2/DSC09001.JPG")

    # -- Kategorien ----------------------------------------------------------

    def schon_im_archiv(self, n: int) -> None:
        """Bilder, die schon im Archiv liegen: am regulaeren Platz (Speicherkarte
        von 2018) und an einem fremden Ort (Handy-Sicherung). Dazu neue Bilder
        auf derselben Karte."""
        g5, g8 = GERAETE["5d4"], GERAETE["iphone8"]
        neu = max(1, n // 5)
        schon = n - neu
        karte = f"{QUELLE}/Alte Speicherkarte (schon importiert)/DCIM/100CANON"
        start = datetime(2018, 6, 10, 10, 15, 0)
        for i in range(schon):
            if i % 2 == 0:
                zeit = start + timedelta(minutes=3 * i)
                d = self.foto("schon_im_archiv", g5, zeit, ordner=karte, warum=meldungen.TB_W_SCHON)
                self.belegt.pop(_schluessel(d.ziel))
                d.erwartung = SCHON
                kopie = self.archivdatei(d.ziel)
            else:
                zeit = self.uhrzeit(self.tag(2017, 2017))
                d = self.foto("schon_im_archiv", g8, zeit, ordner=f"{QUELLE}/Handy-Sicherung 2017 (schon importiert)",
                              warum=meldungen.TB_W_SCHON)
                self.belegt.pop(_schluessel(d.ziel))
                d.erwartung = SCHON
                kopie = self.archivdatei(f"Alte Handybilder/{d.name}")
                d.ziel = kopie.ziel
            kopie.kopie_von = d
            kopie.warum = meldungen.TB_W_VORBELEGT
        for i in range(neu):
            zeit = datetime(2018, 6, 11, 9, 0, 0) + timedelta(minutes=7 * i)
            self.foto("schon_im_archiv", g5, zeit, ordner=karte,
                      warum=meldungen.TB_W_SCHON_NEU + " " + meldungen.TB_W_KAMERA)

    def konflikte(self, n: int) -> None:
        """Gleicher Name, anderer Inhalt, gleicher Zielordner: Die Karte, die in
        der Reihenfolge der Quelle zuerst kommt, behaelt den Namen."""
        g = GERAETE["a7c2"]
        karten = [f"{QUELLE}/Namensgleich Karte {k}/DCIM/100MSDCF" for k in (1, 2, 3)]
        tag = datetime(2024, 3, 2, 10, 0, 0)
        gezaehlt = 0

        def foto_mit(karte: str, stamm: str, zeit: datetime, anhang: str, andere: str, grund: str = "") -> Datei:
            d = self.neu(f"{karte}/{stamm}.JPG", "foto", "jpg", "konflikt", True, geraet=g.text, kamera=g.ordner,
                         alias=g.alias, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            d.exif = self.exif_werte(g, zeit)
            d.mtime = zeit + timedelta(seconds=5)
            text = grund or (meldungen.TB_W_ANHANG.format(andere=andere, anhang=anhang) if anhang else meldungen.TB_W_KAMERA)
            self.ins_archiv(d, zeit.date(), g.ordner, text, name=f"{stamm}{anhang}.JPG")
            return d

        # Zwei Karten, gleicher Name
        foto_mit(karten[0], "DSC00001", tag, "", "")
        foto_mit(karten[1], "DSC00001", tag + timedelta(hours=5), "_1", "Namensgleich Karte 1/DSC00001.JPG")
        # Drei Karten
        foto_mit(karten[0], "DSC00002", tag + timedelta(minutes=1), "", "")
        foto_mit(karten[1], "DSC00002", tag + timedelta(hours=5, minutes=1), "_1", "Namensgleich Karte 1/DSC00002.JPG")
        foto_mit(karten[2], "DSC00002", tag + timedelta(hours=6, minutes=1), "_2", "Karte 1 und Karte 2")
        gezaehlt += 5
        # Eine ganze Gruppe (RAW, JPG, XMP) bekommt denselben Anhang
        for k, (karte, anhang, form2) in enumerate(((karten[0], "", True), (karten[1], "_1", False))):
            zeit = tag + timedelta(minutes=2, hours=5 * k)
            grund = meldungen.TB_W_RAW_PAAR + (" " + meldungen.TB_W_ANHANG_GRUPPE.format(anhang=anhang) if anhang else "")
            r = self.neu(f"{karte}/DSC00003.ARW", "raw", "raw", "konflikt", True, geraet=g.text, kamera=g.ordner,
                         alias=g.alias, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            r.exif = self.exif_werte(g, zeit)
            r.mtime = zeit + timedelta(seconds=3)
            self.ins_archiv(r, zeit.date(), g.ordner, grund, name=f"DSC00003{anhang}.ARW")
            j = self.neu(f"{karte}/DSC00003.JPG", "foto", "jpg", "konflikt", True, geraet=g.text, kamera=g.ordner,
                         alias=g.alias, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            j.exif = dict(r.exif)
            j.mtime = r.mtime
            self.ins_archiv(j, zeit.date(), g.ordner, grund, name=f"DSC00003{anhang}.JPG")
            xmp_name = "DSC00003.ARW.xmp" if form2 else "DSC00003.xmp"
            x = self.begleit(r, xmp_name, "xmp", formate.xmp(bewertung=3 + k).encode("utf-8"),
                             meldungen.TB_W_ANHANG_GRUPPE.format(anhang=anhang) if anhang else meldungen.TB_W_RAW_PAAR)
            if anhang:
                self.belegt.pop(_schluessel(x.ziel))
                x.ziel = x.ziel.rsplit("/", 1)[0] + "/" + ("DSC00003_1.xmp")
                self.belegen(x)
            j.dazu.extend([r.name, xmp_name])
            r.dazu.append(j.name)
        gezaehlt += 4
        # Gross-/Kleinschreibung: unter Windows derselbe Name
        g8 = GERAETE["iphone8"]
        for k, (karte, stamm, endung, anhang) in enumerate(((karten[0], "IMG_0001", ".JPG", ""),
                                                            (karten[1], "img_0001", ".jpg", "_1"))):
            zeit = datetime(2019, 4, 1, 14, 0, 0) + timedelta(hours=2 * k)
            d = self.neu(f"{karte}/{stamm}{endung}", "foto", "jpg", "konflikt", True, geraet=g8.text, kamera=g8.ordner,
                         aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            d.exif = self.exif_werte(g8, zeit)
            d.mtime = zeit + timedelta(seconds=2)
            grund = (meldungen.TB_W_ANHANG_GROSS_KLEIN.format(andere="Namensgleich Karte 1/IMG_0001.JPG", anhang=anhang)
                     if anhang else meldungen.TB_W_KAMERA)
            self.ins_archiv(d, zeit.date(), g8.ordner, grund, name=f"{stamm}{anhang}{endung}")
        gezaehlt += 2
        # Im Archiv schon belegter Name
        zeit = datetime(2024, 2, 14, 16, 30, 0)
        d = self.neu(f"{karten[0]}/DSC09001.JPG", "foto", "jpg", "konflikt", True, geraet=g.text, kamera=g.ordner,
                     alias=g.alias, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
        d.exif = self.exif_werte(g, zeit)
        d.mtime = zeit + timedelta(seconds=2)
        self.ins_archiv(d, zeit.date(), g.ordner, meldungen.TB_W_ANHANG_ARCHIV.format(anhang="_1"), name="DSC09001_1.JPG")
        gezaehlt += 1
        # Weitere Paare bis n
        k = 10
        while gezaehlt + 2 <= n:
            stamm = f"DSC000{k:02d}"
            zeit = tag + timedelta(minutes=k)
            foto_mit(karten[0], stamm, zeit, "", "")
            foto_mit(karten[1], stamm, zeit + timedelta(hours=5), "_1", f"Namensgleich Karte 1/{stamm}.JPG")
            gezaehlt += 2
            k += 1

    def archiv_struktur(self, n: int) -> None:
        """Bilder aus Monaten und Tagen, fuer die das vorbelegte Archiv eigene Ordner hat."""
        faelle = [
            (date(2019, 7, 1), date(2019, 7, 31), ("a7r4", "5d4", "iphone8", "q2", "gr3")),
            (date(2020, 8, 1), date(2020, 8, 31), ("a7c", "r5", "iphone8", "gh5")),
            (date(2021, 1, 1), date(2021, 1, 31), ("a7c", "r5", "z62", "p30")),
            (date(2022, 3, 1), date(2022, 3, 31), ("xt5", "a7c", "dji", "z62")),
            (date(2023, 5, 20), date(2023, 5, 20), ("a7c2", "iphone15", "s23", "r5")),
            (date(2023, 6, 10), date(2023, 6, 10), ("a7c2", "iphone15", "pixel8")),
            (date(2015, 1, 1), date(2015, 12, 31), ("d750", "em10")),
        ]
        # Kamerafolder in anderer Gross-/Kleinschreibung (2019-07-14)
        g5 = GERAETE["5d4"]
        zeit = datetime(2019, 7, 14, 11, 20, 0)
        z = self.zaehler_weiter(g5)
        d = self.neu(f"{QUELLE}/Kamera Canon 5D (Großbuchstaben)/IMG_{z:04d}.JPG", "foto", "jpg", "archiv_struktur", True,
                     geraet="Canon CANON EOS 5D MARK IV", kamera="Canon EOS 5D Mark IV",
                     aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
        d.exif = self.exif_werte(g5, zeit, model="CANON EOS 5D MARK IV")
        d.mtime = zeit + timedelta(seconds=4)
        self.ins_archiv(d, zeit.date(), "Canon EOS 5D Mark IV",
                        meldungen.TB_O_KAMERA_GROSS.format(ordner="Canon EOS 5D Mark IV"))
        gemacht = 1
        i = 0
        while gemacht < n:
            von, bis, geraete = faelle[i % len(faelle)]
            g = GERAETE[geraete[(i // len(faelle)) % len(geraete)]]
            t = von + timedelta(days=self.rng.randrange((bis - von).days + 1))
            zeit = self.uhrzeit(t, 9, 20)
            warum = meldungen.TB_W_KAMERA + (" " + meldungen.TB_O_JAHRESBEREICH if t.year == 2015 else "")
            d = self.foto("archiv_struktur", g, zeit, warum=warum)
            gemacht += 1
            i += 1

    def raw_paare(self, n: int) -> None:
        geraete = [GERAETE[k] for k in ("a7c2", "a7c", "a7r4", "5d4", "z62", "d750", "em10", "gh5", "q2", "gr3", "dji")]
        paare = n // 2
        for i in range(paare):
            g = geraete[i % len(geraete)]
            zeit = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            stamm = self.stamm(g, zeit, z)
            ordner = self.quellordner(g, z)
            r = self.raw("raw_paar", g, zeit, stamm, ordner, meldungen.TB_W_RAW_PAAR)
            j = self.neu(f"{ordner}/{stamm}{g.endung}", "foto", "jpg", "raw_paar", True, geraet=g.text,
                         kamera=g.ordner, alias=g.alias, aufnahme=r.aufnahme, datumsquelle=r.datumsquelle)
            j.exif = dict(r.exif)
            j.mtime = r.mtime
            self.ins_archiv(j, zeit.date(), g.ordner, meldungen.TB_W_RAW_PAAR)
            r.dazu.append(j.name)
            j.dazu.append(r.name)
            if i % 3 == 0:
                name = f"{stamm}.xmp" if i % 2 == 0 else f"{stamm}{g.raw}.xmp"
                farbe = self.rng.choice((None, "Red", "Green", "Blue", "Yellow"))
                self.begleit(r, name, "xmp", formate.xmp(bewertung=self.rng.randint(1, 5), farbe=farbe).encode("utf-8"),
                             meldungen.TB_W_RAW_PAAR)
                j.dazu.append(name)
        if n % 2:
            self.raw_allein(1)

    def raw_allein(self, n: int) -> None:
        geraete = [GERAETE[k] for k in ("a7r4", "z62", "5d4", "q2", "gr3")]
        for i in range(n):
            g = geraete[i % len(geraete)]
            zeit = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            self.raw("raw_allein", g, zeit, self.stamm(g, zeit, z), self.quellordner(g, z),
                     meldungen.TB_W_RAW_ALLEIN + " " + meldungen.TB_W_KAMERA)

    def heic(self, n: int) -> None:
        """iPhone-Fotos als HEIC; ein Teil als Live-Foto mit MOV, einige mit .AAE."""
        gemacht = 0
        i = 0
        while gemacht < n:
            g = GERAETE["iphone15"] if i % 3 else GERAETE["iphone8"]
            mitternacht = i in (5, 11)
            if mitternacht:
                t = self.tag(max(g.von, 2018), g.bis)
                zeit = datetime(t.year, t.month, t.day, 23, 59, 58)
            else:
                zeit = self.uhrzeit(self.tag(g.von, g.bis))
            live = (i % 5 in (0, 2) or mitternacht) and gemacht + 2 <= n
            z = self.zaehler_weiter(g)
            stamm = f"IMG_{z:04d}"
            ordner = self.quellordner(g, z)
            warum = meldungen.TB_W_HEIC + (" " + meldungen.TB_W_LIVE if live and not mitternacht else "")
            if mitternacht:
                warum = meldungen.TB_W_HEIC + " " + meldungen.TB_W_LIVE_MITTERNACHT
            h = self.neu(f"{ordner}/{stamm}.HEIC", "foto", "heic", "heic", True, geraet=g.text, kamera=g.ordner,
                         aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            h.exif = self.exif_werte(g, zeit)
            h.mtime = zeit + timedelta(seconds=2)
            self.ins_archiv(h, zeit.date(), g.ordner, warum)
            gemacht += 1
            if live:
                mz = zeit + timedelta(seconds=3 if mitternacht else 1)
                v = self.neu(f"{ordner}/{stamm}.MOV", "video", "mov", "heic", True, geraet=g.text, kamera=g.ordner,
                             aufnahme=meldungen.tb_zeit(mz), datumsquelle=meldungen.tb_dq_zone(zone_text(mz)))
                v.film = {"marke": b"qt  ", "utc": von_heimat(mz)}
                v.exiftool = [f"-Keys:CreationDate={_exif_zeit(mz)}{zone_text(mz)}", "-Keys:Make=Apple",
                              f"-Keys:Model={g.model}"]
                v.mtime = mz + timedelta(seconds=3)
                self.ins_archiv(v, zeit.date(), g.ordner, meldungen.TB_W_LIVE_MITTERNACHT if mitternacht else meldungen.TB_W_LIVE)
                h.dazu.append(v.name)
                v.dazu.append(h.name)
                gemacht += 1
            if i % 7 == 3:
                self.begleit(h, f"{stamm}.AAE", "aae", formate.aae(f"Testbild {h.nr}").encode("utf-8"), meldungen.TB_W_AAE)
            i += 1

    def videos(self, n: int) -> None:
        arten = ["iphone", "samsung", "gopro", "dji", "sony_xml", "sony_eingebettet", "avi", "3gp"]
        gewichte = [22, 18, 12, 8, 12, 8, 8, 6]
        sonder = ["silvester", "sommer_naechster_tag", "winter_naechster_tag", "zeitumstellung", "z"]
        plan = sonder + [self.rng.choices(arten, gewichte)[0] for _ in range(max(0, n - len(sonder)))]
        for art in arten:          # jede Art mindestens einmal
            if art not in plan[len(sonder):] and len(plan) > len(sonder):
                plan[len(sonder) + arten.index(art) % max(1, len(plan) - len(sonder))] = art
        for i, art in enumerate(plan[:n]):
            self.video(art, i)

    def video(self, art: str, i: int) -> None:
        if art in ("silvester", "sommer_naechster_tag", "winter_naechster_tag", "zeitumstellung"):
            g = GERAETE["gopro"]
            jahr = 2022 + (i % 3)
            utc = {"silvester": datetime(jahr, 12, 31, 23, 30, 0),
                   "sommer_naechster_tag": datetime(2023, 8, 19, 22, 40, 0),
                   "winter_naechster_tag": datetime(2024, 11, 23, 23, 15, 0),
                   "zeitumstellung": datetime(2023, 3, 26, 1, 30, 0)}[art]
            ort = nach_heimat(utc)
            warum = {"silvester": meldungen.TB_W_VIDEO_UTC_JAHR.format(utc=f"{utc:%d.%m.%Y %H:%M}", jahr=ort.year),
                     "sommer_naechster_tag": meldungen.TB_W_VIDEO_UTC_TAG,
                     "winter_naechster_tag": meldungen.TB_W_VIDEO_UTC_TAG,
                     "zeitumstellung": meldungen.TB_W_VIDEO_SOMMERZEIT}[art]
            self.video_utc(g, utc, warum, f"GX01{self.zaehler_weiter(g):04d}.MP4", b"mp41")
            return
        if art == "z":
            g = GERAETE["iphone15"]
            utc = datetime(2023, 12, 31, 23, 45, 0)
            ort = nach_heimat(utc)
            z = self.zaehler_weiter(g)
            v = self.neu(f"{self.quellordner(g, z)}/IMG_{z:04d}.MOV", "video", "mov", "video", True, geraet=g.text,
                         kamera=g.ordner, aufnahme=meldungen.tb_zeit(ort), datumsquelle=meldungen.tb_dq_z(utc, video=True))
            v.film = {"marke": b"qt  ", "utc": utc}
            v.exiftool = [f"-Keys:CreationDate={_exif_zeit(utc)}Z", "-Keys:Make=Apple", f"-Keys:Model={g.model}"]
            v.mtime = ort + timedelta(seconds=30)
            self.ins_archiv(v, ort.date(), g.ordner, meldungen.TB_W_Z)
            return
        if art == "iphone":
            g = GERAETE["iphone15"] if i % 2 else GERAETE["iphone8"]
            ort = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            v = self.neu(f"{self.quellordner(g, z)}/IMG_{z:04d}.MOV", "video", "mov", "video", True, geraet=g.text,
                         kamera=g.ordner, aufnahme=meldungen.tb_zeit(ort), datumsquelle=meldungen.tb_dq_zone(zone_text(ort)))
            v.film = {"marke": b"qt  ", "utc": von_heimat(ort)}
            v.exiftool = [f"-Keys:CreationDate={_exif_zeit(ort)}{zone_text(ort)}", "-Keys:Make=Apple", f"-Keys:Model={g.model}"]
            v.mtime = ort + timedelta(seconds=40)
            self.ins_archiv(v, ort.date(), g.ordner, meldungen.TB_W_VIDEO_ZONE)
        elif art in ("samsung", "gopro", "dji"):
            g = GERAETE[{"samsung": "s23", "gopro": "gopro", "dji": "dji"}[art]]
            ort = self.uhrzeit(self.tag(g.von, g.bis))
            utc = von_heimat(ort)
            z = self.zaehler_weiter(g)
            name = {"samsung": f"{ort:%Y%m%d_%H%M%S}.mp4", "gopro": f"GX01{z:04d}.MP4", "dji": f"DJI_{z:04d}.MP4"}[art]
            self.video_utc(g, utc, meldungen.TB_W_VIDEO_UTC, name, b"mp42")
        elif art == "sony_xml":
            g = GERAETE["a7c2"]
            ort = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            ordner = f"{QUELLE}/Kamera Sony A7C II/PRIVATE/M4ROOT/CLIP"
            stamm = f"C{z:04d}"
            xml = f"{stamm}M01.XML"
            v = self.neu(f"{ordner}/{stamm}.MP4", "video", "mp4", "video", True, geraet=f"SONY {g.model} (laut {xml})",
                         kamera=g.ordner, alias=True, aufnahme=meldungen.tb_zeit(ort),
                         datumsquelle=meldungen.TB_DQ_SONY_XML.format(xml=xml))
            v.film = {"marke": b"XAVC", "utc": von_heimat(ort)}
            v.mtime = ort + timedelta(seconds=30)
            self.ins_archiv(v, ort.date(), g.ordner, meldungen.TB_W_SONY_XML.format(xml=xml) + " " + meldungen.TB_W_ALIAS)
            self.begleit(v, xml, "xml", formate.sony_xml(f"{ort:%Y-%m-%dT%H:%M:%S}{zone_text(ort)}", g.model).encode("utf-8"),
                         meldungen.TB_W_SONY_XML.format(xml=xml))
        elif art == "sony_eingebettet":
            g = GERAETE["a7c"]
            ort = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            v = self.neu(f"{QUELLE}/Kamera Sony A7C/PRIVATE/M4ROOT/CLIP/C{z:04d}.MP4", "video", "mp4", "video", True,
                         geraet=f"SONY {g.model}", kamera=g.ordner, alias=True, aufnahme=meldungen.tb_zeit(ort),
                         datumsquelle=meldungen.TB_DQ_SONY_EINGEBETTET)
            v.film = {"marke": b"XAVC", "utc": von_heimat(ort),
                      "sony_xml": formate.sony_xml(f"{ort:%Y-%m-%dT%H:%M:%S}{zone_text(ort)}", g.model)}
            v.mtime = ort + timedelta(seconds=30)
            self.ins_archiv(v, ort.date(), g.ordner, meldungen.TB_W_SONY_EINGEBETTET + " " + meldungen.TB_W_ALIAS)
        elif art == "avi":
            g = GERAETE["ixus"]
            ort = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            stamm = f"MVI_{z:04d}"
            v = self.neu(f"{self.quellordner(g, z)}/{stamm}.AVI", "video", "avi", "video", True, geraet="",
                         kamera=UNBEKANNT, aufnahme=meldungen.tb_zeit(ort), datumsquelle=meldungen.TB_DQ_AVI)
            v.film = {"idit": formate.idit_text(ort)}
            v.mtime = ort + timedelta(seconds=30)
            self.ins_archiv(v, ort.date(), UNBEKANNT, meldungen.TB_W_AVI)
            thm = self.begleit(v, f"{stamm}.THM", "thm", None, meldungen.TB_W_THM)
            thm.etikett_von = v
        elif art == "3gp":
            g = GERAETE["nokia"]
            ort = self.uhrzeit(self.tag(g.von, g.bis))
            z = self.zaehler_weiter(g)
            self.video_utc(g, von_heimat(ort), meldungen.TB_W_3GP, f"Video({z:03d}).3gp", b"3gp4")

    def video_utc(self, g: Geraet, utc: datetime, warum: str, name: str, marke: bytes) -> Datei:
        """Ein Video mit Weltzeit ohne Zeitzone (CreateDate) und Modell (UserData)."""
        ort = nach_heimat(utc)
        z = self.zaehler[g.kennung] if g.kennung in self.zaehler else self.zaehler_weiter(g)
        form = name.rsplit(".", 1)[1].lower()
        v = self.neu(f"{self.quellordner(g, z)}/{name}", "video", form, "video", True, geraet=g.text, kamera=g.ordner,
                     aufnahme=meldungen.tb_zeit(ort), datumsquelle=meldungen.tb_dq_utc(utc))
        v.film = {"marke": marke, "utc": None}
        v.exiftool = [f"-QuickTime:CreateDate={_exif_zeit(utc)}", f"-QuickTime:ModifyDate={_exif_zeit(utc)}",
                      f"-UserData:Make={g.make}", f"-UserData:Model={g.model}"]
        v.mtime = ort + timedelta(seconds=45)
        self.ins_archiv(v, ort.date(), g.ordner, warum)
        return v

    def dateinamen(self, n: int) -> None:
        """Keine Kameradaten - das Datum steht nur im Namen."""
        arten = [("whatsapp", 30), ("whatsapp_video", 5), ("android", 15), ("mac", 10), ("snipping", 5),
                 ("signal", 8), ("telegram", 5), ("pxl", 5), ("img_datum", 7), ("nur_datum", 5)]
        namen = [a for a, _ in arten]
        plan = list(namen) + [self.rng.choices(namen, [w for _, w in arten])[0] for _ in range(max(0, n - len(namen)))]
        wa = 0
        for art in plan[:n]:
            ort = self.uhrzeit(self.tag(2014, 2026))
            mit_uhrzeit = True
            if art == "whatsapp":
                wa += 1
                rel = f"{QUELLE}/WhatsApp/Media/WhatsApp Images/IMG-{ort:%Y%m%d}-WA{wa:04d}.jpg"
                form, mit_uhrzeit, warum = "jpg", False, meldungen.TB_W_WHATSAPP
            elif art == "whatsapp_video":
                wa += 1
                rel = f"{QUELLE}/WhatsApp/Media/WhatsApp Video/VID-{ort:%Y%m%d}-WA{wa:04d}.mp4"
                form, mit_uhrzeit, warum = "mp4", False, meldungen.TB_W_WHATSAPP
            elif art == "android":
                rel = f"{QUELLE}/Bildschirmfotos/Screenshot_{ort:%Y%m%d-%H%M%S}.png"
                form, warum = "png", meldungen.TB_W_NAME
            elif art == "mac":
                wort = self.rng.choice(("Bildschirmfoto {d} um {u}", "Screenshot {d} at {u}"))
                rel = f"{QUELLE}/Bildschirmfotos Mac/{wort.format(d=f'{ort:%Y-%m-%d}', u=f'{ort:%H.%M.%S}')}.png"
                form, warum = "png", meldungen.TB_W_NAME
            elif art == "snipping":
                rel = f"{QUELLE}/Bildschirmfotos Windows/Screenshot {ort:%Y-%m-%d} {ort:%H%M%S}.png"
                form, mit_uhrzeit, warum = "png", False, meldungen.TB_W_NAME_DATUM
            elif art == "signal":
                rel = f"{QUELLE}/Signal/signal-{ort:%Y-%m-%d-%H-%M-%S}-{self.rng.randint(100, 999)}.jpg"
                form, warum = "jpg", meldungen.TB_W_NAME
            elif art == "telegram":
                rel = f"{QUELLE}/Telegram Desktop/photo_{ort:%Y-%m-%d_%H-%M-%S}.jpg"
                form, warum = "jpg", meldungen.TB_W_NAME
            elif art == "pxl":
                rel = f"{QUELLE}/Google Fotos Export/PXL_{ort:%Y%m%d_%H%M%S}{self.rng.randint(100, 999)}.jpg"
                form, warum = "jpg", meldungen.TB_W_NAME
            elif art == "img_datum":
                rel = f"{QUELLE}/Handy Export ohne Daten/IMG_{ort:%Y%m%d_%H%M%S}.jpg"
                form, warum = "jpg", meldungen.TB_W_NAME
            else:
                rel = f"{QUELLE}/Fotos mit Datum im Namen/{ort:%Y-%m-%d} {self.rng.choice(('Ausflug', 'Familie', 'Garten', 'Konzert'))} {self.ausgedacht('{n}')}.jpg"
                form, mit_uhrzeit, warum = "jpg", False, meldungen.TB_W_NAME_DATUM
            if _schluessel(rel) in self.quellnamen or not self.frei(f"{zielordner(ort.date(), UNBEKANNT)[0]}/{rel.rsplit('/', 1)[1]}"):
                continue
            art_datei = "video" if form == "mp4" else "foto"
            d = self.neu(rel, art_datei, form, "dateiname", True, kamera=UNBEKANNT,
                         aufnahme=meldungen.tb_zeit(ort, mit_uhrzeit),
                         datumsquelle=meldungen.TB_DQ_NAME if mit_uhrzeit else meldungen.TB_DQ_NAME_DATUM)
            if form == "mp4":
                d.film = {"marke": b"mp42", "utc": None}
            elif form == "jpg":
                d.exif = None          # keine Kameradaten (WhatsApp und Co. entfernen sie)
            d.mtime = ort + timedelta(hours=self.rng.randint(1, 48))
            self.ins_archiv(d, ort.date(), UNBEKANNT, warum)
        while self.nr_kategorie("dateiname") < n:      # sehr selten: doppelt gezogener Name
            ort = self.uhrzeit(self.tag(2014, 2026))
            d = self.neu(f"{QUELLE}/Telegram Desktop/photo_{ort:%Y-%m-%d_%H-%M-%S}_{self.ausgedacht('{n}')}.jpg", "foto",
                         "jpg", "dateiname", True, kamera=UNBEKANNT, aufnahme=meldungen.tb_zeit(ort),
                         datumsquelle=meldungen.TB_DQ_NAME)
            d.mtime = ort + timedelta(hours=2)
            self.ins_archiv(d, ort.date(), UNBEKANNT, meldungen.TB_W_NAME)

    def nr_kategorie(self, kategorie: str) -> int:
        return sum(1 for d in self.dateien if d.kategorie == kategorie and d.nr)

    def xmp_datum(self, n: int) -> None:
        """Scans ohne Datum mit .xmp-Begleitdatei, die das Datum nennt."""
        for i in range(n):
            t = self.tag(1992, 2008)
            zeit = datetime(t.year, t.month, t.day, 12, 0, 0)
            stamm = self.ausgedacht("scan_{n:04d}")
            xmp_name = f"{stamm}.xmp"
            if i % 2 == 0:
                d = self.neu(f"{QUELLE}/Scans mit XMP/{stamm}.tif", "foto", "tif", "xmp_datum", True,
                             geraet="EPSON Perfection V600", kamera="Analog", alias=True,
                             aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.tb_dq_xmp(xmp_name))
                d.exiftool = ["-EXIF:Make=EPSON", "-EXIF:Model=Perfection V600"]
                kamera = "Analog"
            else:
                d = self.neu(f"{QUELLE}/Scans mit XMP/{stamm}.jpg", "foto", "jpg", "xmp_datum", True, kamera=UNBEKANNT,
                             aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.tb_dq_xmp(xmp_name))
                kamera = UNBEKANNT
            d.mtime = datetime(2021, 2, 3, 20, 0, 0) + timedelta(minutes=i)
            self.ins_archiv(d, t, kamera, meldungen.TB_W_XMP.format(xmp=xmp_name)
                            + (" " + meldungen.TB_W_SCAN if kamera == "Analog" else ""))
            self.begleit(d, xmp_name, "xmp", formate.xmp(datum=f"{zeit:%Y-%m-%dT%H:%M:%S}").encode("utf-8"),
                         meldungen.TB_W_XMP.format(xmp=xmp_name))

    def ohne_datum(self, n: int) -> None:
        mit_kamera = n * 3 // 10
        g = GERAETE["r5"]
        for i in range(n):
            if i < mit_kamera:
                z = self.zaehler_weiter(g)
                d = self.neu(f"{QUELLE}/Kamera ohne gestellte Uhr/IMG_{z:04d}.JPG", "foto", "jpg", "ohne_datum", True,
                             geraet=g.text, kamera=g.ordner, aufnahme="", datumsquelle=meldungen.TB_DQ_KEINS)
                d.exif = self.exif_werte(g, None)
                self.ins_archiv(d, None, g.ordner, meldungen.TB_W_OHNE_KAMERA)
            else:
                vorlage, form = self.rng.choice((("download ({n}).jpg", "jpg"), ("Unbenannt-{n}.png", "png"),
                                                 ("Bild {n}.webp", "webp"), ("bearbeitet_{n}.jpg", "jpg")))
                d = self.neu(f"{QUELLE}/Ohne Datum/{self.ausgedacht(vorlage)}", "foto", form, "ohne_datum", True,
                             kamera=UNBEKANNT, aufnahme="", datumsquelle=meldungen.TB_DQ_KEINS)
                self.ins_archiv(d, None, UNBEKANNT, meldungen.TB_W_OHNE)
            d.aufnahme = meldungen.TB_DQ_KEINS
            d.datumsquelle = ""
            d.mtime = datetime(2016, 1, 1) + timedelta(days=self.rng.randrange(2500), seconds=self.rng.randrange(86400))

    def kaputt(self, n: int) -> None:
        arten = ["1970", "2099", "0000", "create", "scan1985"]
        for i in range(n):
            art = arten[i % len(arten)]
            if art == "scan1985":
                zeit = datetime(1985, 6, 1 + i % 28, 12, 0, 0)
                stamm = self.ausgedacht("Negativ_{n:04d}")
                d = self.neu(f"{QUELLE}/Scans/Alte Negative/{stamm}.jpg", "foto", "jpg", "kaputt", True,
                             geraet="Noritsu Koki QSS-32_33", kamera="Analog", alias=True,
                             aufnahme=meldungen.tb_dq_kaputt(_exif_zeit(zeit)), datumsquelle="")
                d.exif = self.exif_werte(None, None, make="Noritsu Koki", model="QSS-32_33", dto=_exif_zeit(zeit))
                d.mtime = datetime(2022, 5, 7, 11, 0, 0) + timedelta(minutes=i)
                self.ins_archiv(d, None, "Analog", meldungen.TB_W_KAPUTT_SCAN)
                continue
            g = GERAETE[("a7c", "z62", "a7c", "r5")[i % 4]]
            z = self.zaehler_weiter(g)
            stamm = self.stamm(g, None, z)
            rel = f"{QUELLE}/Kamera mit kaputter Uhr/{stamm}{g.endung}"
            if art == "create":
                gut = self.uhrzeit(self.tag(g.von, g.bis))
                d = self.neu(rel, "foto", "jpg", "kaputt", True, geraet=g.text, kamera=g.ordner, alias=g.alias,
                             aufnahme=meldungen.tb_zeit(gut), datumsquelle=meldungen.TB_DQ_CREATE)
                d.exif = self.exif_werte(g, None, dto="1970:01:01 00:00:00", create=_exif_zeit(gut))
                d.mtime = gut + timedelta(seconds=5)
                self.ins_archiv(d, gut.date(), g.ordner, meldungen.TB_W_KAPUTT_CREATE)
                continue
            wert = {"1970": "1970:01:01 00:00:00", "2099": "2099:12:31 23:59:59", "0000": "0000:00:00 00:00:00"}[art]
            d = self.neu(rel, "foto", "jpg", "kaputt", True, geraet=g.text, kamera=g.ordner, alias=g.alias,
                         aufnahme=meldungen.tb_dq_kaputt(wert), datumsquelle="")
            d.exif = self.exif_werte(g, None, dto=wert, create=wert)
            d.mtime = datetime(2023, 1, 1) + timedelta(days=self.rng.randrange(600))
            self.ins_archiv(d, None, g.ordner, meldungen.TB_W_KAPUTT)

    def zeitzonen(self, n: int) -> None:
        g = GERAETE["a7c2"]
        g15 = GERAETE["iphone15"]
        arten = ["z", "newyork", "tokio", "mitternacht"]
        for i in range(n):
            art = arten[i % 4]
            ordner = f"{QUELLE}/Reisen und Zeitzonen"
            if art == "z":
                utc = datetime(2022 + (i // 4) % 3, 12, 31, 23, 10 + (i // 4) % 40, 0)
                ort = nach_heimat(utc)
                stamm = self.ausgedacht("Export_Weltzeit_{n:03d}")
                d = self.neu(f"{ordner}/{stamm}.jpg", "foto", "jpg", "zeitzone", True, geraet=g15.text,
                             kamera=g15.ordner, aufnahme=meldungen.tb_zeit(ort), datumsquelle=meldungen.tb_dq_z(utc))
                d.exif = self.exif_werte(g15, None)
                d.exiftool = [f"-XMP-exif:DateTimeOriginal={_exif_zeit(utc)}Z"]
                d.mtime = ort + timedelta(hours=1)
                self.ins_archiv(d, ort.date(), g15.ordner, meldungen.TB_W_Z)
                continue
            if art == "mitternacht":
                t = self.tag(2023, 2026)
                zeit = datetime(t.year, t.month, t.day, 23, 59, 59) if (i // 4) % 2 == 0 else datetime(t.year, t.month, t.day, 0, 0, 0)
                d = self.foto("zeitzone", g, zeit, ordner=ordner, warum=meldungen.TB_W_MITTERNACHT + " " + meldungen.TB_W_ALIAS)
                continue
            ort_name, versatz, stunde = {"newyork": ("New York", "-05:00", 23), "tokio": ("Tokio", "+09:00", 6)}[art]
            t = self.tag(2023, 2026)
            if art == "newyork" and 3 <= t.month <= 10:
                versatz = "-04:00"
            zeit = datetime(t.year, t.month, t.day, stunde, 30, 0)
            d = self.foto("zeitzone", g, zeit, ordner=ordner,
                          warum=meldungen.TB_W_FREMDE_ZONE.format(ort=ort_name, uhrzeit=f"{zeit:%H:%M}") + " " + meldungen.TB_W_ALIAS)
            d.exif["offset"] = versatz

    def scans(self, n: int) -> None:
        scanner = [("EPSON", "Perfection V600", "EPSON Perfection V600", "tif"),
                   ("PLUSTEK", "OpticFilm 8200i", "PLUSTEK OpticFilm 8200i", "tif"),
                   ("Noritsu Koki", "QSS-32_33", "Noritsu Koki QSS-32_33", "jpg"),
                   ("FUJIFILM", "SP-3000", "SP-3000", "jpg"),
                   ("EPSON", "EPSON Perfection V850", "EPSON Perfection V850", "tif")]
        for i in range(n):
            make, model, text, form = scanner[i % len(scanner)]
            zeit = self.uhrzeit(self.tag(2005, 2015))
            stamm = self.ausgedacht("Film_{n:04d}")
            d = self.neu(f"{QUELLE}/Scans/Filme/{stamm}.{form}", "foto", form, "scan", True, geraet=text, kamera="Analog",
                         alias=True, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            if form == "tif":
                d.exiftool = [f"-EXIF:Make={make}", f"-EXIF:Model={model}", f"-EXIF:DateTimeOriginal={_exif_zeit(zeit)}"]
            else:
                d.exif = self.exif_werte(None, zeit, make=make, model=model, offset=False)
            d.mtime = zeit + timedelta(seconds=30)
            self.ins_archiv(d, zeit.date(), "Analog", meldungen.TB_W_SCAN)

    def png_webp(self, n: int) -> None:
        g = GERAETE["pixel8"]
        for i in range(n):
            zeit = self.uhrzeit(self.tag(2019, 2026))
            if i % 2 == 0:
                d = self.neu(f"{QUELLE}/Grafiken/{self.ausgedacht('Diagramm_{n:03d}')}.png", "foto", "png", "png_webp",
                             True, kamera=UNBEKANNT, aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_PNG)
                d.exiftool = [f"-PNG:CreationTime={_exif_zeit(zeit)}"]
                self.ins_archiv(d, zeit.date(), UNBEKANNT, meldungen.TB_W_PNG)
            else:
                zeit = self.uhrzeit(self.tag(g.von, g.bis))
                d = self.neu(f"{QUELLE}/Handy Pixel 8/Exporte/{self.ausgedacht('PXL_Export_{n:03d}')}.webp", "foto", "webp",
                             "png_webp", True, geraet=g.text, kamera=g.ordner, aufnahme=meldungen.tb_zeit(zeit),
                             datumsquelle=meldungen.TB_DQ_DTO)
                d.exiftool = [f"-EXIF:Make={g.make}", f"-EXIF:Model={g.model}", f"-EXIF:DateTimeOriginal={_exif_zeit(zeit)}"]
                self.ins_archiv(d, zeit.date(), g.ordner, meldungen.TB_W_WEBP)
            d.mtime = zeit + timedelta(minutes=3)

    def gruppe_getrennt(self, n: int) -> None:
        g8, g15 = GERAETE["iphone8"], GERAETE["iphone15"]
        ordner = f"{QUELLE}/Handy alt und neu gemischt"
        for i in range(max(1, n // 2)):
            stamm = f"IMG_{i + 1:04d}"
            alt = self.uhrzeit(self.tag(2017, 2019))
            neu = self.uhrzeit(self.tag(2024, 2026))
            j = self.neu(f"{ordner}/{stamm}.JPG", "foto", "jpg", "gruppe_getrennt", True, geraet=g8.text, kamera=g8.ordner,
                         aufnahme=meldungen.tb_zeit(alt), datumsquelle=meldungen.TB_DQ_DTO)
            j.exif = self.exif_werte(g8, alt)
            j.mtime = alt + timedelta(seconds=3)
            self.ins_archiv(j, alt.date(), g8.ordner, meldungen.TB_W_GRUPPE_GETRENNT.format(andere=f"{stamm}.MOV"))
            v = self.neu(f"{ordner}/{stamm}.MOV", "video", "mov", "gruppe_getrennt", True, geraet=g15.text,
                         kamera=g15.ordner, aufnahme=meldungen.tb_zeit(neu), datumsquelle=meldungen.tb_dq_zone(zone_text(neu)))
            v.film = {"marke": b"qt  ", "utc": von_heimat(neu)}
            v.exiftool = [f"-Keys:CreationDate={_exif_zeit(neu)}{zone_text(neu)}", "-Keys:Make=Apple", f"-Keys:Model={g15.model}"]
            v.mtime = neu + timedelta(seconds=20)
            self.ins_archiv(v, neu.date(), g15.ordner, meldungen.TB_W_GRUPPE_GETRENNT.format(andere=f"{stamm}.JPG"))

    def pfade(self, n: int) -> None:
        g = GERAETE["a7c2"]
        g2 = GERAETE["xt5"]
        tief = f"{QUELLE}/Sonderfälle/tief/" + "/".join(f"ebene_{k:02d}" for k in range(1, 13))
        langer_name = ("sehr_langer_dateiname_" * 9)[:180]
        namen = [
            (f"{QUELLE}/Sonderfälle/Urlaub Ägypten 2019 – Nil & Wüste", "Kamel #1 (groß) [Abend]", ".jpg", g2, meldungen.TB_W_PFAD),
            (f"{QUELLE}/Sonderfälle", "Oma's 80. Geburtstag 100% schön", ".jpg", g2, meldungen.TB_W_PFAD),
            (f"{QUELLE}/Sonderfälle", "Strand 🌊 und Sonne ☀", ".jpg", g2, meldungen.TB_W_PFAD),
            (f"{QUELLE}/Sonderfälle", unicodedata.normalize("NFD", "Mädchen mit Hüten"), ".jpg", g2, meldungen.TB_W_PFAD),
            (f"{QUELLE}/Sonderfälle/Ünïcödé Ørdner", "Café Crème", ".JPEG", g2, meldungen.TB_W_PFAD),
            (f"{QUELLE}/Sonderfälle", "Leerzeichen  doppelt", ".jpg", g2, meldungen.TB_W_PFAD),
            (tief, langer_name, ".jpg", g, meldungen.TB_W_LANG + " " + meldungen.TB_W_ALIAS),
            (f"{QUELLE}/.versteckt", "IMG_7001", ".jpg", g2, meldungen.TB_W_VERSTECKT),
        ]
        for i in range(n):
            ordner, stamm, endung, gg, warum = namen[i % len(namen)]
            if i >= len(namen):
                stamm = f"{stamm} ({i // len(namen) + 1})"
            zeit = self.uhrzeit(self.tag(gg.von, gg.bis))
            self.foto("pfade", gg, zeit, ordner=ordner, stamm=stamm, endung=endung, warum=warum)

    def kameranamen(self, n: int) -> None:
        faelle = [
            ("Testwerk", 'Cam:Pro/2 "X"?', meldungen.TB_W_KAMERANAME),
            ("Testwerk", "Retro Cam.", meldungen.TB_W_KAMERANAME),
            ("Testwerk", "CON", meldungen.TB_W_GERAETENAME),
            ("Agfa", "", meldungen.TB_W_NUR_HERSTELLER),
            ("Testwerk", "  Mehrfach   Leer  ", meldungen.TB_W_KAMERANAME),
            ("Testwerk", "Kamera Ü", meldungen.TB_W_KAMERA),
            ("SONY", "ilce-7cm2", meldungen.TB_W_ALIAS + " " + meldungen.TB_W_KLEIN),
            ("EPSON", "Perfection V850", meldungen.TB_W_SCAN),
        ]
        for i in range(n):
            make, model, warum = faelle[i % len(faelle)]
            kamera, alias = kameraordner(make, model)
            zeit = self.uhrzeit(self.tag(2016, 2026))
            stamm = self.ausgedacht("Kamera_{n:03d}")
            text = f"{make} {model.strip()}".strip() if model.strip() else make
            d = self.neu(f"{QUELLE}/Kameranamen Sonderfälle/{stamm}.jpg", "foto", "jpg", "kameraname", True,
                         geraet=text if model else f"{make} (kein Modell)", kamera=kamera, alias=alias,
                         aufnahme=meldungen.tb_zeit(zeit), datumsquelle=meldungen.TB_DQ_DTO)
            d.exif = self.exif_werte(None, zeit, make=make, model=model)
            d.mtime = zeit + timedelta(seconds=2)
            self.ins_archiv(d, zeit.date(), kamera, warum)

    def kamera(self, n: int) -> None:
        """Die Masse: Kamerafotos mit Datum und Modell, in Aufnahmetagen."""
        summe = sum(_GEWICHTE.values())
        anteile_je = {k: n * w // summe for k, w in _GEWICHTE.items()}
        rest = n - sum(anteile_je.values())
        for k in list(_GEWICHTE)[:rest]:
            anteile_je[k] += 1
        for kennung, m in anteile_je.items():
            g = GERAETE[kennung]
            for zeit in self.zeiten(g, m)[:m]:
                self.foto("kamera", g, zeit)
        while self.nr < self.anzahl:          # falls zeiten() eine Zeit wegen eines reservierten Tags verwarf
            g = GERAETE["a7c2"]
            self.foto("kamera", g, self.uhrzeit(self.tag(g.von, g.bis)))

    def doppelte(self) -> None:
        """Gleicher Inhalt zweimal in der Quelle: Kopien in einem Ordner, der in
        der Reihenfolge der Quelle hinter allen anderen kommt."""
        kandidaten = [d for d in self.dateien if d.kategorie == "kamera" and d.form == "jpg"]
        anzahl = max(3, len(kandidaten) // 100)
        for i, original in enumerate(self.rng.sample(kandidaten, min(anzahl, len(kandidaten)))):
            stamm, endung = original.name.rsplit(".", 1)
            name = (original.name, f"Kopie von {original.name}", f"{stamm} (2).{endung}")[i % 3]
            d = self.neu(f"{QUELLE}/zz Doppelt/{name}", "foto", "jpg", "doppelt", False, geraet=original.geraet,
                         kamera=original.kamera, alias=original.alias, aufnahme=original.aufnahme,
                         datumsquelle=original.datumsquelle)
            d.kopie_von = original
            d.erwartung = DOPPELT
            d.ziel = original.ziel
            d.warum = meldungen.TB_W_DOPPELT.format(kopie=d.rel[len(QUELLE) + 1:])
            d.mtime = original.mtime
            original.warum = f"{original.warum} {d.warum}"

    def sonstiges(self) -> None:
        ordner = f"{QUELLE}/Sonstiges"
        dateien = [
            ("Notizen.txt", "Einkaufsliste: Milch, Brot, Speicherkarte\n".encode("utf-8"), False),
            ("Rechnung 2021.pdf", formate.pdf("Rechnung 2021 - kein Foto"), False),
            ("Lied.mp3", b"ID3\x03\x00\x00\x00\x00\x00\x0f" + b"\x00" * 64, False),
            ("Präsentation.pptx", b"PK\x03\x04" + "kein Foto".encode("utf-8") + b"\x00" * 32, False),
            ("Animation.gif", formate.gif(), False),
            ("Thumbs.db", b"Rest einer Windows-Vorschau", True),
            ("desktop.ini", b"[.ShellClassInfo]\r\n", True),
            (".DS_Store", b"Bud1\x00\x00\x00\x00", True),
        ]
        for name, inhalt, rest in dateien:
            d = self.neu(f"{ordner}/{name}", "sonstiges", "bytes", "sonstiges", False)
            d.inhalt, d.rest = inhalt, rest
            d.erwartung = BLEIBT
            d.warum = meldungen.TB_W_SONSTIGES
            d.mtime = datetime(2021, 3, 4, 12, 0, 0)
        # Begleitdatei ohne Bild
        d = self.neu(f"{ordner}/DSC09999.xmp", "sidecar", "xmp", "sonstiges", False)
        d.inhalt = formate.xmp(bewertung=2).encode("utf-8")
        d.erwartung = BLEIBT
        d.warum = meldungen.TB_W_OHNE_HAUPT
        d.mtime = datetime(2021, 3, 4, 12, 0, 0)
        # Eine Vorschau-Datenbank mitten in einem Kameraordner
        g = GERAETE["a7c"]
        d = self.neu(f"{QUELLE}/{g.quelle}/100MSDCF/Thumbs.db", "sonstiges", "bytes", "sonstiges", False)
        d.inhalt, d.rest = b"Rest einer Windows-Vorschau (Kameraordner)", True
        d.erwartung = BLEIBT
        d.warum = meldungen.TB_W_SONSTIGES
        d.mtime = datetime(2021, 3, 4, 12, 0, 0)


def planen(anzahl: int = STANDARD_ANZAHL, saat: int = SAAT) -> _Plan:
    """Der ganze Testsatz als Plan - ohne eine Datei anzulegen."""
    teile = anteile(anzahl)
    p = _Plan(anzahl, saat)
    p.vorbelegen()
    p.schon_im_archiv(teile["schon_im_archiv"])
    p.konflikte(teile["konflikt"])
    p.archiv_struktur(teile["archiv_struktur"])
    p.raw_paare(teile["raw_paar"])
    p.raw_allein(teile["raw_allein"])
    p.heic(teile["heic"])
    p.videos(teile["video"])
    p.dateinamen(teile["dateiname"])
    p.xmp_datum(teile["xmp_datum"])
    p.ohne_datum(teile["ohne_datum"])
    p.kaputt(teile["kaputt"])
    p.zeitzonen(teile["zeitzone"])
    p.scans(teile["scan"])
    p.png_webp(teile["png_webp"])
    p.gruppe_getrennt(teile["gruppe_getrennt"])
    p.pfade(teile["pfade"])
    p.kameranamen(teile["kameraname"])
    if p.nr >= anzahl:
        raise FotosortFehler(meldungen.tb_anzahl_zu_klein(MINDESTANZAHL))
    p.kamera(anzahl - p.nr)
    p.doppelte()
    p.sonstiges()
    if p.nr != anzahl:
        raise AssertionError(f"Testbilder: {p.nr} statt {anzahl} geplant")
    return p


# ------------------------------------------------------------- Zeichnen ----


def qt_bereit() -> None:
    """Qt braucht fuer Schriften eine Anwendung. Ohne Fenster (Befehl
    "testbilder") eine ohne Bildschirm (offscreen)."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        global _APP
        _APP = QGuiApplication([])


_APP = None


def etikett(d: Datei, gesamt: int) -> dict:
    """Was auf dem Bild steht."""
    if d.erwartung == VORBELEGT:
        kopf = meldungen.TB_KOPF_VORBELEGT
    elif d.nr:
        kopf = meldungen.tb_kopf(d.nr, gesamt)
    else:
        kopf = meldungen.TB_KATEGORIEN.get(d.kategorie, (d.kategorie, ""))[0]
    form = d.name.rsplit(".", 1)[-1].upper() if "." in d.name else d.form.upper()
    felder: list[tuple[str, str, bool]] = [(meldungen.TB_FELD_DATEI, meldungen.tb_datei(d.name, d.art, form), False),
                                           (meldungen.TB_FELD_ORDNER, d.ordner + "/", False)]
    if d.erwartung != VORBELEGT:
        felder.append((meldungen.TB_FELD_GERAET, meldungen.tb_geraet(d.geraet, d.kamera, d.alias), False))
        aufnahme = d.aufnahme + (f" – {d.datumsquelle}" if d.datumsquelle else "")
        felder.append((meldungen.TB_FELD_AUFNAHME, aufnahme, False))
    felder.append((meldungen.TB_FELD_SOLL, soll_text(d), True))
    if d.warum:
        felder.append((meldungen.TB_FELD_WARUM, d.warum, False))
    if d.dazu:
        felder.append((meldungen.TB_FELD_DAZU, ", ".join(d.dazu), False))
    farbe = next((g.farbe for g in _G if g.text == d.geraet or g.ordner == d.kamera), "#4f5b66")
    if d.erwartung == VORBELEGT:
        farbe = "#6d5a3f"
    return {"kopf": kopf, "kategorie": meldungen.TB_KATEGORIEN.get(d.kategorie, (d.kategorie, ""))[0],
            "felder": felder, "farbe": farbe, "fuss": meldungen.TB_FUSS}


def soll_text(d: Datei) -> str:
    if d.erwartung == ARCHIV:
        return meldungen.tb_soll_archiv(d.ziel)
    if d.erwartung == DOPPELT and d.kopie_von is not None:
        return meldungen.tb_soll_doppelt(d.kopie_von.rel[len(QUELLE) + 1:], d.ziel)
    if d.erwartung == SCHON:
        return meldungen.tb_soll_schon(d.ziel)
    if d.erwartung == VORBELEGT:
        return meldungen.TB_SOLL_VORBELEGT
    return meldungen.TB_SOLL_BLEIBT


def zeichnen(e: dict, breite: int, hoehe: int):
    """Die Beschriftung als QImage: farbiger Kopf, darunter die Felder."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

    s = hoehe / 800.0
    bild = QImage(breite, hoehe, QImage.Format.Format_RGB32)
    grund = QColor(e["farbe"])
    bild.fill(QColor.fromHsl(max(0, grund.hslHue()), 70, 236))
    p = QPainter(bild)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    band = int(120 * s)
    p.fillRect(0, 0, breite, band, grund)
    rand = int(40 * s)

    def schrift(px: float, fett: bool = False) -> QFont:
        f = QFont()
        f.setPixelSize(max(6, int(px)))
        f.setBold(fett)
        return f

    p.setPen(QColor("white"))
    p.setFont(schrift(44 * s, True))
    p.drawText(QRect(rand, int(14 * s), breite - 2 * rand, int(56 * s)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, e["kopf"])
    p.setFont(schrift(25 * s))
    p.drawText(QRect(rand, int(68 * s), breite - 2 * rand, int(40 * s)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, e["kategorie"])

    links = int(200 * s)
    x_wert = rand + links
    breite_wert = breite - x_wert - rand
    y = band + int(24 * s)
    unten = hoehe - int(44 * s)
    umbruch = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop)
    for name, wert, fett in e["felder"]:
        groesse_px = 25 * s if not fett else 26 * s
        f_name, f_wert = schrift(21 * s, True), schrift(groesse_px, fett)
        # Pfade duerfen an "/" umbrechen
        text = wert.replace("/", "/​")
        hoehe_text = QFontMetrics(f_wert).boundingRect(QRect(0, 0, breite_wert, 10000), umbruch, text).height()
        if y + min(hoehe_text, int(30 * s)) > unten:
            break
        p.setPen(QColor(grund).darker(140))
        p.setFont(f_name)
        p.drawText(QRect(rand, y + int(3 * s), links - int(10 * s), int(40 * s)), umbruch, name)
        p.setPen(QColor("#15191e"))
        p.setFont(f_wert)
        p.drawText(QRect(x_wert, y, breite_wert, max(0, unten - y)), umbruch, text)
        y += hoehe_text + int(14 * s)
    p.setPen(QColor("#5a636d"))
    p.setFont(schrift(17 * s))
    p.drawText(QRect(rand, hoehe - int(36 * s), breite - 2 * rand, int(28 * s)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, e["fuss"])
    p.end()
    return bild


_QT_FORMATE = {"jpg": b"JPG", "png": b"PNG", "tif": b"TIFF", "webp": b"WEBP"}


def kodieren(bild, form: str, qualitaet: int = 82) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageWriter

    daten = QByteArray()
    puffer = QBuffer(daten)
    puffer.open(QIODevice.OpenModeFlag.WriteOnly)
    schreiber = QImageWriter(puffer, _QT_FORMATE[form])
    if form in ("jpg", "webp"):
        schreiber.setQuality(qualitaet)
    if form == "tif":
        schreiber.setCompression(1)          # LZW - ohne waere ein Scan 3 MB gross
    ok = schreiber.write(bild)
    puffer.close()
    if not ok:
        raise FotosortFehler(meldungen.tb_format_fehlt(form))
    return bytes(daten.data())


def formate_pruefen() -> None:
    """Kann Qt hier JPEG, PNG, TIFF und WebP schreiben? Sonst sofort abbrechen."""
    from PySide6.QtGui import QImageWriter
    da = {bytes(f).decode().lower() for f in QImageWriter.supportedImageFormats()}
    for form, name in _QT_FORMATE.items():
        if name.decode().lower() not in da:
            raise FotosortFehler(meldungen.tb_format_fehlt(form))


GROESSE_FOTO = (1200, 800)
GROESSE_VORSCHAU = (960, 640)
GROESSE_THM = (480, 320)


def zeichnen_fuer(d: Datei, gesamt: int) -> tuple[dict | None, object]:
    """(Etikett, QImage) einer Datei - nur das Zeichnen. Es braucht Schriften
    und laeuft deshalb immer im aufrufenden Strang: Mehrere Straenge, die
    gleichzeitig zum ersten Mal Schriften laden, brachten Qt im Container zum
    Absturz. Das Kodieren (inhalt_bauen) darf danach auf allen Kernen laufen."""
    if d.inhalt is not None:
        return None, None
    e = etikett(d.etikett_von or d, gesamt)
    if d.form in ("jpg", "png", "tif", "webp"):
        groesse = GROESSE_FOTO
    elif d.form == "thm":
        groesse = GROESSE_THM
    else:
        groesse = GROESSE_VORSCHAU
    return e, zeichnen(e, *groesse)


def inhalt_bauen(d: Datei, gesamt: int, e: dict | None = None, bild=None) -> bytes:
    """Die Bytes einer Datei (ohne die Felder, die danach ExifTool eintraegt)."""
    if d.inhalt is not None:
        return d.inhalt
    if bild is None:
        e, bild = zeichnen_fuer(d, gesamt)
    kommentar = f"{e['kopf']}: {soll_text(d.etikett_von or d)}"
    if d.form in ("jpg", "png", "tif", "webp"):
        daten = kodieren(bild, d.form)
        if d.form == "jpg" and d.exif is not None:
            daten = formate.jpeg_mit_exif(daten, dict(d.exif, titel=e["kopf"], kommentar=kommentar))
        return daten
    if d.form == "thm":
        return kodieren(bild, "jpg", 75)
    vorschau = kodieren(bild, "jpg", 78)
    if d.form == "raw":
        return formate.raw_datei(dict(d.exif or {}, titel=e["kopf"], kommentar=kommentar), vorschau,
                                 dng=d.name.lower().endswith(".dng"))
    if d.form == "heic":
        return formate.heic(dict(d.exif or {}, titel=e["kopf"], kommentar=kommentar), vorschau)
    if d.form in ("mov", "mp4", "3gp"):
        f = d.film or {}
        return formate.film(vorschau, *GROESSE_VORSCHAU, marke=f.get("marke", b"qt  "), zeit_utc=f.get("utc"),
                            sony_xml=f.get("sony_xml"))
    if d.form == "avi":
        return formate.avi(vorschau, *GROESSE_VORSCHAU, (d.film or {})["idit"])
    raise AssertionError(f"Testbilder: unbekannte Form {d.form}")


# ------------------------------------------------------------- Erzeugen ----


@dataclass
class Ergebnis:
    ordner: Path
    bilder: int = 0
    dateien: int = 0
    bytes_: int = 0
    sekunden: float = 0.0


def _melden(melden, text: str, erledigt: int = 0, gesamt: int = 0) -> None:
    if melden is not None:
        melden(text, erledigt, gesamt)


def _anhalten_pruefen(stop: threading.Event | None) -> None:
    if stop is not None and stop.is_set():
        raise Abgebrochen(meldungen.TB_ABGEBROCHEN)


def _pfad(ordner: Path, rel: str) -> Path:
    return ordner.joinpath(*rel.split("/"))


def _exklusiv_schreiben(pfad: Path, daten: bytes) -> None:
    pfade.lang(pfad.parent).mkdir(parents=True, exist_ok=True)
    with open(pfade.lang(pfad), "xb") as f:
        f.write(daten)


def ordner_leer(ordner: Path) -> bool:
    try:
        return not any(os.scandir(pfade.lang(ordner)))
    except FileNotFoundError:
        return True


def erzeugen(ordner: Path, anzahl: int = STANDARD_ANZAHL, exiftool: str | None = None, melden=None,
             stop: threading.Event | None = None, prozesse_zahl: int | None = None) -> Ergebnis:
    """Den Testsatz in ordner anlegen (neu oder leer)."""
    begonnen = time.monotonic()
    ordner = Path(ordner).absolute()
    if not ordner_leer(ordner):
        raise FotosortFehler(meldungen.tb_ordner_nicht_leer(ordner))
    heute = datetime.now().date()
    if heute < ENDE + timedelta(days=2):
        raise FotosortFehler(meldungen.tb_uhr_falsch(heute))
    if not exiftool:
        raise FotosortFehler(meldungen.TB_EXIFTOOL_FEHLT)
    _melden(melden, meldungen.TB_SCHRITT_PLANEN)
    plan = planen(anzahl)
    qt_bereit()
    formate_pruefen()
    pfade.lang(ordner).mkdir(parents=True, exist_ok=True)
    (pfade.lang(ordner) / QUELLE).mkdir(exist_ok=True)
    (pfade.lang(ordner) / ZIEL).mkdir(exist_ok=True)
    ergebnis = Ergebnis(ordner, bilder=plan.nr)

    # 1. Zeichnen (hier, in einem Strang) und kodieren und schreiben (alle
    #    Kerne). Kopien kommen spaeter.
    eigene = [d for d in plan.dateien if d.kopie_von is None]
    fertig = 0
    sperre = threading.Lock()
    kerne = max(1, os.cpu_count() or 1)

    def schreiben(d: Datei, e, bild) -> None:
        nonlocal fertig
        _exklusiv_schreiben(_pfad(ordner, d.rel), inhalt_bauen(d, plan.anzahl, e, bild))
        with sperre:
            fertig += 1
            if fertig % 50 == 0 or fertig == len(eigene):
                _melden(melden, meldungen.TB_SCHRITT_BILDER, fertig, len(eigene))

    laufend: list = []
    with ThreadPoolExecutor(max_workers=kerne) as pool:
        try:
            for d in eigene:
                _anhalten_pruefen(stop)
                e, bild = zeichnen_fuer(d, plan.anzahl)
                laufend.append(pool.submit(schreiben, d, e, bild))
                if len(laufend) > 2 * kerne:        # nicht mehr Bilder im Speicher als noetig
                    laufend.pop(0).result()
            for z in laufend:
                z.result()
        finally:
            for z in laufend:
                z.cancel()

    # 2. Kameradaten, die ExifTool eintraegt (PNG, TIFF, WebP, Videos, XMP-Felder)
    mit_exiftool = [d for d in eigene if d.exiftool]
    _exiftool_schreiben(ordner, mit_exiftool, exiftool, melden, stop, prozesse_zahl)

    # 3. Kopien: doppelt in der Quelle, schon im Archiv
    kopien = [d for d in plan.dateien if d.kopie_von is not None]
    for i, d in enumerate(kopien, start=1):
        _anhalten_pruefen(stop)
        with open(pfade.lang(_pfad(ordner, d.kopie_von.rel)), "rb") as f:
            _exklusiv_schreiben(_pfad(ordner, d.rel), f.read())
        _melden(melden, meldungen.TB_SCHRITT_KOPIEN, i, len(kopien))

    # 4. Aenderungszeiten und Pruefsummen
    for i, d in enumerate(plan.dateien, start=1):
        if d.mtime is not None:
            t = d.mtime.timestamp()
            os.utime(pfade.lang(_pfad(ordner, d.rel)), (t, t))
    _pruefsummen(ordner, plan.dateien, melden, stop)
    for d in plan.dateien:
        ergebnis.bytes_ += os.stat(pfade.lang(_pfad(ordner, d.rel))).st_size
    ergebnis.dateien = len(plan.dateien)

    # 5. Uebersicht, Erwartung, Marken - die Marke zuletzt: Sie sagt "vollstaendig".
    _melden(melden, meldungen.TB_SCHRITT_LISTE)
    _schreiben_text(ordner / "LIESMICH.txt", meldungen.TB_LIESMICH)
    _schreiben_text(ordner / "Erwartung.csv", _csv(plan), bom=True)
    _schreiben_text(ordner / "Übersicht.html", _uebersicht_html(plan, ordner))
    _schreiben_text(ordner / TESTBAUM_MARKE, "kuenstlicher Testbaum (fotosort Testbilder, SPEC Abschnitt 11)\n")
    _schreiben_text(ordner / MARKE, json.dumps(_manifest(plan), ensure_ascii=False, indent=1))
    ergebnis.sekunden = time.monotonic() - begonnen
    return ergebnis


def _schreiben_text(pfad: Path, text: str, bom: bool = False) -> None:
    _exklusiv_schreiben(pfad, (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def _exiftool_schreiben(ordner: Path, dateien: list[Datei], programm: str, melden, stop, prozesse_zahl) -> None:
    """ExifTool traegt Felder ein, die nicht im eigenen EXIF-Block stehen -
    mehrere Prozesse gleichzeitig, je einer mit einer Argumentdatei (-@)."""
    from .metadaten import exiftool_befehl

    if not dateien:
        return
    stapel = [dateien[i:i + 60] for i in range(0, len(dateien), 60)]
    erledigt = 0
    sperre = threading.Lock()

    def ein_stapel(teil: list[Datei]) -> str:
        nonlocal erledigt
        _anhalten_pruefen(stop)
        zeilen: list[str] = []
        for d in teil:
            zeilen += ["-charset", "filename=utf8", "-overwrite_original", "-m", *d.exiftool,
                       str(_pfad(ordner, d.rel)), "-execute"]
        fertig = subprocess.run(exiftool_befehl(programm) + ["-charset", "filename=utf8", "-@", "-"],
                                input="\n".join(zeilen) + "\n", capture_output=True, text=True, encoding="utf-8",
                                errors="replace", check=False, **prozesse.unsichtbar())
        fehler = [z for z in (fertig.stdout + "\n" + fertig.stderr).splitlines()
                  if z.startswith("Error") or "weren't updated due to errors" in z]
        with sperre:
            erledigt += len(teil)
            _melden(melden, meldungen.TB_SCHRITT_EXIFTOOL, erledigt, len(dateien))
        return "\n".join(fehler)

    with ThreadPoolExecutor(max_workers=max(1, prozesse_zahl or min(8, os.cpu_count() or 1))) as pool:
        fehler = [z.result() for z in [pool.submit(ein_stapel, t) for t in stapel]]
    text = "\n".join(f for f in fehler if f)
    if text:
        raise FotosortFehler(meldungen.tb_exiftool_fehler(text[:2000]))


def _pruefsummen(ordner: Path, dateien: list[Datei], melden, stop) -> None:
    fertig = 0
    sperre = threading.Lock()

    def eine(d: Datei) -> None:
        nonlocal fertig
        d.blake3 = hashes.blake3_datei(pfade.lang(_pfad(ordner, d.rel)), stop)
        with sperre:
            fertig += 1
            if fertig % 200 == 0 or fertig == len(dateien):
                _melden(melden, meldungen.TB_SCHRITT_HASH, fertig, len(dateien))

    try:
        with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1)) as pool:
            for z in [pool.submit(eine, d) for d in dateien]:
                z.result()
    except hashes.Abgebrochen as fehler:
        raise Abgebrochen(meldungen.TB_ABGEBROCHEN) from fehler


# ---------------------------------------------------- Liste und Uebersicht --


def _eintrag(d: Datei) -> dict:
    return {
        "nr": d.nr, "datei": d.rel, "art": d.art, "kategorie": d.kategorie, "geraet": d.geraet,
        "kamera": d.kamera, "aufnahme": d.aufnahme, "datumsquelle": d.datumsquelle, "erwartung": d.erwartung,
        "ziel": d.ziel, "warum": d.warum, "dazu": d.dazu, "blake3": d.blake3, "rest": d.rest,
        "original": d.kopie_von.rel if d.kopie_von is not None and d.erwartung == DOPPELT else "",
    }


def _manifest(plan: _Plan) -> dict:
    return {"format": FORMAT, "programm": f"fotosort {__version__}", "erzeugt": datetime.now().isoformat(timespec="seconds"),
            "anzahl": plan.anzahl, "saat": SAAT, "dateien": [_eintrag(d) for d in plan.dateien]}


def _csv(plan: _Plan) -> str:
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    w.writerow(meldungen.TB_CSV_KOPF)
    for d in plan.dateien:
        w.writerow([d.nr or "", d.rel, meldungen.TB_ART.get(d.art, d.art), meldungen.TB_KATEGORIEN.get(d.kategorie, (d.kategorie,))[0],
                    d.geraet, d.kamera, d.aufnahme, d.datumsquelle, meldungen.TB_ERWARTUNG.get(d.erwartung, d.erwartung),
                    soll_text(d), d.warum, ", ".join(d.dazu), d.blake3])
    return puffer.getvalue()


_CSS = """
:root { color-scheme: light dark; --grund: #ffffff; --text: #1d2125; --leise: #5c6670; --linie: #d7dce1;
  --kopf: #f3f5f7; --gut: #1c7c3c; --schlecht: #b3261e; }
@media (prefers-color-scheme: dark) { :root { --grund: #16191c; --text: #e4e7ea; --leise: #9aa4ad; --linie: #2f353b;
  --kopf: #1f2327; --gut: #5cc485; --schlecht: #ff8a80; } }
body { background: var(--grund); color: var(--text); font: 14px/1.45 "Segoe UI", system-ui, sans-serif; margin: 0;
  padding: 24px 16px 48px; }
main { max-width: 1400px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 28px 0 8px; }
p, li { max-width: 900px; } .leise { color: var(--leise); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; vertical-align: top; padding: 5px 8px; border-bottom: 1px solid var(--linie); }
th { background: var(--kopf); position: sticky; top: 0; }
td.pfad { font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; word-break: break-all; }
.gut { color: var(--gut); font-weight: 600; } .schlecht { color: var(--schlecht); font-weight: 600; }
.wrap { overflow-x: auto; }
"""


def _uebersicht_html(plan: _Plan, ordner: Path) -> str:
    e = html.escape
    zaehler: dict[str, int] = {}
    for d in plan.dateien:
        zaehler[d.kategorie] = zaehler.get(d.kategorie, 0) + 1
    teile = [f"<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
             f" initial-scale=1'><title>{e(meldungen.TB_UEBERSICHT_TITEL)}</title><style>{_CSS}</style></head><body><main>",
             f"<h1>{e(meldungen.TB_UEBERSICHT_TITEL)}</h1>",
             f"<p class='leise'>{e(meldungen.anzahl(plan.nr))} Testbilder, {e(meldungen.anzahl(len(plan.dateien)))} Dateien"
             f" – fotosort {e(__version__)}</p>"]
    teile.append("<ol>" + "".join(f"<li>{e(t.format(ziel=ordner / ZIEL, quelle=ordner / QUELLE))}</li>"
                                  for t in meldungen.TB_ANLEITUNG[1:]) + "</ol>")
    teile.append("<h2>Was geprüft wird</h2><div class='wrap'><table><tr><th>Kategorie</th><th>Dateien</th><th>Worum es geht</th></tr>")
    for k, (titel, was) in meldungen.TB_KATEGORIEN.items():
        if zaehler.get(k):
            teile.append(f"<tr><td>{e(titel)}</td><td>{zaehler[k]}</td><td>{e(was)}</td></tr>")
    teile.append("</table></div><h2>Alle Dateien</h2><div class='wrap'><table><tr>"
                 + "".join(f"<th>{e(k)}</th>" for k in ("Nr", "Datei", "Gerät", "Aufnahme", "Soll nach", "Warum")) + "</tr>")
    for d in sorted(plan.dateien, key=lambda d: (d.nr == 0, d.nr, d.rel)):
        teile.append(f"<tr><td>{d.nr or ''}</td><td class='pfad'>{e(d.rel)}</td><td>{e(d.geraet or '–')}<br>"
                     f"<span class='leise'>→ {e(d.kamera)}</span></td><td>{e(d.aufnahme)}<br><span class='leise'>"
                     f"{e(d.datumsquelle)}</span></td><td class='pfad'>{e(soll_text(d))}</td><td>{e(d.warum)}</td></tr>")
    teile.append("</table></div></main></body></html>")
    return "\n".join(teile)


# --------------------------------------------------------------- Pruefen ----


@dataclass
class Befund:
    nr: int
    datei: str
    text: str
    schwer: bool = False     # Inhalt verloren


@dataclass
class Pruefung:
    ordner: Path
    erwartet: int = 0
    richtig: int = 0
    befunde: list = field(default_factory=list)
    hinweise: list = field(default_factory=list)
    verloren: int = 0
    bericht: Path | None = None
    sekunden: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.befunde and not self.verloren


def ist_testordner(ordner: Path) -> bool:
    return (Path(ordner) / MARKE).is_file()


def testordner_von(pfad: Path) -> Path | None:
    """Der Testordner, zu dem eine Quelle oder ein Ziel gehoert (oder None)."""
    pfad = Path(pfad)
    for kandidat in (pfad.parent, pfad):
        if ist_testordner(kandidat):
            return kandidat
    return None


def _alle_dateien(wurzel: Path, ohne: tuple[str, ...] = ()) -> list[str]:
    """Pfade relativ zu wurzel (mit "/"), ohne Programmordner und Verknuepfungen."""
    ergebnis: list[str] = []
    stapel = [""]
    while stapel:
        rel = stapel.pop()
        try:
            eintraege = list(os.scandir(pfade.lang(wurzel / rel) if rel else pfade.lang(wurzel)))
        except OSError:
            continue
        for e in eintraege:
            r = f"{rel}/{e.name}" if rel else e.name
            if e.is_symlink():
                continue
            if e.is_dir(follow_symlinks=False):
                if not rel and e.name in ohne:
                    continue
                stapel.append(r)
            elif e.is_file(follow_symlinks=False):
                ergebnis.append(r)
    return ergebnis


def pruefen(ordner: Path, melden=None, stop: threading.Event | None = None) -> Pruefung:
    """Das sortierte Ziel mit der Erwartung vergleichen; Bericht schreiben."""
    begonnen = time.monotonic()
    ordner = Path(ordner).absolute()
    if not ist_testordner(ordner):
        raise FotosortFehler(meldungen.TB_KEIN_TESTORDNER)
    with open(ordner / MARKE, encoding="utf-8") as f:
        manifest = json.load(f)
    eintraege = manifest["dateien"]
    ziel, quelle = ordner / ZIEL, ordner / QUELLE

    # 1. Alles im Ziel und in der Quelle lesen (BLAKE3)
    im_ziel = _alle_dateien(ziel, (".fotosortierer",))
    in_quelle = _alle_dateien(quelle)
    alle = [(ZIEL, r) for r in im_ziel] + [(QUELLE, r) for r in in_quelle]
    hash_von: dict[tuple[str, str], str] = {}
    fertig = 0
    sperre = threading.Lock()

    def lesen(teil: tuple[str, str]) -> None:
        nonlocal fertig
        try:
            h = hashes.blake3_datei(pfade.lang(ordner / teil[0] / teil[1]), stop)
        except OSError:
            h = ""
        with sperre:
            hash_von[teil] = h
            fertig += 1
            if fertig % 200 == 0 or fertig == len(alle):
                _melden(melden, meldungen.TB_SCHRITT_HASH, fertig, len(alle))

    try:
        with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1)) as pool:
            for z in [pool.submit(lesen, t) for t in alle]:
                z.result()
    except hashes.Abgebrochen as fehler:
        raise Abgebrochen(meldungen.TB_ABGEBROCHEN) from fehler

    ziel_genau = {unicodedata.normalize("NFC", r): hash_von[(ZIEL, r)] for r in im_ziel}
    ziel_gross_klein = {_schluessel(r): r for r in im_ziel}
    orte_ziel: dict[str, list[str]] = {}
    for r in im_ziel:
        orte_ziel.setdefault(hash_von[(ZIEL, r)], []).append(r)
    quelle_genau = {unicodedata.normalize("NFC", r): hash_von[(QUELLE, r)] for r in in_quelle}
    hashes_quelle = {h for (wo, _r), h in hash_von.items() if wo == QUELLE}

    p = Pruefung(ordner)
    erwartete_orte: set[str] = set()
    for e in eintraege:
        if e["erwartung"] in (ARCHIV, VORBELEGT):
            erwartete_orte.add(unicodedata.normalize("NFC", e["ziel"]))

    def befund(e: dict, text: str, schwer: bool = False) -> None:
        p.befunde.append(Befund(e["nr"], e["datei"], text, schwer))

    for e in eintraege:
        p.erwartet += 1
        rel_quelle = e["datei"].split("/", 1)[1] if e["datei"].startswith(QUELLE + "/") else ""
        z = unicodedata.normalize("NFC", e["ziel"])
        if e["erwartung"] in (ARCHIV, VORBELEGT):
            h = ziel_genau.get(z)
            if h == e["blake3"]:
                p.richtig += 1
            elif h is not None:
                befund(e, meldungen.TB_P_ANDERS if e["erwartung"] == ARCHIV else meldungen.TB_P_VORBELEGT_WEG)
            else:
                anders_geschrieben = ziel_gross_klein.get(_schluessel(z))
                orte = [o for o in orte_ziel.get(e["blake3"], []) if unicodedata.normalize("NFC", o) not in erwartete_orte]
                if e["erwartung"] == VORBELEGT:
                    befund(e, meldungen.TB_P_VORBELEGT_WEG)
                elif anders_geschrieben and hash_von[(ZIEL, anders_geschrieben)] == e["blake3"]:
                    befund(e, meldungen.TB_P_STATTDESSEN.format(ort=anders_geschrieben))
                elif orte:
                    befund(e, meldungen.TB_P_STATTDESSEN.format(ort=orte[0]))
                elif rel_quelle and quelle_genau.get(unicodedata.normalize("NFC", rel_quelle)) == e["blake3"]:
                    befund(e, meldungen.TB_P_NOCH_NICHT)
                else:
                    befund(e, meldungen.TB_P_FEHLT)
            if e["erwartung"] == ARCHIV and e["art"] != "sidecar":
                weitere = [o for o in orte_ziel.get(e["blake3"], []) if unicodedata.normalize("NFC", o) != z
                           and unicodedata.normalize("NFC", o) not in erwartete_orte]
                if weitere and h == e["blake3"]:
                    befund(e, meldungen.TB_P_DOPPELT_ARCHIV.format(ort=weitere[0]))
        elif e["erwartung"] in (DOPPELT, SCHON):
            weitere = [o for o in orte_ziel.get(e["blake3"], []) if unicodedata.normalize("NFC", o) != z]
            ok = not weitere
            if weitere:
                befund(e, meldungen.TB_P_DOPPELT_ARCHIV.format(ort=weitere[0]))
            if e["erwartung"] == SCHON and quelle_genau.get(unicodedata.normalize("NFC", rel_quelle)) != e["blake3"]:
                ok = False
                befund(e, meldungen.TB_P_QUELLE_FEHLT if unicodedata.normalize("NFC", rel_quelle) not in quelle_genau
                       else meldungen.TB_P_QUELLE_ANDERS)
            p.richtig += ok
        else:   # bleibt
            h = quelle_genau.get(unicodedata.normalize("NFC", rel_quelle))
            if h == e["blake3"] or (h is None and e.get("rest")):
                p.richtig += 1
            else:
                befund(e, meldungen.TB_P_QUELLE_FEHLT if h is None else meldungen.TB_P_QUELLE_ANDERS)
        # Nichts darf verloren sein: Der Inhalt liegt in der Quelle (auch im
        # Ordner _geloescht_) oder im Ziel.
        if e["blake3"] and not e.get("rest") and e["blake3"] not in orte_ziel and e["blake3"] not in hashes_quelle:
            p.verloren += 1
            befund(e, meldungen.TB_P_VERLOREN, schwer=True)

    # 2. Was liegt im Ziel, das niemand erwartet?
    bekannte = {unicodedata.normalize("NFC", e["ziel"]) for e in eintraege if e["erwartung"] in (ARCHIV, VORBELEGT)}
    for r in sorted(im_ziel):
        rn = unicodedata.normalize("NFC", r)
        if rn in bekannte:
            continue
        if rn.lower().endswith(".xmp") and any(rn.rsplit(".", 1)[0] == b.rsplit(".", 1)[0] or rn[:-4] == b for b in bekannte):
            p.hinweise.append(f"Ziel/{r}: {meldungen.TB_P_XMP_SICHTEN}")
            continue
        p.befunde.append(Befund(0, f"{ZIEL}/{r}", meldungen.TB_P_UNERWARTET))
    p.sekunden = time.monotonic() - begonnen
    p.bericht = _bericht_schreiben(p, manifest)
    return p


def _bericht_schreiben(p: Pruefung, manifest: dict) -> Path:
    """Pruefbericht.html - neu, nie ueberschrieben: Gibt es ihn schon, bekommt der neue eine Nummer."""
    e = html.escape
    zusammen = meldungen.tb_pruef_zusammenfassung(p.richtig, p.erwartet, len(p.befunde), p.verloren)
    klasse = "gut" if p.ok else "schlecht"
    teile = [f"<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
             f" initial-scale=1'><title>{e(meldungen.TB_PRUEF_TITEL)}</title><style>{_CSS}</style></head><body><main>",
             f"<h1>{e(meldungen.TB_PRUEF_TITEL)}</h1>",
             f"<p class='leise'>{e(datetime.now().strftime('%d.%m.%Y %H:%M'))} – fotosort {e(__version__)}</p>"]
    teile += [f"<p class='{klasse}'>{e(z)}</p>" for z in zusammen.splitlines()]
    if p.befunde:
        teile.append("<h2>Abweichungen</h2><div class='wrap'><table><tr><th>Nr</th><th>Datei</th><th>Befund</th></tr>")
        for b in p.befunde:
            teile.append(f"<tr><td>{b.nr or ''}</td><td class='pfad'>{e(b.datei)}</td>"
                         f"<td class='{'schlecht' if b.schwer else ''}'>{e(b.text)}</td></tr>")
        teile.append("</table></div>")
    if p.hinweise:
        teile.append("<h2>Hinweise</h2><ul>" + "".join(f"<li>{e(h)}</li>" for h in p.hinweise) + "</ul>")
    teile.append("</main></body></html>")
    name = "Prüfbericht.html"
    k = 1
    while (p.ordner / name).exists():
        k += 1
        name = f"Prüfbericht ({k}).html"
    pfad = p.ordner / name
    _schreiben_text(pfad, "\n".join(teile))
    return pfad


def pruef_text(p: Pruefung, grenze: int = 30) -> str:
    """Kurzfassung fuer Konsole und Fenster."""
    zeilen = [meldungen.tb_pruef_zusammenfassung(p.richtig, p.erwartet, len(p.befunde), p.verloren)]
    for b in p.befunde[:grenze]:
        rel = b.datei.split("/", 1)[1] if b.datei.startswith(QUELLE + "/") else b.datei
        zeilen.append("  " + (meldungen.tb_pruef_zeile(b.nr, rel, b.text) if b.datei.startswith(QUELLE + "/")
                              else f"{b.datei}: {b.text}"))
    if len(p.befunde) > grenze:
        zeilen.append(f"  … und {meldungen.anzahl(len(p.befunde) - grenze)} weitere (siehe Prüfbericht)")
    if p.bericht is not None:
        zeilen.append(meldungen.tb_pruef_bericht_wo(p.bericht))
    return "\n".join(zeilen)
