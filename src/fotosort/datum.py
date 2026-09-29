"""Aufnahmedatum bestimmen (SPEC Abschnitt 3, "Datum"). Reine Logik.

Reihenfolge der Quellen, die erste gueltige gewinnt:
  1  DateTimeOriginal ("Z" = Weltzeit: umgerechnet, Hinweis "zeitzone_angenommen")
  2  Video-Felder MIT Offset: aus der Datei (QuickTime CreationDate,
     Sony CreationDateValue), dann der Sony-XML-Sidecar
  3  nur Video: CreateDate / MediaCreateDate ohne Offset, als UTC in die
     Heimat-Zeitzone umgerechnet, Hinweis "zeitzone_angenommen"
  4  nur Foto/RAW: CreateDate / DateTimeDigitized, dann XMP DateCreated und
     PNG CreationTime als Kamera-Ortszeit; danach fuer alle Typen das Datum
     aus dem .xmp-Sidecar (seit v0.8)
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
    # Nur mit bekannter Uhrzeit wird die Tagesgrenze angewendet. Das gilt fuer
    # den Dateinamen (SPEC Abschnitt 3) und aus demselben Grund fuer einen
    # Metadaten-Wert, der nur ein Datum traegt ("2026:01:01").
    uhrzeit_bekannt: bool = True

    def __post_init__(self) -> None:
        if self.hinweis == HINWEIS_OHNE_UHRZEIT:
            self.uhrzeit_bekannt = False


class ZeitzoneUngueltig(ValueError):
    """Die eingestellte Heimat-Zeitzone kennt das System nicht."""


def zeitzone_pruefen(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name))
    except Exception as fehler:
        raise ZeitzoneUngueltig(str(name)) from fehler


# ------------------------------------------------------------- Parsen ----

_ZEIT = re.compile(
    r"^\s*(\d{4})[:\-](\d{2})[:\-](\d{2})"
    r"(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?"
    r"\s*(Z|[+\-]\d{2}:?\d{2})?\s*$"
)


@dataclass
class Zeitwert:
    zeit: datetime | None
    offset: timedelta | None   # None: kein Offset angegeben
    hat_uhrzeit: bool
    ist_utc_marke: bool        # "Z": der Wert IST UTC, keine Ortszeit


def zeit_genau(text) -> Zeitwert:
    """Wie zeit_parsen, aber mit Uhrzeit-Kennung und UTC-Marke ("Z")."""
    zeit, offset = zeit_parsen(text)
    if zeit is None:
        return Zeitwert(None, None, False, False)
    m = _ZEIT.match(str(text))
    hat_uhrzeit = m is not None and m.group(4) is not None
    ist_z = m is not None and m.group(7) == "Z"
    return Zeitwert(zeit, offset, hat_uhrzeit, ist_z)


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


def _gueltig(text, jetzt=None) -> Zeitwert | None:
    w = zeit_genau(text)
    return None if ist_kaputt(w.zeit, jetzt) else w


def _mit_offset(text, jetzt=None) -> Zeitwert | None:
    """Nur Werte mit echtem Zeitzonen-Offset: Ortszeit direkt angegeben.

    "Z" zaehlt nicht - das ist UTC, keine Ortszeit.
    """
    w = zeit_genau(text)
    if w.zeit is None or w.offset is None or w.ist_utc_marke or ist_kaputt(w.zeit, jetzt):
        return None
    return w


def _utc_nach_heimat(text, zeitzone: ZoneInfo, jetzt=None) -> tuple[Zeitwert | None, bool]:
    """(Wert in der Heimat-Zeitzone, wurde umgerechnet?)."""
    w = zeit_genau(text)
    if w.zeit is None or ist_kaputt(w.zeit, jetzt):
        return None, False
    if w.offset is not None and not w.ist_utc_marke:
        return w, False  # traegt einen Offset: bereits Ortszeit
    ort = w.zeit.replace(tzinfo=timezone.utc).astimezone(zeitzone)
    return Zeitwert(ort.replace(tzinfo=None), w.offset, w.hat_uhrzeit, w.ist_utc_marke), True


# ---------------------------------------------------------- Dateiname ----

_NAME_MIT_UHRZEIT = re.compile(
    r"(?<!\d)(\d{4})(\d{2})(\d{2})[_\-\. T]?(\d{2})(\d{2})(\d{2})\d*(?!\d)"
)
# Zwischen Datum und Uhrzeit: Leerzeichen, "_", "T", "-" (Signal:
# "signal-2026-01-01-23-45-10") oder " at " / " um " (macOS-Bildschirmfotos:
# "Screenshot 2026-01-01 at 00.30.12", "Bildschirmfoto 2026-01-01 um 00.30.12").
_NAME_MIT_UHRZEIT_STRICHE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:[ _T\-]| at | um )(\d{2})[.:\-](\d{2})(?:[.:\-](\d{2}))?(?!\d)"
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


#: Quelle 4 aus der Datei selbst (nur Fotos/RAW), in dieser Reihenfolge.
FELDER_QUELLE_4 = ("CreateDate", "DateTimeDigitized", "DateCreated", "CreationTime")
#: Quelle 4 aus dem .xmp-Sidecar (alle Typen), in dieser Reihenfolge.
FELDER_XMP = ("DateTimeOriginal", "DateCreated", "CreateDate")


def _ortszeit(text, quelle: int, konf, jetzt) -> Datum | None:
    """Ein Wert, der als Ortszeit gilt - ausser er traegt die Marke "Z": Dann
    ist er Weltzeit und wird in die Heimat-Zeitzone umgerechnet (SPEC §3)."""
    w = _gueltig(text, jetzt)
    if w is None:
        return None
    if w.ist_utc_marke:
        zeitzone = zeitzone_pruefen(konf.wert("datum.heimat_zeitzone"))
        ort = w.zeit.replace(tzinfo=timezone.utc).astimezone(zeitzone).replace(tzinfo=None)
        return Datum(ort, quelle, True, HINWEIS_ZEITZONE, uhrzeit_bekannt=w.hat_uhrzeit)
    return Datum(w.zeit, quelle, True, uhrzeit_bekannt=w.hat_uhrzeit)


def bestimmen(
    felder: dict | None,
    sidecar_felder: dict | None,
    name: str,
    dateityp: str,
    mtime: float,
    konf,
    jetzt: datetime | None = None,
    xmp_felder: dict | None = None,
) -> Datum:
    """Das Aufnahmedatum einer Datei nach der Reihenfolge aus SPEC Abschnitt 3.

    xmp_felder: die Felder aus dem .xmp-Sidecar der Datei (Quelle 4, nur wenn
    die Datei selbst bis dahin nichts liefert)."""
    felder = felder or {}
    sidecar_felder = sidecar_felder or {}
    ist_video = dateityp == dateitypen.VIDEO

    # 1. DateTimeOriginal
    d = _ortszeit(felder.get("DateTimeOriginal"), 1, konf, jetzt)
    if d is not None:
        return d

    if ist_video:
        # 2. Felder MIT Offset: aus der Datei, dann der Sony-XML-Sidecar
        for feld in ("CreationDate", "CreationDateValue"):
            w = _mit_offset(felder.get(feld), jetzt)
            if w is not None:
                return Datum(w.zeit, 2, True, uhrzeit_bekannt=w.hat_uhrzeit)
        w = _mit_offset(sidecar_felder.get("NonRealTimeMetaCreationDateValue"), jetzt)
        if w is not None:
            return Datum(w.zeit, 2, True, uhrzeit_bekannt=w.hat_uhrzeit)
        # 3. UTC in die Heimat-Zeitzone: CreateDate / MediaCreateDate - und
        #    ein "Z"-Wert aus den Offset-Feldern, denn der IST UTC.
        zeitzone = zeitzone_pruefen(konf.wert("datum.heimat_zeitzone"))
        for feld in ("CreationDate", "CreationDateValue", "CreateDate", "MediaCreateDate"):
            w, umgerechnet = _utc_nach_heimat(felder.get(feld), zeitzone, jetzt)
            if w is not None:
                return Datum(w.zeit, 3 if umgerechnet else 2, True,
                             HINWEIS_ZEITZONE if umgerechnet else "",
                             uhrzeit_bekannt=w.hat_uhrzeit)
    else:
        # 4. nur Fotos: CreateDate / DateTimeDigitized, dann XMP DateCreated
        #    und PNG CreationTime - als Kamera-Ortszeit
        for feld in FELDER_QUELLE_4:
            d = _ortszeit(felder.get(feld), 4, konf, jetzt)
            if d is not None:
                return d

    # 4, alle Typen: das Datum aus dem .xmp-Sidecar (Lightroom und Co.)
    for feld in FELDER_XMP:
        d = _ortszeit((xmp_felder or {}).get(feld), 4, konf, jetzt)
        if d is not None:
            return d

    # 5. Datum im Dateinamen
    zeit, mit_uhrzeit = aus_dateiname(name, jetzt)
    if zeit is not None:
        return Datum(zeit, 5, True, "" if mit_uhrzeit else HINWEIS_OHNE_UHRZEIT,
                     uhrzeit_bekannt=mit_uhrzeit)

    # 6. Aenderungsdatum - unsicher
    if mtime and mtime > 0:
        try:
            zeit = datetime.fromtimestamp(float(mtime))
        except (OverflowError, OSError, ValueError):
            zeit = None
        if zeit is not None and not ist_kaputt(zeit, jetzt):
            return Datum(zeit, 6, False)
    return Datum(None, 0, False)


# --------------------------------------------------- Datum auffaellig -----

#: So weit darf das Aufnahmedatum vor dem Aenderungsdatum liegen, ohne dass es
#: auffaellt: ein altes Foto, Jahre spaeter bearbeitet. Mehr ist typisch fuer
#: eine zurueckgesetzte Kamerauhr (2000-01-01).
_AUFFAELLIG_VORHER = timedelta(days=3653)
_AUFFAELLIG_SPIELRAUM = timedelta(days=1)


def auffaellig(d: Datum, name: str, mtime: float, jetzt: datetime | None = None) -> str:
    """Ein Hinweis fuer den Bericht (SPEC §3 "Datum auffaellig"), sonst "".

    Nur fuer ein Datum aus den Metadaten (Quellen 1-4): Es weicht um mehr als
    einen Tag vom Datum im Dateinamen ab, liegt mehr als einen Tag NACH dem
    Aenderungsdatum (vor ihrer Aufnahme kann eine Datei nicht geaendert worden
    sein) oder mehr als zehn Jahre davor. Einsortiert wird trotzdem."""
    if d.zeit is None or not 1 <= d.quelle <= 4:
        return ""
    im_namen, _mit_uhrzeit = aus_dateiname(name, jetzt)
    if im_namen is not None and abs(d.zeit.date() - im_namen.date()) > _AUFFAELLIG_SPIELRAUM:
        return f"weicht vom Datum im Dateinamen ab ({im_namen.date().isoformat()})"
    if mtime and mtime > 0:
        try:
            geaendert = datetime.fromtimestamp(float(mtime))
        except (OverflowError, OSError, ValueError):
            geaendert = None
        if geaendert is not None and not ist_kaputt(geaendert, jetzt):
            if d.zeit > geaendert + _AUFFAELLIG_SPIELRAUM:
                return f"liegt nach dem Aenderungsdatum der Datei ({geaendert.date().isoformat()})"
            if d.zeit < geaendert - _AUFFAELLIG_VORHER:
                return f"liegt mehr als zehn Jahre vor dem Aenderungsdatum ({geaendert.date().isoformat()})"
    return ""


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
