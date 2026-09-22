"""Die Schnittstelle zwischen Seite und Ablauf (Phase 7).

Jede Anfrage ist klein und liefert nur Zusammenfassungen oder eine Seite
einer Liste (SPEC Abschnitt 8). Alle Endpunkte laufen synchron und greifen
ueber die Sperre des Ablaufs nacheinander auf die Datenbank zu.

Der Server hoert nur auf 127.0.0.1. Anfragen, die eine fremde Seite im
Browser ausloest (Origin passt nicht zum eigenen Host), werden abgelehnt;
alle Aenderungen laufen ausserdem ueber JSON-Anfragen, die ein fremder
Ursprung nicht ohne Vorabfrage stellen kann.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import FotosortFehler, meldungen
from . import ablauf as ablauf_modul

STATIC = Path(__file__).resolve().parent / "static"
STATISCHE_DATEIEN = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "fonts.css": "text/css; charset=utf-8",
}


def app_bauen(ab: ablauf_modul.Ablauf) -> FastAPI:
    app = FastAPI(title="fotosort", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def herkunft_pruefen(request: Request, call_next):
        herkunft = request.headers.get("origin")
        host = request.headers.get("host", "")
        if herkunft and herkunft.lower() not in (f"http://{host}".lower(), "null"):
            return JSONResponse({"fehler": meldungen.ob_herkunft_abgelehnt()}, status_code=403)
        antwort = await call_next(request)
        antwort.headers["Cache-Control"] = "no-store"
        return antwort

    @app.exception_handler(FotosortFehler)
    async def fehler_melden(_request: Request, fehler: FotosortFehler):
        return JSONResponse({"fehler": str(fehler)}, status_code=400)

    @app.get("/")
    def startseite():
        return FileResponse(STATIC / "index.html", media_type=STATISCHE_DATEIEN["index.html"])

    @app.get("/static/{name}")
    def statisch(name: str):
        if name not in STATISCHE_DATEIEN:
            return JSONResponse({"fehler": "unbekannt"}, status_code=404)
        return FileResponse(STATIC / name, media_type=STATISCHE_DATEIEN[name])

    @app.get("/static/fonts/{name}")
    def schrift(name: str):
        # Nur die mitgelieferten Schriftdateien, keine Pfadbestandteile.
        if "/" in name or "\\" in name or not name.endswith(".woff2") or not (STATIC / "fonts" / name).is_file():
            return JSONResponse({"fehler": "unbekannt"}, status_code=404)
        return FileResponse(STATIC / "fonts" / name, media_type="font/woff2")

    @app.get("/api/zustand")
    def zustand():
        return ab.zustand()

    @app.post("/api/ziel")
    def ziel(daten: dict = Body(...)):
        return ab.ziel_setzen(str(daten.get("ziel", "")))

    @app.post("/api/einstellungen")
    def einstellungen(daten: dict = Body(...)):
        return ab.einstellungen_setzen(
            verschieben=daten.get("verschieben"), profil=daten.get("profil"),
        )

    @app.post("/api/quelle")
    def quelle(daten: dict = Body(...)):
        if daten.get("entfernen"):
            return ab.quelle_entfernen(str(daten.get("pfad", "")))
        return ab.quelle_hinzufuegen(str(daten.get("pfad", "")), trotzdem=bool(daten.get("trotzdem", False)))

    @app.post("/api/los")
    def los(daten: dict = Body(default={})):
        return ab.los(ziel_anlegen=bool(daten.get("ziel_anlegen", False)),
                      ziel_trotzdem=bool(daten.get("ziel_trotzdem", False)))

    @app.post("/api/verwerfen")
    def verwerfen(daten: dict = Body(default={})):
        return ab.archiv_verwerfen(str(daten.get("wort", "")))

    @app.get("/api/lauf")
    def lauf():
        return ab.lauf_status()

    @app.post("/api/steuern")
    def steuern(daten: dict = Body(...)):
        return ab.steuern(str(daten.get("wunsch", "")))

    @app.get("/api/naechster")
    def naechster():
        return ab.naechster()

    @app.post("/api/schritt")
    def schritt(daten: dict = Body(...)):
        return ab.schritt(
            str(daten.get("schritt", "")), wort=str(daten.get("wort", "")), weise=str(daten.get("weise", "")),
            leere_ordner=bool(daten.get("leere_ordner", False)), wort_ordner=str(daten.get("wort_ordner", "")),
        )

    @app.get("/api/zusammenfassung")
    def zusammenfassung(schritt: str):
        return ab.zusammenfassung(schritt)

    @app.get("/api/aufraeumen_plan")
    def aufraeumen_plan():
        return ab.aufraeumen_plan()

    @app.post("/api/aliase")
    def aliase(daten: dict = Body(...)):
        return ab.aliase_setzen(dict(daten.get("aliase") or {}))

    @app.get("/api/liste")
    def liste(art: str, seite: int = 1):
        return ab.liste(art, seite)

    @app.post("/api/bericht")
    def bericht(daten: dict = Body(default={})):
        return ab.bericht_oeffnen(str(daten.get("art", "neu")))

    @app.post("/api/einstellungen_oeffnen")
    def einstellungen_oeffnen():
        return ab.einstellungen_oeffnen()

    return app


class Server:
    """uvicorn in einem eigenen Strang; die Oberflaeche wartet nur auf ihn."""

    def __init__(self, app: FastAPI, port: int = 0) -> None:
        self.app = app
        self.port = int(port or 0)
        self.adresse = ""
        self._server = None
        self._strang: threading.Thread | None = None
        self._socket: socket.socket | None = None

    def starten(self, wartezeit: float = 20.0) -> str:
        import uvicorn

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.listen(64)
        self.port = sock.getsockname()[1]
        self._socket = sock
        self.adresse = f"http://127.0.0.1:{self.port}/"
        konfig = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning", access_log=False)
        self._server = uvicorn.Server(konfig)
        self._strang = threading.Thread(target=self._server.run, kwargs={"sockets": [sock]}, name="oberflaeche-server", daemon=True)
        self._strang.start()
        ende = time.monotonic() + wartezeit
        while time.monotonic() < ende:
            if getattr(self._server, "started", False):
                return self.adresse
            if not self._strang.is_alive():
                break
            time.sleep(0.05)
        raise OSError("Server nicht gestartet")

    def warten(self) -> None:
        """Bis Strg+C (nur ohne Fenster)."""
        try:
            while self._strang is not None and self._strang.is_alive():
                self._strang.join(0.5)
        except KeyboardInterrupt:
            pass

    def beenden(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._strang is not None:
            self._strang.join(10)
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
