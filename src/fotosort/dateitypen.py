"""Dateityp und Sidecar-Zuordnung - reine Logik, kein Dateisystemzugriff.

SPEC Abschnitt 3 ("Dateitypen", "Zusammengehoerige Dateien").
"""

from __future__ import annotations

import fnmatch
import re
from functools import lru_cache

FOTO = "foto"
RAW = "raw"
VIDEO = "video"
SIDECAR = "sidecar"
SONSTIGES = "sonstiges"

# Nur diese vier sind echte Dateitypen. An ihnen haengt, dass keine Datei
# aus dem Bestand der Datenbank je als Reste-Datei durchgeht (SPEC Abschnitt 5).
ECHTE_TYPEN: frozenset[str] = frozenset({FOTO, RAW, VIDEO, SIDECAR})

# Reihenfolge der Abfrage; entscheidet nur, wenn der Nutzer eine Endung in
# zwei Gruppen eintraegt.
_GRUPPEN = ((FOTO, "foto"), (RAW, "raw"), (VIDEO, "video"), (SIDECAR, "sidecar"))


def _endung(name: str) -> str:
    """Endung ohne Punkt, kleingeschrieben; "" wenn keine da ist."""
    stelle = name.rfind(".")
    if stelle <= 0 or stelle == len(name) - 1:
        return ""
    return name[stelle + 1 :].lower()


def _stamm(name: str) -> str:
    stelle = name.rfind(".")
    if stelle <= 0:
        return name
    return name[:stelle]


def _endungen(konf, gruppe: str) -> set[str]:
    werte = konf.wert(f"dateitypen.{gruppe}")
    return {str(e).lower().lstrip(".") for e in werte}


def typ_von(name: str, konf) -> str:
    """foto | raw | video | sidecar | sonstiges.

    Der Endungsvergleich ist unabhaengig von Gross- und Kleinschreibung
    (SPEC Abschnitt 3).
    """
    endung = _endung(name)
    if not endung:
        return SONSTIGES
    for typ, gruppe in _GRUPPEN:
        if endung in _endungen(konf, gruppe):
            return typ
    return SONSTIGES


def ist_echter_typ(typ: str) -> bool:
    return typ in ECHTE_TYPEN


@lru_cache(maxsize=256)
def _muster(glob: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(glob), re.IGNORECASE)


def sidecar_gehoert_zu(sidecar_name: str, haupt_name: str, konf) -> bool:
    """Gehoert das Sidecar zu dieser Hauptdatei? (SPEC Abschnitt 3)

    Drei Formen:
      1. Stammname + Sidecar-Endung            DSC01234.xmp  zu DSC01234.ARW
      2. vollstaendiger Dateiname + Endung     DSC01234.ARW.xmp zu DSC01234.ARW
      3. Stammname + Zusatzmuster + Endung     C0001M01.XML zu C0001.MP4
    """
    if sidecar_name == haupt_name:
        return False
    if typ_von(sidecar_name, konf) != SIDECAR:
        return False
    # Eine Hauptdatei ist Foto, RAW oder Video - nie ein zweites Sidecar.
    if typ_von(haupt_name, konf) not in (FOTO, RAW, VIDEO):
        return False

    sidecar_stamm = _stamm(sidecar_name)
    haupt_stamm = _stamm(haupt_name)

    # Form 2: vollstaendiger Dateiname plus Endung.
    if sidecar_stamm.lower() == haupt_name.lower():
        return True
    # Form 1: Stammname plus Endung.
    if sidecar_stamm.lower() == haupt_stamm.lower():
        return True
    # Form 3: Stammname plus Zusatzmuster plus Endung.
    if len(sidecar_stamm) > len(haupt_stamm) and sidecar_stamm.lower().startswith(
        haupt_stamm.lower()
    ):
        zusatz = sidecar_stamm[len(haupt_stamm) :]
        for glob in konf.wert("dateitypen.sidecar_zusatzmuster"):
            if _muster(str(glob)).match(zusatz):
                return True
    return False
