"""Aufnahmedatum bestimmen (SPEC Abschnitt 3, "Datum"). Reine Logik.

Reihenfolge der Quellen, die erste gueltige gewinnt:
  1  DateTimeOriginal
  2  Video-Felder MIT Offset: aus der Datei (QuickTime CreationDate,
     Sony CreationDateValue), dann der Sony-XML-Sidecar
  3  nur Video: CreateDate / MediaCreateDate ohne Offset, als UTC in die
     Heimat-Zeitzone umgerechnet, Hinweis "zeitzone_angenommen"
  4  nur Foto/RAW: CreateDate / DateTimeDigitized als Kamera-Ortszeit
  5  Datum im Dateinamen (Tagesgrenze nur mit Uhrzeit)
  6  Aenderungsdatum - das einzige UNSICHERE Datum
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import dateitypen

HINWEIS_ZEITZONE = "zeitzone_angenommen"
HINWEIS_OHNE_UHRZEIT = "dateiname_ohne_uhrzeit"

_FRUEHESTES_JAHR = 1990


@dataclass
class Datum:
    zeit: datetime | None      # naiv, Ortszeit der Aufnahme
    quelle: int                # 1..6, 0 = gar nichts gefunden
    sicher: bool
    hinweis: str = ""          # "" | zeitzone_angenommen | dateiname_ohne_uhrzeit

    @property
    def uhrzeit_bekannt(self) -> bool:
        return self.hinweis != HINWEIS_OHNE_UHRZEIT


# ------------------------------------------------------------- Parsen ----

_ZEIT = re.compile(
    r"^\s*(\d{4})[:\-](\d{2})[:\-](\d{2})"
    r"(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?"
    r"\s*(Z|[+\-]\d{2}:?\d{2})?\s*$"
)


def zeit_parsen(text) -> tuple[datetime | None, timedelta | None]:
    """ExifTool-Zeitangabe -> (naive Zeit, Offset oder None).

    Versteht "2026:01:01 12:30:00", "2026-01-01T12:30:00+01:00",
    "2026:01:01 12:30:00Z" und Angaben ohne Uhrzeit. Kaputte Werte
    (0000:00:00, unmoegliche Monate) ergeben None.
    """
    if text is None:
        return None, None
    m = _ZEIT.match(str(text))
    if not m:
        return None, None
    jahr, monat, tag = int(m.group(1)), int(m.group(2)), int(m.group(3))
    stunde = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    sekunde = int(m.group(6) or 0)
    try:
        zeit = datetime(jahr, monat, tag, stunde, minute, min(sekunde, 59))
    except ValueError:
        return None, None
    offset = None
    kennung = m.group(7)
    if kennung:
        if kennung == "Z":
            offset = timedelta(0)
        else:
            vorzeichen = -1 if kennung[0] == "-" else 1
            ziffern = kennung[1:].replace(":", "")
            offset = vorzeichen * timedelta(hours=int(ziffern[:2]), minutes=int(ziffern[2:]))
    return zeit, offset


def ist_kaputt(zeit: datetime | None, jetzt: datetime | None = None) -> bool:
    """Vor 1990, in der Zukunft oder gar nicht vorhanden (SPEC Abschnitt 3)."""
    if zeit is None:
        return True
    if zeit.year < _FRUEHESTES_JAHR:
        return True
    grenze = (jetzt or datetime.now()) + timedelta(days=1)
    return zeit > grenze


def _gueltig(text, jetzt=None) -> datetime | None:
    zeit, _ = zeit_parsen(text)
    return None if ist_kaputt(zeit, jetzt) else zeit


def _mit_offset(text, jetzt=None) -> datetime | None:
    """Nur Werte, die einen Zeitzonen-Offset tragen; Ortszeit ohne Offset."""
    zeit, offset = zeit_parsen(text)
    if zeit is None or offset is None or ist_kaputt(zeit, jetzt):
        return None
    return zeit


def _utc_nach_heimat(text, zeitzone: str, jetzt=None) -> datetime | None:
    zeit, offset = zeit_parsen(text)
    if zeit is None or ist_kaputt(zeit, jetzt):
        return None
    if offset is not None:
        # Traegt der Wert doch einen Offset, ist er bereits Ortszeit.
        return zeit
    utc = zeit.replace(tzinfo=timezone.utc)
    try:
        ort = utc.astimezone(ZoneInfo(zeitzone))
    except Exception:  # unbekannte Zeitzone: lieber unverändert als falsch
        return zeit
    return ort.replace(tzinfo=None)


# ---------------------------------------------------------- Dateiname ----

_NAME_MIT_UHRZEIT = re.compile(
    r"(?<!\d)(\d{4})(\d{2})(\d{2})[_\-\. T]?(\d{2})(\d{2})(\d{2})\d*(?!\d)"
)
_NAME_MIT_UHRZEIT_STRICHE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[ _T](\d{2})[.:\-](\d{2})(?:[.:\-](\d{2}))?(?!\d)"
)
_NAME_NUR_DATUM_STRICHE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NAME_NUR_DATUM_KOMPAKT = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")


def aus_dateiname(name: str, jetzt=None) -> tuple[datetime | None, bool]:
    """(Zeit, Uhrzeit enthalten?) aus dem Dateinamen; (None, False) wenn nichts."""
    for muster in (_NAME_MIT_UHRZEIT, _NAME_MIT_UHRZEIT_STRICHE):
        m = muster.search(name)
        if m:
            try:
                zeit = datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    int(m.group(4)), int(m.group(5)), int(m.group(6) or 0),
                )
            except ValueError:
                continue
            if not ist_kaputt(zeit, jetzt):
                return zeit, True
    for muster in (_NAME_NUR_DATUM_STRICHE, _NAME_NUR_DATUM_KOMPAKT):
        m = muster.search(name)
        if m:
            try:
                zeit = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if not ist_kaputt(zeit, jetzt):
                return zeit, False
    return None, False


# --------------------------------------------------------- Bestimmen -----


def bestimmen(
    felder: dict | None,
    sidecar_felder: dict | None,
    name: str,
    dateityp: str,
    mtime: float,
    konf,
    jetzt: datetime | None = None,
) -> Datum:
    """Das Aufnahmedatum einer Datei nach der Reihenfolge aus SPEC Abschnitt 3."""
    felder = felder or {}
    sidecar_felder = sidecar_felder or {}
    ist_video = dateityp == dateitypen.VIDEO

    # 1. DateTimeOriginal
    zeit = _gueltig(felder.get("DateTimeOriginal"), jetzt)
    if zeit is not None:
        return Datum(zeit, 1, True)

    if ist_video:
        # 2. Felder MIT Offset: aus der Datei, dann der Sony-XML-Sidecar
        for feld in ("CreationDate", "CreationDateValue"):
            zeit = _mit_offset(felder.get(feld), jetzt)
            if zeit is not None:
                return Datum(zeit, 2, True)
        zeit = _mit_offset(sidecar_felder.get("NonRealTimeMetaCreationDateValue"), jetzt)
        if zeit is not None:
            return Datum(zeit, 2, True)
        # 3. CreateDate / MediaCreateDate als UTC in die Heimat-Zeitzone
        zeitzone = str(konf.wert("datum.heimat_zeitzone"))
        for feld in ("CreateDate", "MediaCreateDate"):
            roh = felder.get(feld)
            _, offset = zeit_parsen(roh)
            zeit = _utc_nach_heimat(roh, zeitzone, jetzt)
            if zeit is not None:
                return Datum(zeit, 2 if offset is not None else 3, True,
                             "" if offset is not None else HINWEIS_ZEITZONE)
    else:
        # 4. nur Fotos: CreateDate / DateTimeDigitized als Kamera-Ortszeit
        for feld in ("CreateDate", "DateTimeDigitized"):
            zeit = _gueltig(felder.get(feld), jetzt)
            if zeit is not None:
                return Datum(zeit, 4, True)

    # 5. Datum im Dateinamen
    zeit, mit_uhrzeit = aus_dateiname(name, jetzt)
    if zeit is not None:
        return Datum(zeit, 5, True, "" if mit_uhrzeit else HINWEIS_OHNE_UHRZEIT)

    # 6. Aenderungsdatum - unsicher
    if mtime and mtime > 0:
        try:
            zeit = datetime.fromtimestamp(float(mtime))
        except (OverflowError, OSError, ValueError):
            zeit = None
        if zeit is not None and not ist_kaputt(zeit, jetzt):
            return Datum(zeit, 6, False)
    return Datum(None, 0, False)


# ------------------------------------------------------- Tagesgrenze -----


def tagesgrenze_parsen(text) -> time:
    """"04:00" -> time(4, 0). Ungueltig -> 00:00."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text or ""))
    if not m:
        return time(0, 0)
    stunde, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= stunde < 24 and 0 <= minute < 60):
        return time(0, 0)
    return time(stunde, minute)


def tagesdatum(zeit: datetime, tagesgrenze, uhrzeit_bekannt: bool = True) -> date:
    """Zu welchem Tagesordner die Aufnahme gehoert.

    Liegt die Uhrzeit vor der Tagesgrenze, zaehlt die Aufnahme zum Vortag.
    Ohne bekannte Uhrzeit (Datum aus dem Dateinamen) bleibt es beim Datum,
    wie es dasteht (SPEC Abschnitt 3).
    """
    grenze = tagesgrenze if isinstance(tagesgrenze, time) else tagesgrenze_parsen(tagesgrenze)
    if not uhrzeit_bekannt or grenze == time(0, 0):
        return zeit.date()
    if zeit.time() < grenze:
        return (zeit - timedelta(days=1)).date()
    return zeit.date()
