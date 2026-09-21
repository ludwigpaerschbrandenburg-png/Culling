"""Laufende Anzeige fuer Kopieren und Pruefen (SPEC Abschnitt 7 und 8).

Dateien und Datenmenge (erledigt/gesamt), MB/s und geschaetzte Restzeit;
im Terminal als Balken mit hoechstens zwei Aktualisierungen je Sekunde,
sonst hoechstens alle fuenf Sekunden eine Zeile.
"""

from __future__ import annotations

import time
from typing import Callable

from . import meldungen

STILLE_SEKUNDEN = 5.0
BALKEN_SEKUNDEN = 0.5


class Fortschritt:
    def __init__(self, konsole, gesamt: int, gesamt_bytes: int,
                 text: Callable[[int, int, int, int, float], str]) -> None:
        """text(dateien, gesamt, bytes, gesamt_bytes, bytes_je_sekunde) -> Zeile."""
        self.konsole = konsole
        self.gesamt = gesamt
        self.gesamt_bytes = gesamt_bytes
        self.text_fn = text
        self.dateien = 0
        self.bytes = 0
        self.begonnen = time.monotonic()
        self._zuletzt = self.begonnen
        self.balken = None
        self.aufgabe = None
        if konsole is not None and getattr(konsole, "is_terminal", False):
            from rich.progress import BarColumn, Progress, TextColumn

            self.balken = Progress(
                TextColumn("{task.description}"), BarColumn(bar_width=None),
                TextColumn("{task.fields[rest]}"),
                console=konsole, refresh_per_second=2, transient=True,
            )
            self.aufgabe = self.balken.add_task(self._text(), total=gesamt_bytes or None, rest="")
            self.balken.start()

    def _text(self) -> str:
        verstrichen = max(1e-9, time.monotonic() - self.begonnen)
        return self.text_fn(self.dateien, self.gesamt, self.bytes, self.gesamt_bytes, self.bytes / verstrichen)

    def _rest(self) -> str:
        verstrichen = time.monotonic() - self.begonnen
        if self.bytes <= 0 or verstrichen <= 0:
            return ""
        rest = (self.gesamt_bytes - self.bytes) * verstrichen / self.bytes
        return meldungen.restzeit(rest)

    def weiter(self, dateien: int, bytes_: int) -> None:
        self.dateien += dateien
        self.bytes += bytes_
        jetzt = time.monotonic()
        if jetzt - self._zuletzt < (BALKEN_SEKUNDEN if self.balken else STILLE_SEKUNDEN):
            return
        self._zuletzt = jetzt
        if self.balken is not None:
            self.balken.update(self.aufgabe, completed=self.bytes, description=self._text(), rest=self._rest())
        elif self.konsole is not None:
            self.konsole.print(self._text())

    def stop(self) -> None:
        if self.balken is not None:
            self.balken.stop()
