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


def rohmodell(felder: dict | None) -> str:
    """Der Modellname, wie er in den Metadaten steht; leer, wenn keiner da ist.

    Bevorzugt Model. Steht darin der Hersteller nicht schon drin, kommt Make
    davor - so wird aus "SONY" + "ILCE-7CM2" nicht "SONY SONY ILCE-7CM2".
    Sony-Videos tragen das Modell im eingebetteten XML (DeviceModelName).
    """
    felder = felder or {}
    model = str(felder.get("Model") or felder.get("DeviceModelName") or "").strip()
    make = str(felder.get("Make") or "").strip()
    if model:
        return model
    return make


def _bereinigen(text: str) -> str:
    text = _VERBOTEN.sub("_", text)
    text = _MEHRFACH_LEER.sub(" ", text).strip().strip("._ ")
    if not any(z.isalnum() for z in text):
        return ""
    return text


def ordnername(felder: dict | None, konf) -> tuple[str, str]:
    """(Ordnername, Rohmodell) fuer eine Datei.

    Die Alias-Tabelle wird zuerst mit dem Modell, dann mit "Make Model"
    verglichen, jeweils ohne Rucksicht auf Gross-/Kleinschreibung.
    """
    felder = felder or {}
    roh = rohmodell(felder)
    unbekannt = str(konf.wert("kamera.unbekannt") or "Unbekannte_Kamera")
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
