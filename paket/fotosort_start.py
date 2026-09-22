"""Einstieg fuer das mit PyInstaller gepackte Programm (paket/bauen.py).

Nichts weiter als der normale Einstieg der Kommandozeile; die Datei gibt es
nur, weil PyInstaller ein Skript und kein Modul als Startpunkt braucht.
"""

import sys

from fotosort.cli import main

if __name__ == "__main__":
    sys.exit(main())
