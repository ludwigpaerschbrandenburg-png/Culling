"""Beobachtung und Steuerung eines laufenden Schritts von aussen (Phase 7).

Die Oberflaeche startet jeden Schritt (scan, analyse, kopieren, pruefen,
aufraeumen) als eigenen Prozess (SPEC Abschnitt 8: Fenster schliessen darf
den Lauf nicht beeinflussen). Der Arbeitsprozess schreibt hoechstens
zweimal je Sekunde seinen Stand in eine kleine JSON-Datei; die Oberflaeche
liest sie. Umgekehrt schreibt die Oberflaeche Wuensche (Pause, Weiter,
Abbruch) in eine zweite JSON-Datei; der Arbeitsprozess sieht bei jeder
Fortschrittsmeldung nach. Ein Abbruch laeuft ueber denselben Weg wie
Strg+C (KeyboardInterrupt), also so sauber wie am Terminal.

Kein Datenbankzugriff in diesem Modul.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ZUSTAND_LAEUFT = "laeuft"
ZUSTAND_PAUSE = "pause"
ZUSTAND_FERTIG = "fertig"
ZUSTAND_ABGEBROCHEN = "abgebrochen"
ZUSTAND_FEHLER = "fehler"

SCHREIB_ABSTAND = 0.5      # Sekunden zwischen zwei Statusdateien
HERZSCHLAG = 2.0           # spaetestens so oft wird der Stand geschrieben, auch ohne Fortschritt


def json_schreiben(pfad: Path, daten: dict) -> None:
    """Datei komplett neu schreiben, nie halb: erst .neu, dann umbenennen."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = pfad.with_name(pfad.name + ".neu")
    vorlaeufig.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(vorlaeufig, pfad)


def json_lesen(pfad: Path) -> dict | None:
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Steuerung:
    """Stand schreiben, Wuensche lesen. Lebt nur im Arbeitsprozess."""

    def __init__(self, status_datei: Path, steuer_datei: Path, schritt: str) -> None:
        self.status_datei = Path(status_datei)
        self.steuer_datei = Path(steuer_datei)
        self.schritt = schritt
        self.begonnen = time.time()
        self.zustand = ZUSTAND_LAEUFT
        self.dateien = 0
        self.gesamt = 0
        self.bytes = 0
        self.gesamt_bytes = 0
        self.lauf: int | None = None
        self.hinweis = ""
        self._zuletzt = 0.0
        self._sperre = threading.Lock()
        self._herz: threading.Thread | None = None
        self._ende = threading.Event()

    # -- Schreiben -------------------------------------------------------

    def _daten(self, rc: int | None = None) -> dict:
        jetzt = time.time()
        verstrichen = max(1e-9, jetzt - self.begonnen)
        rate = self.bytes / verstrichen
        rest = None
        if self.gesamt_bytes and self.bytes and self.bytes < self.gesamt_bytes:
            rest = (self.gesamt_bytes - self.bytes) * verstrichen / self.bytes
        elif self.gesamt and self.dateien and self.dateien < self.gesamt and not self.gesamt_bytes:
            rest = (self.gesamt - self.dateien) * verstrichen / self.dateien
        return {
            "schritt": self.schritt,
            "zustand": self.zustand,
            "pid": os.getpid(),
            "beginn": self.begonnen,
            "aktualisiert": jetzt,
            "dateien": self.dateien,
            "gesamt": self.gesamt,
            "bytes": self.bytes,
            "gesamt_bytes": self.gesamt_bytes,
            "bytes_pro_s": rate,
            "restzeit_s": rest,
            "sekunden": verstrichen,
            "lauf": self.lauf,
            "rc": rc,
            "hinweis": self.hinweis,
        }

    def schreiben(self, rc: int | None = None) -> None:
        with self._sperre:
            self._zuletzt = time.monotonic()
            try:
                json_schreiben(self.status_datei, self._daten(rc))
            except OSError:
                pass   # die Anzeige ist Komfort, die Arbeit geht weiter

    def herzschlag_starten(self) -> None:
        """Auch ohne Fortschritt regelmaessig schreiben, damit die
        Oberflaeche einen abgestuerzten Prozess von einem stillen unterscheidet."""
        def schlagen() -> None:
            while not self._ende.wait(HERZSCHLAG):
                if time.monotonic() - self._zuletzt >= HERZSCHLAG:
                    self.schreiben()
        self._herz = threading.Thread(target=schlagen, name="herzschlag", daemon=True)
        self._herz.start()

    def beenden(self, zustand: str, rc: int, hinweis: str = "") -> None:
        self._ende.set()
        self.zustand = zustand
        if hinweis:
            self.hinweis = hinweis
        self.schreiben(rc)

    # -- Fortschritt und Wuensche ------------------------------------------

    def melden(self, dateien: int, gesamt: int, bytes_: int, gesamt_bytes: int) -> None:
        """Vom Hauptstrang der Arbeit gerufen. Schreibt gedrosselt; prueft
        die Wuensche der Oberflaeche: Pause haelt hier an, Abbruch wirft
        KeyboardInterrupt (der saubere Weg jeder Phase)."""
        self.dateien, self.gesamt, self.bytes, self.gesamt_bytes = dateien, gesamt, bytes_, gesamt_bytes
        jetzt = time.monotonic()
        if jetzt - self._zuletzt >= SCHREIB_ABSTAND:
            self._wuensche_pruefen()
            self.schreiben()

    def _wuensche_pruefen(self) -> None:
        wunsch = json_lesen(self.steuer_datei) or {}
        if wunsch.get("abbrechen"):
            raise KeyboardInterrupt
        if wunsch.get("pause"):
            self.zustand = ZUSTAND_PAUSE
            self.schreiben()
            while True:
                time.sleep(0.5)
                wunsch = json_lesen(self.steuer_datei) or {}
                if wunsch.get("abbrechen"):
                    self.zustand = ZUSTAND_LAEUFT
                    raise KeyboardInterrupt
                if not wunsch.get("pause"):
                    break
            self.zustand = ZUSTAND_LAEUFT
            self.schreiben()


# Die eine aktive Steuerung dieses Prozesses (nur im Arbeitsprozess gesetzt).
AKTIV: Steuerung | None = None


def melden(dateien: int, gesamt: int, bytes_: int, gesamt_bytes: int) -> None:
    """Fortschrittsmeldung aus den Phasen. Ohne Oberflaeche ein Nichts."""
    if AKTIV is not None:
        AKTIV.melden(dateien, gesamt, bytes_, gesamt_bytes)


def lauf_setzen(nummer: int) -> None:
    if AKTIV is not None:
        AKTIV.lauf = nummer
        AKTIV.schreiben()


def wunsch_schreiben(steuer_datei: Path, *, pause: bool = False, abbrechen: bool = False) -> None:
    """Von der Oberflaeche aus: Pause, Weiter (pause=False) oder Abbruch."""
    json_schreiben(steuer_datei, {"pause": bool(pause), "abbrechen": bool(abbrechen), "zeit": time.time()})
