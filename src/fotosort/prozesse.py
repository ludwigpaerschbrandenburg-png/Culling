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


def startzeit(pid: int) -> float | None:
    """Wann der Prozess gestartet wurde (Sekunden seit 1970); None, wenn das
    hier nicht feststellbar ist. Damit laesst sich eine wiederverwendete
    Prozessnummer von "unserem" Arbeitsprozess unterscheiden: Ein fremder
    Prozess mit derselben Nummer hat eine andere Startzeit."""
    try:
        if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.windll.kernel32
            griff = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
            if not griff:
                return None
            try:
                erstellt, beendet, kern, nutzer = (wintypes.FILETIME() for _ in range(4))
                if not k32.GetProcessTimes(griff, ctypes.byref(erstellt), ctypes.byref(beendet),
                                           ctypes.byref(kern), ctypes.byref(nutzer)):
                    return None
            finally:
                k32.CloseHandle(griff)
            hundert_ns = (erstellt.dwHighDateTime << 32) | erstellt.dwLowDateTime
            return (hundert_ns - 116444736000000000) / 1e7   # FILETIME beginnt 1601
        if sys.platform.startswith("linux"):
            import os

            stat = open(f"/proc/{int(pid)}/stat", "rb").read().decode("ascii", "replace")
            felder = stat[stat.rindex(")") + 2:].split()      # nach "(name)" beginnt Feld 3
            ticks = int(felder[19])                           # Feld 22: Startzeit in Takten seit dem Hochfahren
            takte = os.sysconf("SC_CLK_TCK")
            with open("/proc/stat", "rb") as f:
                for zeile in f:
                    if zeile.startswith(b"btime "):
                        return int(zeile.split()[1]) + ticks / takte
            return None
    except (OSError, ValueError, IndexError):
        return None
    return None


def baum_beenden(prozess: subprocess.Popen) -> None:
    """Einen Hilfsprozess samt seinen Kindern hart beenden.

    Unter Windows ist exiftool.exe nur ein Starter fuer perl.exe, das die
    Ausgabe-Pipe haelt: Wuerde nur der Starter beendet, bliebe das Lesen der
    Antwort ewig stehen. taskkill /T nimmt den ganzen Prozessbaum.
    """
    if sys.platform.startswith("win"):
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(prozess.pid)],
                           capture_output=True, timeout=30, check=False, **unsichtbar())
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        prozess.kill()
    except OSError:
        pass
