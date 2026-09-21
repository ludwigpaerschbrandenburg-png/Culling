"""Metadaten ueber dauerhaft laufende ExifTool-Prozesse (SPEC Abschnitt 7).

ExifTool wird nicht je Datei gestartet, sondern laeuft mit -stay_open
weiter und bekommt Stapel von Dateien. Je Strang ein Prozess; die Anzahl
ist einstellbar (leistung.metadaten_prozesse, 0 = Anzahl Kerne).

Fotos und RAW werden mit -fast2 gelesen. Videos ohne: Sony legt seine
XML-Metadaten (CreationDateValue mit Zeitzonen-Offset) am Ende der Datei
ab, und -fast2 hoert vorher auf zu lesen - das ist im Container geprueft
(SPEC Abschnitt 3, Quelle 2).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from . import dateitypen

# Nur die Felder, die die Datumsermittlung (SPEC Abschnitt 3) und der
# Kamera-Ordner brauchen. Gruppenpraefixe weggelassen: ExifTool liefert
# den Namen ohne Gruppe, egal aus welchem Block der Wert stammt.
FELDER_FOTO: tuple[str, ...] = (
    "Error",                 # Lesefehler von ExifTool - sonst unsichtbar
    "DateTimeOriginal",
    "CreateDate",
    "DateTimeDigitized",
    "Make",
    "Model",
)
FELDER_VIDEO: tuple[str, ...] = (
    "Error",
    "DateTimeOriginal",
    "CreateDate",
    "MediaCreateDate",
    "CreationDate",          # QuickTime, mit Offset (Apple und viele Kameras)
    "CreationDateValue",     # eingebettetes Sony-XML, mit Offset
    "DeviceModelName",       # eingebettetes Sony-XML
    "Make",
    "Model",
)
FELDER_SIDECAR_XML: tuple[str, ...] = (
    "Error",
    "NonRealTimeMetaCreationDateValue",  # Sony-XML-Sidecar C0001M01.XML
    "NonRealTimeMetaDeviceModelName",
)

STAPELGROESSE = 200


class MetadatenFehler(Exception):
    """ExifTool konnte eine Datei nicht lesen."""


def schluessel(pfad) -> str:
    """Pfad in der Form, unter der die ExifTool-Antwort zugeordnet wird.

    ExifTool schreibt SourceFile unter Windows mit Schraegstrichen zurueck,
    egal wie der Pfad uebergeben wurde. Damit die Antwort zur Datenbank
    passt, werden beide Seiten auf Schraegstriche gebracht.
    """
    return str(pfad).replace("\\", "/")


def unzulaessig_fuer_exiftool(pfad) -> bool:
    """Ein Zeilenumbruch im Namen wuerde in der Argumentdatei (-@) zu
    weiteren Argumenten - im schlimmsten Fall zu Schreibbefehlen. Solche
    Pfade gehen nie an ExifTool (SPEC Abschnitt 4 Phase 2: nichts anfassen).
    """
    text = str(pfad)
    return "\n" in text or "\r" in text


def prozesse_bestimmen(konf) -> int:
    """0 heisst automatisch: Anzahl Kerne (SPEC Abschnitt 9)."""
    gewuenscht = int(konf.wert("leistung.metadaten_prozesse") or 0)
    if gewuenscht > 0:
        return gewuenscht
    return max(1, os.cpu_count() or 1)


def _argumente(dateityp: str) -> list[str]:
    if dateityp == dateitypen.VIDEO:
        felder, schnell = FELDER_VIDEO, False
    elif dateityp == dateitypen.SIDECAR:
        felder, schnell = FELDER_SIDECAR_XML, False
    else:
        felder, schnell = FELDER_FOTO, True
    args = ["-j", "-charset", "filename=utf8", "-charset", "utf8", "-m"]
    if schnell:
        args.append("-fast2")
    args.extend(f"-{feld}" for feld in felder)
    return args


class _Prozess:
    """Ein einzelner ExifTool-Prozess mit -stay_open."""

    def __init__(self, programm: str) -> None:
        self.programm = programm
        self.zaehler = 0
        self.prozess = subprocess.Popen(
            [programm, "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def lesen(self, pfade_typ: list[tuple[str, str]]) -> dict[str, dict]:
        """Einen Stapel gleichen Dateityps lesen. Pfad -> Felder."""
        if not pfade_typ:
            return {}
        typ = pfade_typ[0][1]
        pfade_typ = [(p, t) for p, t in pfade_typ if not unzulaessig_fuer_exiftool(p)]
        if not pfade_typ:
            return {}
        self.zaehler += 1
        nummer = self.zaehler
        zeilen = _argumente(typ) + [p for p, _ in pfade_typ]
        eingabe = "\n".join(zeilen) + f"\n-execute{nummer}\n"
        assert self.prozess.stdin is not None and self.prozess.stdout is not None
        self.prozess.stdin.write(eingabe.encode("utf-8", "surrogateescape"))
        self.prozess.stdin.flush()

        ende = f"{{ready{nummer}}}".encode()
        puffer = bytearray()
        while True:
            zeile = self.prozess.stdout.readline()
            if not zeile:
                raise MetadatenFehler("ExifTool hat sich unerwartet beendet")
            if zeile.rstrip(b"\r\n") == ende:
                break
            puffer.extend(zeile)

        text = puffer.decode("utf-8", "surrogateescape").strip()
        ergebnis: dict[str, dict] = {}
        if text:
            try:
                for eintrag in json.loads(text):
                    quelle = eintrag.pop("SourceFile", None)
                    if quelle is not None:
                        ergebnis[schluessel(quelle)] = eintrag
            except json.JSONDecodeError as fehler:
                raise MetadatenFehler(f"ExifTool-Antwort nicht lesbar: {fehler}") from fehler
        return ergebnis

    def beenden(self) -> None:
        try:
            if self.prozess.stdin is not None:
                self.prozess.stdin.write(b"-stay_open\nFalse\n")
                self.prozess.stdin.flush()
                self.prozess.stdin.close()
            self.prozess.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.prozess.kill()


class ExifToolPool:
    """N ExifTool-Prozesse, einer je Strang. Stapel werden parallel gelesen."""

    def __init__(self, programm: str, prozesse: int) -> None:
        self.programm = programm
        self.prozesse = max(1, int(prozesse))
        self._lokal = threading.local()
        self._alle: list[_Prozess] = []
        self._schloss = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None

    def __enter__(self) -> "ExifToolPool":
        self._executor = ThreadPoolExecutor(max_workers=self.prozesse, thread_name_prefix="exiftool")
        return self

    def __exit__(self, *_: object) -> None:
        self.schliessen()

    def _prozess(self) -> _Prozess:
        p = getattr(self._lokal, "prozess", None)
        if p is None:
            p = _Prozess(self.programm)
            self._lokal.prozess = p
            with self._schloss:
                self._alle.append(p)
        return p

    def _lesen(self, pfade_typ: list[tuple[str, str]]) -> dict[str, dict]:
        return self._prozess().lesen(pfade_typ)

    def einreichen(self, pfade_typ: list[tuple[str, str]]) -> Future:
        """Einen Stapel (alle vom selben Dateityp) im Hintergrund lesen."""
        assert self._executor is not None, "Pool nicht gestartet (with-Block)"
        return self._executor.submit(self._lesen, list(pfade_typ))

    def lesen(self, pfade_typ: list[tuple[str, str]]) -> dict[str, dict]:
        """Bequem und synchron, fuer Tests und kleine Mengen."""
        return self.einreichen(pfade_typ).result()

    def schliessen(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        with self._schloss:
            for p in self._alle:
                p.beenden()
            self._alle.clear()


def stapel_bilden(
    eintraege: list[tuple[str, str]], groesse: int = STAPELGROESSE
) -> list[list[tuple[str, str]]]:
    """Eintraege (Pfad, Dateityp) in Stapel gleichen Typs teilen.

    Die Reihenfolge nach Quellordner bleibt erhalten, damit die Platte
    moeglichst sequentiell liest (SPEC Abschnitt 7).
    """
    def art(typ: str) -> str:
        if typ == dateitypen.VIDEO:
            return "video"
        return "sidecar" if typ == dateitypen.SIDECAR else "foto"

    # Erst nach Art sammeln (stabil, also innerhalb der Art weiter nach
    # Ordner), sonst ergaebe ein Handy-Ordner mit IMG_0001.JPG/IMG_0002.MOV
    # im Wechsel lauter Stapel mit einer einzigen Datei.
    stapel: list[list[tuple[str, str]]] = []
    aktuell: list[tuple[str, str]] = []
    aktueller_typ = None
    for pfad, typ in sorted(eintraege, key=lambda e: art(e[1])):
        kennung = art(typ)
        if aktuell and (kennung != aktueller_typ or len(aktuell) >= groesse):
            stapel.append(aktuell)
            aktuell = []
        aktueller_typ = kennung
        aktuell.append((pfad, typ))
    if aktuell:
        stapel.append(aktuell)
    return stapel


def pfad_fuer_exiftool(pfad: Path) -> str:
    return str(pfad)
