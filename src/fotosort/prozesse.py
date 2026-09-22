"""Hilfsprozesse (ExifTool, Arbeitsprozess) ohne sichtbares Konsolenfenster.

Unter Windows bekommt ein Konsolenprogramm, das aus einem Programm ohne
eigene Konsole gestartet wird (dem Fenster oder dem losgeloesten
Arbeitsprozess), von Windows ein neues Konsolenfenster - je ExifTool-
Prozess eines. Deshalb bekommt jeder Hilfsprozess die Flagge
CREATE_NO_WINDOW und ein STARTUPINFO mit SW_HIDE. Auf anderen Systemen
gibt es nichts zu verstecken.
"""

from __future__ import annotations

import subprocess
import sys


def unsichtbar() -> dict:
    """Zusaetzliche Argumente fuer subprocess.Popen/run."""
    if not sys.platform.startswith("win"):
        return {}
    start = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    start.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    start.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": start}  # type: ignore[attr-defined]


def losgeloest() -> dict:
    """Argumente fuer den Arbeitsprozess der Oberflaeche: er ueberlebt das
    Ende des Fensters, haengt an keiner Konsole und zeigt kein Fenster."""
    if not sys.platform.startswith("win"):
        return {"start_new_session": True}
    start = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    start.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    start.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    # DETACHED_PROCESS: keine Konsole erben und keine neue oeffnen.
    # CREATE_NEW_PROCESS_GROUP: ein Strg+C im Fenster erreicht ihn nicht.
    return {
        "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
        "startupinfo": start,
    }
