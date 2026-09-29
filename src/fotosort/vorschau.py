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

#: Je Anfrage die Felder in dieser Reihenfolge, das erste vorhandene gewinnt.
#: Fuer die Uebersicht erst die kleinen Vorschaubilder; das oft mehrere MB
#: grosse JpgFromRaw nur, wenn beide fehlen (ExifTool liefert jedes erfragte
#: Feld, das es gibt - also nicht alle auf einmal fragen).
STUFEN_KLEIN = (("PreviewImage", "ThumbnailImage"), ("JpgFromRaw",))
STUFEN_GROSS = (("JpgFromRaw", "PreviewImage", "ThumbnailImage"),)
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
        self._zu = False

    def _lesen(self, pfad: Path, felder: tuple[str, ...]) -> dict:
        if self._zu:
            return {}   # geschlossen: nie wieder ein ExifTool starten
        if self._prozess is None:
            try:
                self._prozess = metadaten._Prozess(self.programm)
            except metadaten.MetadatenFehler:
                return {}
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
        if self._zu or metadaten.unzulaessig_fuer_exiftool(pfad) or not os.path.isfile(pfade.lang(Path(pfad))):
            return None, 1
        drehung = 1
        for felder in STUFEN_GROSS if gross else STUFEN_KLEIN:
            with self._sperre:
                werte = self._lesen(Path(pfad), felder)
            try:
                drehung = int(str(werte.get("Orientation") or drehung))
            except ValueError:
                pass
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
        return None, 1

    def schliessen(self) -> None:
        """Beenden, ohne auf ein langsames Bild zu warten: Ist der Prozess
        gerade beschaeftigt, wird er hart beendet (die laufende Anfrage endet
        dann ohne Vorschau). Danach startet dieser Leser nie wieder ExifTool."""
        self._zu = True
        if self._sperre.acquire(timeout=0.5):
            try:
                if self._prozess is not None:
                    self._prozess.beenden()
                    self._prozess = None
            finally:
                self._sperre.release()
            return
        prozess = self._prozess
        if prozess is not None:
            prozess._abwuergen()
