"""BLAKE3-Pruefsummen (SPEC Abschnitt 7).

Der Quell-Hash entsteht WAEHREND des Kopierens, damit die Quelle nur einmal
gelesen wird. Bloecke von 1 MiB.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import blake3

BLOCK = 1024 * 1024


class Abgebrochen(Exception):
    """Die Kopie wurde ueber das Stop-Signal abgebrochen (Strg+C)."""


def blake3_datei(pfad: Path, stop: threading.Event | None = None) -> str:
    """Hash einer vorhandenen Datei, blockweise gelesen.

    Ist "stop" gesetzt, wird nach dem laufenden Block mit Abgebrochen
    beendet (Strg+C waehrend des Pruefens).
    """
    h = blake3.blake3()
    with open(pfad, "rb", buffering=0) as f:
        while True:
            if stop is not None and stop.is_set():
                raise Abgebrochen()
            block = f.read(BLOCK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def exklusiv_anlegen(ziel: Path) -> int:
    """Zieldatei exklusiv anlegen (O_EXCL) und den Dateigriff liefern.

    Schlaegt mit FileExistsError fehl, wenn der Name belegt ist - so wird
    nie etwas ueberschrieben (SPEC §5), auch auf exFAT und FAT32.
    """
    return os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)


def kopieren_mit_hash(
    quelle: Path, ziel: Path, stop: threading.Event | None = None, fd: int | None = None
) -> tuple[str, int]:
    """Quelle nach ziel kopieren und dabei hashen. (Hash, Bytes).

    Die Zieldatei wird EXKLUSIV angelegt (O_EXCL): Existiert sie schon,
    schlaegt das Anlegen fehl, statt etwas zu ueberschreiben (SPEC §5).
    Wahlweise kommt der schon exklusiv angelegte Dateigriff "fd" herein
    (Rueckfall ohne .part: dort legt der Hauptstrang die Datei an, bevor er
    den Anspruch festschreibt); er wird hier uebernommen und geschlossen.
    Ist "stop" gesetzt, wird nach dem laufenden Block abgebrochen; die
    halbfertige Zieldatei wird dann entfernt und Abgebrochen geworfen.
    """
    h = blake3.blake3()
    bytes_gesamt = 0
    if fd is None:
        fd = exklusiv_anlegen(ziel)
    try:
        with os.fdopen(fd, "wb", buffering=0) as aus, open(quelle, "rb", buffering=0) as ein:
            while True:
                if stop is not None and stop.is_set():
                    raise Abgebrochen()
                block = ein.read(BLOCK)
                if not block:
                    break
                aus.write(block)
                h.update(block)
                bytes_gesamt += len(block)
    except BaseException:
        # Halbfertiges nie liegen lassen - es traegt unseren Anspruch, also
        # duerfen wir es entfernen (SPEC §5).
        try:
            os.unlink(ziel)
        except OSError:
            pass
        raise
    return h.hexdigest(), bytes_gesamt


def gleich_byteweise(a: Path, b: Path) -> bool:
    """Zwei Dateien Byte fuer Byte vergleichen (Option byte_vergleich_vor_loeschen)."""
    with open(a, "rb", buffering=0) as fa, open(b, "rb", buffering=0) as fb:
        while True:
            x = fa.read(BLOCK)
            y = fb.read(BLOCK)
            if x != y:
                return False
            if not x:
                return True
