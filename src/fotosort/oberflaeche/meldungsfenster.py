"""Fehler vor oder beim Start verstaendlich zeigen - auch dann, wenn Qt selbst
nicht geladen werden konnte. Unter Windows ein normales Meldungsfenster des
Systems (ctypes, immer vorhanden); sonst die Fehlerausgabe.

Nie "Unhandled exception in script": Wer das Fensterprogramm startet, sieht
einen deutschen Satz, was zu tun ist, und wo das Protokoll liegt.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

MB_OK = 0x0
MB_ICONERROR = 0x10
MB_SETFOREGROUND = 0x10000


def zeigen(titel: str, text: str) -> None:
    """Meldungsfenster (Windows) oder Text auf der Fehlerausgabe."""
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, titel, MB_OK | MB_ICONERROR | MB_SETFOREGROUND)
            return
        except Exception:  # noqa: BLE001 - dann eben Text
            pass
    try:
        print(f"{titel}\n{text}", file=sys.stderr or sys.stdout)
    except Exception:  # noqa: BLE001
        pass


def protokollieren(protokoll: Path | None, text: str) -> None:
    if protokoll is None:
        return
    try:
        protokoll.parent.mkdir(parents=True, exist_ok=True)
        with open(protokoll, "a", encoding="utf-8", errors="replace") as f:
            f.write(text + "\n")
    except OSError:
        pass


def starttext(fehler: BaseException, protokoll: Path | None) -> str:
    """Der Text fuer das Fenster: was passiert ist, was zu tun ist, wo das Protokoll liegt."""
    from .. import meldungen
    return meldungen.ob_startfehler(f"{type(fehler).__name__}: {fehler}", protokoll)


def startfehler(fehler: BaseException, protokoll: Path | None) -> None:
    """Fuer den Einstieg des gepackten Programms: protokollieren und zeigen."""
    protokollieren(protokoll, "=== Startfehler ===\n" + "".join(traceback.format_exception(fehler)))
    zeigen("fotosort konnte nicht starten", starttext(fehler, protokoll))


def excepthook_einrichten(protokoll: Path | None) -> None:
    """Unerwartete Fehler im laufenden Fenster: protokollieren, zeigen, weiterlaufen."""
    from .. import meldungen

    def haken(art, wert, tb):
        text = "".join(traceback.format_exception(art, wert, tb))
        protokollieren(protokoll, "=== Fehler im Fenster ===\n" + text)
        zeigen("fotosort: unerwarteter Fehler", meldungen.ob_laufzeitfehler(f"{art.__name__}: {wert}", protokoll))

    sys.excepthook = haken
