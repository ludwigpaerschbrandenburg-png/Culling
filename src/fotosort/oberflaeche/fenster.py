"""Einstieg der Oberflaeche (Phase 7).

Ohne Angaben: das Desktop-Fenster (desktop.py, PySide6) - unter Windows das
Programm mit Taskleisten-Symbol und Ordnerdialogen. Mit --ohne-fenster nur
der Server der Browser-Fassung (server.py), der die Adresse nennt - fuer den
spaeteren Betrieb im Container (Phase 8). --selbsttest oeffnet das Fenster,
liest den Zustand und schliesst wieder; --durchlauf ZIEL QUELLE faehrt den
ganzen Ablauf ueber das Fenster (CI, Bildschirmfotos).
"""

from __future__ import annotations

import json
import urllib.request

from .. import meldungen
from . import ablauf as ablauf_modul
from . import meldungsfenster

# Der Server der Browser-Fassung (fastapi, uvicorn) wird erst geladen, wenn er
# gebraucht wird: Das Windows-Paket enthaelt ihn nicht (dort gibt es das
# Fenster), und das Fenster darf nicht an einer fehlenden Bibliothek scheitern.

OK = 0
FEHLER = 1


def _selbsttest_http(adresse: str, konsole) -> int:
    try:
        with urllib.request.urlopen(adresse + "api/zustand", timeout=20) as antwort:
            daten = json.loads(antwort.read().decode("utf-8"))
        with urllib.request.urlopen(adresse, timeout=20) as antwort:
            seite = antwort.read().decode("utf-8")
    except Exception as fehler:  # noqa: BLE001 - jeder Grund ist ein Fehlschlag
        konsole.print(meldungen.ob_selbsttest(False, str(fehler), fenster=False))
        return FEHLER
    ok = "version" in daten and 'id="seite-start"' in seite
    konsole.print(meldungen.ob_selbsttest(ok, f"Version {daten.get('version', '?')}", fenster=False))
    return OK if ok else FEHLER


def server_starten(port: int, selbsttest: bool, ziel: str | None, konsole) -> int:
    """Nur der Server (Browser-Fassung): Adresse nennen, bis Strg+C laufen."""
    try:
        from . import server as server_modul
    except ImportError as fehler:
        konsole.print(meldungen.ob_server_fehlt(f"{type(fehler).__name__}: {fehler}"))
        return FEHLER
    ab = ablauf_modul.Ablauf(ziel=ziel)
    app = server_modul.app_bauen(ab)
    srv = server_modul.Server(app, port)
    try:
        adresse = srv.starten()
    except OSError as fehler:
        konsole.print(meldungen.ob_server_fehlgeschlagen(fehler))
        return FEHLER
    try:
        konsole.print(meldungen.ob_adresse(adresse))
        if selbsttest:
            return _selbsttest_http(adresse, konsole)
        srv.warten()
        return OK
    finally:
        srv.beenden()


def starten(ohne_fenster: bool, port: int, selbsttest: bool, ziel: str | None, konsole,
            durchlauf: tuple[str, str] | None = None, fotos: str | None = None) -> int:
    if ohne_fenster:
        return server_starten(port, selbsttest, ziel, konsole)
    try:
        from . import desktop
    except Exception as fehler:  # noqa: BLE001 - PySide6 fehlt oder laedt nicht (z. B. libEGL)
        text = meldungen.ob_qt_fehlt(f"{type(fehler).__name__}: {fehler}")
        konsole.print(text)
        meldungsfenster.zeigen("fotosort: Fenster nicht verfügbar", text)
        return FEHLER
    return desktop.starten(ziel, selbsttest=selbsttest, durchlauf=durchlauf, fotos=fotos, konsole=konsole)
