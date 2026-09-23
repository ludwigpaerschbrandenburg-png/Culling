"""Metadaten ueber dauerhaft laufende ExifTool-Prozesse (SPEC Abschnitt 7).

ExifTool wird nicht je Datei gestartet, sondern laeuft mit -stay_open
weiter und bekommt Stapel von Dateien. Je Strang ein Prozess; die Anzahl
ist einstellbar (leistung.metadaten_prozesse), sonst richtet sie sich nach
dem Profil: Festplatte und Netzlaufwerk 4, SSD Anzahl Kerne, hoechstens 16.
Die Prozesse starten gestaffelt (STARTABSTAND), nicht alle auf einmal.

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
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from . import dateitypen, meldungen, prozesse

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

# ExifTool-Prozesse je Profil, wenn leistung.metadaten_prozesse = 0 ist.
# Eine Festplatte liest mit 32 Lesern auf einmal nur noch mit springendem
# Kopf (im ersten echten Testlauf: 8 Dateien/s); 0 heisst Anzahl Kerne.
PROZESSE_JE_PROFIL: dict[str, int] = {"hdd": 4, "netzwerk": 4, "ssd": 0}
PROZESSE_HOECHSTENS = 16
# Abstand zwischen zwei Prozessstarts: 16 Perl-Starts im selben Augenblick
# bremsen sich gegenseitig und lassen Virenscanner anschlagen.
STARTABSTAND = 0.2

# Zeitlimit je Stapel: Grundzeit plus je Datei. Bleibt ExifTool an einer
# Datei haengen, wird der Prozess beendet und neu gestartet; der Stapel wird
# danach Datei fuer Datei gelesen, damit nur die eine Datei als Fehler endet.
ZEITLIMIT_GRUND = 60.0
ZEITLIMIT_JE_DATEI = 1.0


def zeitlimit(anzahl: int) -> float:
    return ZEITLIMIT_GRUND + ZEITLIMIT_JE_DATEI * max(1, anzahl)


class MetadatenFehler(Exception):
    """ExifTool konnte eine Datei nicht lesen."""


class ZeitlimitUeberschritten(MetadatenFehler):
    """ExifTool hat innerhalb des Zeitlimits nicht geantwortet und wurde beendet."""


def schluessel(pfad) -> str:
    """Pfad in der Form, unter der die ExifTool-Antwort zugeordnet wird.

    ExifTool schreibt SourceFile unter Windows mit Schraegstrichen zurueck,
    egal wie der Pfad uebergeben wurde. Damit die Antwort zur Datenbank
    passt, werden beide Seiten auf Schraegstriche gebracht.
    """
    return str(pfad).replace("\\", "/")


def exiftool_befehl(programm: str) -> list[str]:
    """Womit ExifTool wirklich gestartet wird.

    Die Windows-Fassung von exiftool.org besteht aus einem kleinen Starter
    (exiftool(-k).exe bzw. exiftool.exe) und dem Ordner exiftool_files mit
    perl.exe, perl532.dll und dem Skript exiftool.pl. Der Starter laedt nur
    perl532.dll und ruft darin Perl mit exiftool.pl auf - genau das tut auch
    perl.exe, ohne eigene Umgebungsvariablen. Deshalb wird perl.exe direkt
    gestartet, wo es geht: ein Programm weniger, das ein Virenscanner bei
    jedem Start pruefen muss. Lange Pfade behandelt ExifTool selbst
    (WindowsLongPath, ueber das mitgelieferte Win32::API).

    programm: exiftool.pl (daneben perl.exe), ein Starter mit exiftool_files
    daneben, oder jedes andere ExifTool (dann unveraendert).
    """
    p = Path(programm)
    if p.suffix.lower() == ".pl":
        perl = p.with_name("perl.exe")
        if perl.is_file():
            return [str(perl), str(p)]
        return ["perl", str(p)]
    if p.suffix.lower() == ".exe":
        dateien = p.parent / "exiftool_files"
        perl, skript = dateien / "perl.exe", dateien / "exiftool.pl"
        if perl.is_file() and skript.is_file():
            return [str(perl), str(skript)]
    return [str(programm)]


def unzulaessig_fuer_exiftool(pfad) -> bool:
    """Ein Zeilenumbruch im Namen wuerde in der Argumentdatei (-@) zu
    weiteren Argumenten - im schlimmsten Fall zu Schreibbefehlen. Solche
    Pfade gehen nie an ExifTool (SPEC Abschnitt 4 Phase 2: nichts anfassen).
    """
    text = str(pfad)
    return "\n" in text or "\r" in text


def prozesse_bestimmen(konf, profil: str | None = None) -> int:
    """Konfigurationswert, sonst nach Profil (SPEC Abschnitte 7 und 9).

    Das Profil kommt von der Befehlszeile oder aus der Oberflaeche; fehlt
    es, gilt leistung.profil aus der Konfiguration.
    """
    gewuenscht = int(konf.wert("leistung.metadaten_prozesse") or 0)
    if gewuenscht > 0:
        return gewuenscht
    profil = str(profil or konf.wert("leistung.profil") or "hdd").strip().lower()
    fest = PROZESSE_JE_PROFIL.get(profil, PROZESSE_JE_PROFIL["hdd"])
    if fest > 0:
        return fest
    return max(1, min(os.cpu_count() or 1, PROZESSE_HOECHSTENS))


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
        self.abgewuergt = False
        self.prozess = subprocess.Popen(
            exiftool_befehl(programm) + ["-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            **prozesse.unsichtbar(),
        )

    def _abwuergen(self) -> None:
        """Nach Ablauf des Zeitlimits: Prozess samt Kindern beenden, damit
        readline() sicher zu Ende kommt (prozesse.baum_beenden)."""
        self.abgewuergt = True
        prozesse.baum_beenden(self.prozess)

    def lesen(self, pfade_typ: list[tuple[str, str]], limit: float | None = None) -> dict[str, dict]:
        """Einen Stapel gleichen Dateityps lesen. Pfad -> Felder.

        Mit limit (Sekunden) wird der Prozess beendet, wenn die Antwort nicht
        rechtzeitig kommt (ZeitlimitUeberschritten); er ist danach unbrauchbar.
        """
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
        waechter = threading.Timer(limit, self._abwuergen) if limit else None
        if waechter is not None:
            waechter.daemon = True
            waechter.start()
        try:
            try:
                self.prozess.stdin.write(eingabe.encode("utf-8", "surrogateescape"))
                self.prozess.stdin.flush()
            except OSError as fehler:
                raise MetadatenFehler(f"ExifTool nimmt keine Eingabe an: {fehler}") from fehler

            ende = f"{{ready{nummer}}}".encode()
            puffer = bytearray()
            while True:
                zeile = self.prozess.stdout.readline()
                if not zeile:
                    if self.abgewuergt:
                        raise ZeitlimitUeberschritten(meldungen.EXIFTOOL_ZEITLIMIT)
                    raise MetadatenFehler("ExifTool hat sich unerwartet beendet")
                if zeile.rstrip(b"\r\n") == ende:
                    break
                puffer.extend(zeile)
        finally:
            if waechter is not None:
                waechter.cancel()

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
        self._naechster_start = 0.0
        self.zeitlimits = 0          # wie oft ein Prozess wegen Zeitlimit ersetzt wurde

    def __enter__(self) -> "ExifToolPool":
        self._executor = ThreadPoolExecutor(max_workers=self.prozesse, thread_name_prefix="exiftool")
        return self

    def __exit__(self, *_: object) -> None:
        self.schliessen()

    def _startplatz_abwarten(self) -> None:
        """Prozesse gestaffelt starten: der naechste fruehestens STARTABSTAND
        nach dem vorigen, der erste sofort."""
        with self._schloss:
            jetzt = time.monotonic()
            geplant = max(jetzt, self._naechster_start)
            self._naechster_start = geplant + STARTABSTAND
        if geplant > jetzt:
            time.sleep(geplant - jetzt)

    def _prozess(self) -> _Prozess:
        p = getattr(self._lokal, "prozess", None)
        if p is None:
            self._startplatz_abwarten()
            p = _Prozess(self.programm)
            self._lokal.prozess = p
            with self._schloss:
                self._alle.append(p)
        return p

    def _ersetzen(self, p: _Prozess) -> None:
        """Einen abgewuergten Prozess vergessen; der naechste Aufruf startet neu."""
        p.beenden()
        with self._schloss:
            if p in self._alle:
                self._alle.remove(p)
            self.zeitlimits += 1
        if getattr(self._lokal, "prozess", None) is p:
            self._lokal.prozess = None

    def _lesen(self, pfade_typ: list[tuple[str, str]]) -> dict[str, dict]:
        p = self._prozess()
        try:
            return p.lesen(pfade_typ, zeitlimit(len(pfade_typ)))
        except ZeitlimitUeberschritten:
            self._ersetzen(p)
        if len(pfade_typ) <= 1:
            # Diese eine Datei ist es: Sie bekommt einen Fehler, alles andere geht weiter.
            return {schluessel(pf): {"Error": meldungen.EXIFTOOL_ZEITLIMIT} for pf, _t in pfade_typ}
        # Den Stapel Datei fuer Datei nachlesen: nur die haengende Datei kostet
        # noch ein Zeitlimit, die uebrigen sind in Sekundenbruchteilen gelesen.
        ergebnis: dict[str, dict] = {}
        for eintrag in pfade_typ:
            ergebnis.update(self._lesen([eintrag]))
        return ergebnis

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
