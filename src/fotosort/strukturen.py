"""Datum aus Ordnernamen in jeder Schreibweise - reine Logik (Runde 3a).

Ein Archiv, das jemand von Hand angelegt hat, schreibt den Januar 2021 als
"2021.01", "01.2021", "Januar 2021" oder als "01" unter "2021". Das Programm
soll solche Ordner als das erkennen, was sie sind (Entscheidung des Nutzers
vom 26.10.2026: "bereits erstandene Strukturen kennen"), statt daneben einen
zweiten Ordner in eigener Schreibweise anzulegen.

Erkannt wird ein Datum nur am Anfang des Namens ("2021-01-15 Hochzeit"), und
nur mit gueltigen Werten (Jahr 1900-2100). "Hochzeit 2021" bleibt ohne Datum:
Dort ist das Jahr Teil eines Namens, keine Ordnung.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

JAHR_VON, JAHR_BIS = 1900, 2100

#: Monatsnamen, deutsch und englisch, ausgeschrieben und abgekuerzt.
MONATE: dict[str, int] = {}
for _nr, _namen in enumerate((
    ("januar", "jänner", "jaenner", "jan", "january"),
    ("februar", "feb", "february"),
    ("märz", "maerz", "mär", "mrz", "mar", "march"),
    ("april", "apr"),
    ("mai", "may"),
    ("juni", "jun", "june"),
    ("juli", "jul", "july"),
    ("august", "aug"),
    ("september", "sep", "sept"),
    ("oktober", "okt", "oct", "october"),
    ("november", "nov"),
    ("dezember", "dez", "dec", "december"),
), start=1):
    for _n in _namen:
        MONATE[_n] = _nr

_RANG = {"jahr": 1, "monat": 2, "tag": 3}


@dataclass(frozen=True)
class Zeitraum:
    """Jahr, Monat oder Tag, den ein Ordner nennt."""
    art: str            # "jahr" | "monat" | "tag"
    jahr: int
    monat: int = 0
    tag: int = 0

    def umfasst(self, d: date) -> bool:
        if d.year != self.jahr:
            return False
        if self.art == "jahr":
            return True
        if d.month != self.monat:
            return False
        return self.art == "monat" or d.day == self.tag

    def enthaelt(self, anderer: "Zeitraum") -> bool:
        """Liegt der andere Zeitraum ganz in diesem (oder ist er gleich)?"""
        if _RANG[anderer.art] < _RANG[self.art] or anderer.jahr != self.jahr:
            return False
        if self.art == "jahr":
            return True
        if anderer.monat != self.monat:
            return False
        return self.art == "monat" or anderer.tag == self.tag

    def feiner_als(self, anderer: "Zeitraum") -> bool:
        return _RANG[self.art] > _RANG[anderer.art]

    @property
    def rang(self) -> int:
        return _RANG[self.art]


# Ein Datum endet am Namensende oder vor einem Zeichen, das kein Buchstabe und
# keine Ziffer ist ("2021-01 Januar", "2021_Hochzeit") - nie mitten in einem Wort.
_ENDE = r"(?=$|[^0-9A-Za-zÄÖÜäöüß])"
_T = r"[-._ ]"
# Reihenfolge: das Feinste zuerst. Passt ein Muster der Form nach, aber mit
# unmoeglichen Werten (2021-13, 2021-02-30), ist das kein Datum - es wird
# nicht ersatzweise ein groberes daraus.
_ZAHLENMUSTER = (
    ("ymd", re.compile(rf"^(\d{{4}}){_T}(\d{{1,2}}){_T}(\d{{1,2}}){_ENDE}")),
    ("ymd", re.compile(rf"^(\d{{4}})(\d{{2}})(\d{{2}}){_ENDE}")),
    ("dmy", re.compile(rf"^(\d{{1,2}}){_T}(\d{{1,2}}){_T}(\d{{4}}){_ENDE}")),
    ("ym", re.compile(rf"^(\d{{4}}){_T}(\d{{1,2}}){_ENDE}")),
    ("my", re.compile(rf"^(\d{{1,2}}){_T}(\d{{4}}){_ENDE}")),
)
_NAME_JAHR = re.compile(rf"^([A-Za-zÄÖÜäöüß]+)\.?(?:{_T})+(\d{{4}}){_ENDE}")
_JAHR_NAME = re.compile(rf"^(\d{{4}})(?:{_T})+([A-Za-zÄÖÜäöüß]+)\.?{_ENDE}")
_JAHR = re.compile(rf"^(\d{{4}}){_ENDE}")
_ZAHL = re.compile(rf"^(\d{{1,2}}){_ENDE}")
_WORT = re.compile(rf"^([A-Za-zÄÖÜäöüß]+)\.?{_ENDE}")


def _monat(wort: str) -> int:
    return MONATE.get(unicodedata.normalize("NFC", wort).casefold(), 0)


def _bauen(art: str, j: int, m: int = 0, t: int = 0) -> Zeitraum | None:
    if not JAHR_VON <= j <= JAHR_BIS:
        return None
    if art != "jahr" and not 1 <= m <= 12:
        return None
    if art == "tag" and not 1 <= t <= calendar.monthrange(j, m)[1]:
        return None
    return Zeitraum(art, j, m if art != "jahr" else 0, t if art == "tag" else 0)


def _ohne_zusammenhang(name: str) -> tuple[bool, Zeitraum | None]:
    """(passt der Form nach, Zeitraum)."""
    for form, muster in _ZAHLENMUSTER:
        m = muster.match(name)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if form == "ymd":
            return True, _bauen("tag", a, b, int(m.group(3)))
        if form == "dmy":
            return True, _bauen("tag", int(m.group(3)), b, a)
        if form == "ym":
            return True, _bauen("monat", a, b)
        return True, _bauen("monat", b, a)          # my
    m = _NAME_JAHR.match(name)
    if m and _monat(m.group(1)):
        return True, _bauen("monat", int(m.group(2)), _monat(m.group(1)))
    m = _JAHR_NAME.match(name)
    if m and _monat(m.group(2)):
        return True, _bauen("monat", int(m.group(1)), _monat(m.group(2)))
    m = _JAHR.match(name)
    if m:
        return True, _bauen("jahr", int(m.group(1)))
    return False, None


def zeitraum(name: str, eltern: Zeitraum | None = None) -> Zeitraum | None:
    """Der Zeitraum, den ein Ordnername nennt - oder None. Mit "eltern" (dem
    Zeitraum des Ordners darueber) gelten auch "01" oder "Januar" unter "2021"
    und "15" unter "2021.01"; ein Name, der dem Elternordner widerspricht
    ("2022.01" unter "2021"), gilt nicht."""
    name = unicodedata.normalize("NFC", str(name)).strip()
    passt, z = _ohne_zusammenhang(name)
    if passt:
        if z is not None and eltern is not None and not eltern.enthaelt(z):
            return None
        return z
    if eltern is None or eltern.art == "tag":
        return None
    m = _ZAHL.match(name)
    if m:
        zahl = int(m.group(1))
        if eltern.art == "jahr":
            return _bauen("monat", eltern.jahr, zahl)
        return _bauen("tag", eltern.jahr, eltern.monat, zahl)
    if eltern.art == "jahr":
        m = _WORT.match(name)
        if m and _monat(m.group(1)):
            return _bauen("monat", eltern.jahr, _monat(m.group(1)))
    return None


def zeitraum_im_pfad(teile) -> Zeitraum | None:
    """Der feinste Zeitraum, den eine Folge von Ordnernamen nennt (von oben
    nach unten, jeder im Zusammenhang der Ordner darueber)."""
    ergebnis: Zeitraum | None = None
    for teil in teile:
        z = zeitraum(teil, ergebnis)
        if z is not None:
            ergebnis = z
    return ergebnis
