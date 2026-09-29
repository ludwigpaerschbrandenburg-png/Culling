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
    """Wann der Prozess gestartet wurde, in Sekunden; None, wenn das hier nicht
    feststellbar ist. Damit laesst sich eine wiederverwendete Prozessnummer von
    "unserem" Arbeitsprozess unterscheiden: Ein fremder Prozess mit derselben
    Nummer hat eine andere Startzeit.

    Nur zum Vergleichen gedacht, keine Uhrzeit: Unter Windows zaehlt sie ab
    1970, unter Linux ab dem Hochfahren - dort haengt sie so nicht an der Uhr
    (die Bootzeit in /proc/stat verschiebt sich bei jedem Stellen der Uhr)."""
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

            with open(f"/proc/{int(pid)}/stat", "rb") as f:
                stat = f.read().decode("ascii", "replace")
            felder = stat[stat.rindex(")") + 2:].split()      # nach "(name)" beginnt Feld 3
            ticks = int(felder[19])                           # Feld 22: Startzeit in Takten seit dem Hochfahren
            return ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None
    return None


def _nachkommen(eintraege, wurzel: int, wurzel_start: float | None) -> list[int]:
    """Aus (Nummer, Eltern-Nummer, erstellt) die Nachkommen von wurzel.

    Windows merkt sich den Elternprozess nur als Nummer und vergibt Nummern
    schnell neu. Ein Prozess, der VOR seinem angeblichen Elternprozess
    entstand, ist darum nicht dessen Kind - etwa das Fenster, wenn die Nummer
    seines laengst beendeten Starters an den Arbeitsprozess ging. Ohne lesbare
    Startzeit wird nichts angefasst."""
    erstellt: dict[int, float | None] = {}
    kinder: dict[int, list[int]] = {}
    for pid, eltern, zeit in eintraege:
        erstellt[pid] = zeit
        if pid != eltern:
            kinder.setdefault(eltern, []).append(pid)
    if wurzel_start is None:
        wurzel_start = erstellt.get(wurzel)
    start = {wurzel: wurzel_start}
    ergebnis: list[int] = []
    offen = [wurzel]
    while offen:
        eltern = offen.pop()
        eltern_start = start[eltern]
        for kind in kinder.get(eltern, ()):
            zeit = erstellt.get(kind)
            if kind in start or zeit is None or eltern_start is None or zeit < eltern_start:
                continue
            start[kind] = zeit
            ergebnis.append(kind)
            offen.append(kind)
    return ergebnis


def _windows_prozesse() -> list[tuple[int, int, float | None]]:  # pragma: no cover - nur Windows
    """Alle Prozesse als (Nummer, Eltern-Nummer, Startzeit)."""
    import ctypes
    from ctypes import wintypes

    class Eintrag(ctypes.Structure):   # PROCESSENTRY32W
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Eintrag))
    k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Eintrag))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    schnappschuss = k32.CreateToolhelp32Snapshot(0x2, 0)    # TH32CS_SNAPPROCESS
    if not schnappschuss or schnappschuss == wintypes.HANDLE(-1).value:
        return []
    paare: list[tuple[int, int]] = []
    try:
        e = Eintrag()
        e.dwSize = ctypes.sizeof(Eintrag)
        weiter = k32.Process32FirstW(schnappschuss, ctypes.byref(e))
        while weiter:
            paare.append((int(e.th32ProcessID), int(e.th32ParentProcessID)))
            weiter = k32.Process32NextW(schnappschuss, ctypes.byref(e))
    finally:
        k32.CloseHandle(schnappschuss)
    return [(pid, eltern, startzeit(pid) if pid else None) for pid, eltern in paare]


def _windows_hart_beenden(pid: int) -> None:  # pragma: no cover - nur Windows
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    griff = k32.OpenProcess(0x0001, False, int(pid))   # PROCESS_TERMINATE
    if griff:
        try:
            k32.TerminateProcess(griff, 1)
        finally:
            k32.CloseHandle(griff)


def baum_beenden_pid(pid: int, start: float | None = None) -> None:  # pragma: no cover - nur Windows
    """Windows: den Prozess und seine echten Nachkommen hart beenden. Kein
    taskkill /T - das nimmt jeden, der dieselbe Eltern-Nummer traegt, auch
    wenn sie inzwischen einem ganz anderen Prozess gehoerte (_nachkommen)."""
    jetzt = startzeit(pid)
    if start is not None and jetzt is not None and abs(jetzt - float(start)) > 2.0:
        return   # die Nummer gehoert inzwischen einem fremden Prozess
    try:
        eintraege = _windows_prozesse()
    except OSError:
        eintraege = []
    ziele = _nachkommen(eintraege, int(pid), jetzt if jetzt is not None else start)
    # Erst die Wurzel, damit sie keine neuen Kinder mehr startet, dann die Kinder.
    for nummer in [int(pid)] + ziele:
        try:
            _windows_hart_beenden(nummer)
        except OSError:
            pass


def baum_beenden(prozess: subprocess.Popen) -> None:
    """Einen Hilfsprozess samt seinen Kindern hart beenden.

    Unter Windows ist exiftool.exe nur ein Starter fuer perl.exe, das die
    Ausgabe-Pipe haelt: Wuerde nur der Starter beendet, bliebe das Lesen der
    Antwort ewig stehen. Beendet wird deshalb der ganze Prozessbaum.
    """
    if sys.platform.startswith("win"):
        baum_beenden_pid(prozess.pid)
    try:
        prozess.kill()
    except OSError:
        pass
