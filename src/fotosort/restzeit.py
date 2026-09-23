"""Geschaetzte Restzeit eines Schritts - fuer das Fenster und die Konsole.

Aus dem Test von v0.5 mit echten Dateien: Die alte Schaetzung rechnete vom
Durchschnitt seit dem Start hoch. Der Anfang ist aber schnell, weil Windows
die ersten Dateien aus dem Zwischenspeicher liefert - die Anzeige sprang von
3 auf 11 Minuten. Deshalb jetzt, in allen Phasen gleich:

- In den ersten 60 Sekunden und solange weniger als 3 % geschafft sind,
  gibt es keine Zahl, nur "wird berechnet".
- Danach kommt das Tempo aus einem gleitenden Durchschnitt der letzten
  60 Sekunden: erledigte Menge in diesem Fenster geteilt durch seine Dauer.
- Neu berechnet wird hoechstens alle 5 Sekunden; dazwischen bleibt die
  angezeigte Zahl stehen.
- Abgerundet auf ganze Minuten, unter 2 Minuten auf 10-Sekunden-Schritte.
- Die Uhr laeuft ab der ersten Meldung mit bekannter Gesamtmenge, also ab
  dem Moment, in dem die Phase wirklich arbeitet; Vorbereitung zaehlt nicht.
- Pausen zaehlen nicht mit: Die Uhr steht, solange der Schritt angehalten ist.
- Ging in der letzten Minute gar nichts voran (etwa eine sehr grosse Datei),
  bleibt die letzte Schaetzung stehen.

"Menge" ist die Datenmenge, wenn sie bekannt ist (Kopieren, Pruefen,
Aufraeumen), sonst die Zahl der Dateien (Analyse). Ohne bekannte
Gesamtmenge (Scan) gibt es keine Restzeit.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

ANLAUF_SEKUNDEN = 60.0      # so lange nur "wird berechnet"
ANLAUF_ANTEIL = 0.03        # ... und solange weniger als 3 % geschafft sind
FENSTER_SEKUNDEN = 60.0     # gleitender Durchschnitt ueber diese Zeit
TAKT_SEKUNDEN = 5.0         # hoechstens so oft eine neue Zahl
PROBE_ABSTAND = 1.0         # eine Messprobe je Sekunde genuegt
FEIN_UNTER = 120.0          # darunter auf 10-Sekunden-Schritte abrunden
FEIN_SCHRITT = 10
GROB_SCHRITT = 60

# Zustand der Schaetzung (so steht er auch in der Statusdatei).
UNBEKANNT = ""                    # Gesamtmenge unbekannt: keine Restzeit
WIRD_BERECHNET = "wird_berechnet"
GESCHAETZT = "geschaetzt"


def abrunden(sekunden: float) -> int:
    """Auf ganze Minuten abrunden, unter 2 Minuten auf 10-Sekunden-Schritte."""
    s = max(0.0, float(sekunden))
    schritt = FEIN_SCHRITT if s < FEIN_UNTER else GROB_SCHRITT
    return int(s // schritt) * schritt


class Restzeit:
    """Nimmt den Fortschritt eines Schritts auf und liefert die Restzeit.

    uhr: Zeitquelle in Sekunden (monoton); fuer Tests austauschbar.
    """

    def __init__(self, uhr: Callable[[], float] | None = None) -> None:
        self._uhr = uhr or time.monotonic
        self._beginn: float | None = None       # erste Meldung mit bekannter Gesamtmenge
        self._pausen = 0.0
        self._pausiert_seit: float | None = None
        self._proben: deque[tuple[float, float]] = deque()   # (aktive Zeit, erledigt)
        self._wert: int | None = None
        self._wert_zeit = 0.0

    # -- Pausen ------------------------------------------------------------

    def pause(self) -> None:
        if self._beginn is not None and self._pausiert_seit is None:
            self._pausiert_seit = self._uhr()

    def weiter(self) -> None:
        if self._pausiert_seit is not None:
            self._pausen += self._uhr() - self._pausiert_seit
            self._pausiert_seit = None

    def _aktiv(self) -> float:
        """Laufzeit seit der ersten Meldung, ohne Pausen."""
        jetzt = self._uhr()
        if self._beginn is None:
            self._beginn = jetzt
        pause = self._pausen
        if self._pausiert_seit is not None:
            pause += jetzt - self._pausiert_seit
        return jetzt - self._beginn - pause

    # -- Schaetzung ---------------------------------------------------------

    def melden(self, erledigt: float, gesamt: float) -> tuple[int | None, str]:
        """Neuen Stand aufnehmen. Liefert (Sekunden, abgerundet, oder None; Zustand)."""
        if gesamt <= 0:
            return None, UNBEKANNT
        t = self._aktiv()
        erledigt = max(0.0, min(float(erledigt), float(gesamt)))
        if not self._proben or t - self._proben[-1][0] >= PROBE_ABSTAND:
            self._proben.append((t, erledigt))
        # Fenster: Die aelteste behaltene Probe liegt hoechstens knapp vor
        # "jetzt minus 60 Sekunden" - so umfasst das Fenster eine volle Minute.
        while len(self._proben) >= 2 and self._proben[1][0] <= t - FENSTER_SEKUNDEN:
            self._proben.popleft()

        if t < ANLAUF_SEKUNDEN or erledigt < ANLAUF_ANTEIL * gesamt:
            self._wert = None
            return None, WIRD_BERECHNET
        if self._wert is not None and t - self._wert_zeit < TAKT_SEKUNDEN:
            return self._wert, GESCHAETZT
        t0, e0 = self._proben[0]
        if t - t0 <= 0 or erledigt <= e0:
            # In der ganzen letzten Minute nichts geschafft: alte Zahl behalten.
            if self._wert is not None:
                return self._wert, GESCHAETZT
            return None, WIRD_BERECHNET
        tempo = (erledigt - e0) / (t - t0)
        self._wert = abrunden((gesamt - erledigt) / tempo)
        self._wert_zeit = t
        return self._wert, GESCHAETZT
