"""Das Fenster (Phase 7): Server starten, pywebview-Fenster oeffnen.

Ohne Fenster (--ohne-fenster) laeuft nur der Server, und die Adresse wird
genannt - fuer den Browser, spaeter fuer den Container auf dem Server.
--selbsttest oeffnet das Fenster, laesst die Seite den Zustand abfragen und
schliesst wieder; so prueft die CI, dass das gepackte Fenster wirklich
startet.
"""

from __future__ import annotations

import json
import threading
import urllib.request

from .. import meldungen
from . import ablauf as ablauf_modul
from . import server as server_modul

OK = 0
FEHLER = 1
TITEL = "Foto-Sortierer"
SELBSTTEST_JS = """
(function () {
  function melden(text) { window.pywebview.api.selbsttest_ergebnis(text); }
  function los() {
    fetch('/api/zustand').then(function (r) { return r.json(); }).then(function (z) {
      melden(JSON.stringify({zustand: z, seite: !!document.querySelector('#seite-start'), titel: document.title}));
    }).catch(function (e) { melden('FEHLER ' + e); });
  }
  if (window.pywebview && window.pywebview.api) { los(); } else { window.addEventListener('pywebviewready', los); }
})();
"""


class _Api:
    """Was die Seite im Fenster direkt aufrufen darf (window.pywebview.api).

    pywebview reicht jedes oeffentliche Attribut dieses Objekts an die Seite
    durch - auch verschachtelt. Deshalb sind Fenster, Ergebnis und Ereignis
    privat (Unterstrich): Die Seite darf nur die beiden Methoden rufen.
    """

    def __init__(self) -> None:
        self._fenster = None
        self._ergebnis: str | None = None
        self._fertig = threading.Event()

    def ordner_waehlen(self, start: str = "") -> str:
        import webview

        if self._fenster is None:
            return ""
        auswahl = self._fenster.create_file_dialog(webview.FileDialog.FOLDER, directory=str(start or ""))
        if not auswahl:
            return ""
        if isinstance(auswahl, (list, tuple)):
            return str(auswahl[0]) if auswahl else ""
        return str(auswahl)

    def selbsttest_ergebnis(self, text: str) -> None:
        self._ergebnis = str(text)
        self._fertig.set()


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


def _selbsttest_im_fenster(fenster, api: _Api, rc: list, konsole, zeit: float = 60.0) -> None:
    def laufen() -> None:
        try:
            fenster.evaluate_js(SELBSTTEST_JS)
        except Exception as fehler:  # noqa: BLE001
            api._ergebnis = f"FEHLER {fehler}"
            api._fertig.set()
        if not api._fertig.wait(zeit):
            rc[0] = FEHLER
            konsole.print(meldungen.ob_selbsttest(False, "die Seite hat sich nicht gemeldet"))
        else:
            ergebnis = api._ergebnis or ""
            ok = False
            einzelheit = ergebnis
            if not ergebnis.startswith("FEHLER"):
                try:
                    daten = json.loads(ergebnis)
                    ok = bool(daten.get("seite")) and "version" in (daten.get("zustand") or {})
                    einzelheit = f"Version {daten.get('zustand', {}).get('version', '?')}, Titel „{daten.get('titel', '')}“"
                except ValueError:
                    pass
            rc[0] = OK if ok else FEHLER
            konsole.print(meldungen.ob_selbsttest(ok, einzelheit))
        try:
            fenster.destroy()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=laufen, name="selbsttest", daemon=True).start()


def starten(ohne_fenster: bool, port: int, selbsttest: bool, ziel: str | None, konsole) -> int:
    ab = ablauf_modul.Ablauf(ziel=ziel)
    app = server_modul.app_bauen(ab)
    srv = server_modul.Server(app, port)
    try:
        adresse = srv.starten()
    except OSError as fehler:
        konsole.print(meldungen.ob_server_fehlgeschlagen(fehler))
        return FEHLER
    try:
        if ohne_fenster:
            konsole.print(meldungen.ob_adresse(adresse))
            if selbsttest:
                return _selbsttest_http(adresse, konsole)
            srv.warten()
            return OK
        try:
            import webview
        except ImportError as fehler:
            konsole.print(meldungen.ob_kein_fenster(str(fehler)))
            return FEHLER
        ab.fenster = True
        api = _Api()
        fenster = webview.create_window(TITEL, adresse, js_api=api, width=1120, height=820, min_size=(760, 560))
        api._fenster = fenster
        rc = [OK]
        if selbsttest:
            gestartet = [False]

            def bei_laden() -> None:
                if not gestartet[0]:
                    gestartet[0] = True
                    _selbsttest_im_fenster(fenster, api, rc, konsole)

            fenster.events.loaded += bei_laden

            def waechter() -> None:
                if not api._fertig.wait(120):
                    rc[0] = FEHLER
                    konsole.print(meldungen.ob_selbsttest(False, "Fenster oder Seite haben nicht geladen"))
                    try:
                        fenster.destroy()
                    except Exception:  # noqa: BLE001
                        pass

            threading.Thread(target=waechter, name="selbsttest-waechter", daemon=True).start()
        try:
            webview.start(private_mode=False)
        except Exception as fehler:  # noqa: BLE001 - z. B. keine Anzeige, kein WebView2
            konsole.print(meldungen.ob_kein_fenster(f"{type(fehler).__name__}: {fehler}"))
            return FEHLER
        return rc[0]
    finally:
        srv.beenden()
