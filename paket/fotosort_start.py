"""Einstieg des Windows-Pakets (liegt dort als lib\\fotosort_start.py).

start.bat startet ihn mit dem mitgelieferten, signierten python\\pythonw.exe
(das Fenster, ohne Konsole), fotosort.bat mit python\\python.exe (Befehle mit
Ausgabe). Er ist der normale Einstieg der Kommandozeile - und ein Fangnetz:
Geht vor oder beim Start etwas schief, erscheint ein verstaendliches
Meldungsfenster mit Grund, Rat und dem Ort des Protokolls, nie eine
unverstaendliche Fehlermeldung (und unter pythonw.exe nie gar nichts).

Er wird als Datei gestartet, nicht als Modul: So erscheint das Meldungsfenster
selbst dann, wenn der Ordner lib\\ beschaedigt ist und fotosort sich nicht
laden laesst.
"""

import sys


def _fangnetz(fehler: BaseException) -> int:
    try:
        from fotosort import cli
        from fotosort.oberflaeche import meldungsfenster
        protokoll = None
        try:
            protokoll = cli.fenster_protokoll()
        except Exception:  # noqa: BLE001
            pass
        meldungsfenster.startfehler(fehler, protokoll)
    except Exception:  # noqa: BLE001 - selbst das Fangnetz reisst: das Noetigste zeigen
        import traceback
        text = "fotosort konnte nicht starten.\n\n" + "".join(traceback.format_exception(fehler))[-1500:]
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, text, "fotosort konnte nicht starten", 0x10)
            except Exception:  # noqa: BLE001
                pass
        try:
            print(text, file=sys.stderr or sys.stdout)
        except Exception:  # noqa: BLE001
            pass
    return 1


if __name__ == "__main__":
    try:
        from fotosort.cli import main
        rc = main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        rc = 130
    except BaseException as fehler:  # noqa: BLE001 - alles, was den Start verhindert
        rc = _fangnetz(fehler)
    sys.exit(rc)
