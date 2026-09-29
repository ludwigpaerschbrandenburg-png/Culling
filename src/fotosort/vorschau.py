"""Eingebettete Vorschau aus Dateien, die die Oberflaeche nicht selbst lesen
kann - RAW, HEIC (Reiter „Sichten“, SPEC §8 seit v0.8).

Fast jede RAW-Datei traegt ein fertiges JPEG in sich (PreviewImage,
JpgFromRaw, ThumbnailImage). ExifTool holt es heraus, ohne die Datei zu
veraendern: Es bekommt nur lesende Argumente, und die Antwort kommt als
JSON (Binaerdaten als "base64:..."), nicht als Datei. Ein ExifTool-Prozess
bleibt offen (-stay_open, wie bei der Analyse) und wird nacheinander benutzt.
"""

from __future__ import annotations

import base64
import os
import threading
from pathlib import Path

from . import metadaten, pfade

#: Klein fuer die Uebersicht, gross fuer die grosse Ansicht - je in dieser
#: Reihenfolge; das erste vorhandene Feld gewinnt.
FELDER_KLEIN = ("PreviewImage", "ThumbnailImage", "JpgFromRaw")
FELDER_GROSS = ("JpgFromRaw", "PreviewImage", "ThumbnailImage")
ZEITLIMIT = 30.0


def _argumente(felder: tuple[str, ...]) -> list[str]:
    return ["-j", "-b", "-charset", "filename=utf8", "-m", "-api", "LargeFileSupport=1",
            *(f"-{f}" for f in felder), "-Orientation#"]


class Vorschauleser:
    """Ein ExifTool-Prozess fuer Vorschaubilder; sicher aus mehreren Straengen."""

    def __init__(self, programm: str) -> None:
        self.programm = programm
        self._prozess: metadaten._Prozess | None = None
        self._sperre = threading.Lock()

    def _lesen(self, pfad: Path, felder: tuple[str, ...]) -> dict:
        if self._prozess is None:
            self._prozess = metadaten._Prozess(self.programm)
        try:
            antwort = self._prozess.lesen([(str(pfad), "")], limit=ZEITLIMIT, argumente=_argumente(felder))
        except metadaten.MetadatenFehler:
            # Prozess haengt oder ist weg: beim naechsten Bild frisch starten.
            self._prozess.beenden()
            self._prozess = None
            return {}
        return next(iter(antwort.values()), {}) if antwort else {}

    def lesen(self, pfad: Path, gross: bool = False) -> tuple[bytes | None, int]:
        """(JPEG-Daten oder None, Drehung nach EXIF 1-8)."""
        if metadaten.unzulaessig_fuer_exiftool(pfad) or not os.path.isfile(pfade.lang(Path(pfad))):
            return None, 1
        felder = FELDER_GROSS if gross else FELDER_KLEIN
        with self._sperre:
            werte = self._lesen(Path(pfad), felder)
        try:
            drehung = int(str(werte.get("Orientation") or 1))
        except ValueError:
            drehung = 1
        if not 1 <= drehung <= 8:
            drehung = 1
        for feld in felder:
            wert = werte.get(feld)
            if isinstance(wert, str) and wert.startswith("base64:"):
                try:
                    daten = base64.b64decode(wert[len("base64:"):], validate=False)
                except ValueError:
                    continue
                if daten[:2] == b"\xff\xd8":
                    return daten, drehung
        return None, drehung if werte else 1

    def schliessen(self) -> None:
        with self._sperre:
            if self._prozess is not None:
                self._prozess.beenden()
                self._prozess = None
