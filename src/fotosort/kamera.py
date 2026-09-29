"""Kamera-Ordner aus dem Modellnamen (SPEC Abschnitt 3, "Kamera-Ordner").

Reine Logik: Model (ersatzweise Make + Model) -> Alias-Tabelle -> sonst
bereinigter Modellname -> ohne Modell der konfigurierte Name fuer
"Unbekannte_Kamera".
"""

from __future__ import annotations

import re

# Unter Windows und Linux in Dateinamen verboten, dazu Steuerzeichen.
_VERBOTEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MEHRFACH_LEER = re.compile(r"\s+")

#: Geraetenamen, die unter Windows kein Ordner- oder Dateiname sein duerfen -
#: auch nicht mit Endung ("NUL.jpg"). Verglichen ohne Gross-/Kleinschreibung.
_GERAETENAMEN = frozenset(
    ["con", "prn", "aux", "nul"] + [f"com{i}" for i in range(1, 10)] + [f"lpt{i}" for i in range(1, 10)]
)


def windows_sicher(teil: str) -> str:
    """Einen Ordnernamen so anpassen, dass Windows ihn ohne Sonderweg kennt:
    kein Punkt und kein Leerzeichen am Ende (Windows schneidet sie still ab),
    kein Geraetename (dann mit "_" dahinter). Gilt auf allen Systemen - das
    Archiv soll auch ueber eine Freigabe unter Windows lesbar bleiben."""
    teil = teil.rstrip(". ")
    if teil.split(".", 1)[0].strip().lower() in _GERAETENAMEN:
        teil += "_"
    return teil


def rohmodell(felder: dict | None) -> str:
    """Der Modellname, wie er in den Metadaten steht; leer, wenn keiner da ist.

    Bevorzugt Model. Steht darin der Hersteller nicht schon drin, kommt Make
    davor - so wird aus "SONY" + "ILCE-7CM2" nicht "SONY SONY ILCE-7CM2".
    Sony-Videos tragen das Modell im eingebetteten XML (DeviceModelName).
    """
    felder = felder or {}
    return str(felder.get("Model") or felder.get("DeviceModelName") or "").strip()


def _bereinigen(text: str) -> str:
    text = _VERBOTEN.sub("_", text)
    text = _MEHRFACH_LEER.sub(" ", text).strip().strip("._ ")
    if not any(z.isalnum() for z in text):
        return ""
    return windows_sicher(text)


def ordnername(felder: dict | None, konf) -> tuple[str, str]:
    """(Ordnername, Rohmodell) fuer eine Datei.

    Die Alias-Tabelle wird zuerst mit dem Modell, dann mit "Make Model"
    verglichen, jeweils ohne Rucksicht auf Gross-/Kleinschreibung.
    """
    felder = felder or {}
    roh = rohmodell(felder)
    unbekannt = _bereinigen(str(konf.wert("kamera.unbekannt") or "")) or "Unbekannte_Kamera"
    if not roh:
        return unbekannt, ""

    aliase = {str(k).strip().lower(): str(v) for k, v in (konf.wert("kamera.aliase") or {}).items()}
    make = str(felder.get("Make") or "").strip()
    kandidaten = [roh]
    if make and not roh.lower().startswith(make.lower()):
        kandidaten.append(f"{make} {roh}")
    for kandidat in kandidaten:
        treffer = aliase.get(kandidat.lower())
        if treffer:
            return _bereinigen(treffer) or unbekannt, roh

    bereinigt = _bereinigen(roh)
    return bereinigt or unbekannt, roh
