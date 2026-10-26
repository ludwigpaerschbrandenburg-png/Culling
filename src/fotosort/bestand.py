"""Bestand des Archivs kennen (Runde 3a, Entscheidung vom 26.10.2026).

Ein Archiv, das jemand selbst angelegt hat, kennt das Programm zunaechst
nicht. Der Scan erfasst deshalb jede Datei im Ziel mit Namen, Groesse und
Aenderungszeit im Ziel-Index - ohne sie zu lesen (Hash leer). Das geht auch
bei sehr vielen Bildern schnell und laesst eine Festplatte nicht springen.

Gelesen wird erst beim Kopieren, und nur dort, wo es noetig ist: Hat eine
Quelldatei genau dieselbe Groesse wie Archivdateien ohne Hash, werden diese
gelesen und verglichen (kopieren.py). Gleicher Inhalt heisst: bereits
importiert - die Quelldatei wird nicht noch einmal abgelegt.

Im Ziel wird nichts veraendert. Der Index entscheidet nie allein ueber eine
Loeschung (SPEC §6); entfernt werden hier keine Zeilen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import db, steuerung, zielindex


@dataclass
class Ergebnis:
    dateien: int = 0       # Dateien im Archiv
    neu: int = 0           # davon erstmals oder veraendert erfasst


def erfassen(ziel: Path, dbank: db.Datenbank) -> Ergebnis:
    e = Ergebnis()
    for datei in zielindex.dateien_im_ziel(Path(ziel), zielindex.Ergebnis(), melden=steuerung.wuensche_pruefen):
        e.dateien += 1
        if dbank.ziel_index_erfassen(datei.pfad, datei.groesse, datei.mtime):
            e.neu += 1
    dbank.stapel_schreiben()
    return e
