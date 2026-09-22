"""Was hinter der Oberflaeche passiert (Phase 7).

Jeder Schritt (scan, analyse, kopieren, pruefen, aufraeumen) laeuft als
eigener Prozess "fotosort arbeit --auftrag <datei>". Die Oberflaeche
schreibt den Auftrag, startet den Prozess losgeloest (Fenster schliessen
beendet ihn nicht) und liest waehrend des Laufs nur die kleine Statusdatei,
die der Prozess schreibt (steuerung.py). Erst wenn kein Prozess mehr laeuft,
liest sie die Datenbank fuer Zusammenfassungen und Listen - nur lesend, und
in diesem Prozess durch eine Sperre nacheinander (SPEC Abschnitt 6: die
Datenbank bleibt einstraengig).

Kein HTML hier, keine Texte: die stehen in meldungen.py und in static/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .. import FotosortFehler, __version__, bericht, cli, config, db, kopieren, loeschen, meldungen, pfade, steuerung

SCHRITTE = ("scan", "analyse", "kopieren", "pruefen", "aufraeumen")
ZUSTAND_STARTET = "startet"
ZUSTAND_ABGESTUERZT = "abgestuerzt"
ENDZUSTAENDE = (steuerung.ZUSTAND_FERTIG, steuerung.ZUSTAND_ABGEBROCHEN, steuerung.ZUSTAND_FEHLER, ZUSTAND_ABGESTUERZT)
# Ohne Herzschlag so lange gilt ein uebernommener Prozess als verschwunden.
ABGESTUERZT_NACH = 5 * steuerung.HERZSCHLAG
LOG_GRENZE = 5 * 1024 * 1024
LISTEN = {
    "fehler": ("status = 'fehler'", ()),
    "duplikate": ("status IN ('duplikat', 'duplikat_bestaetigt')", ()),
    "ohne_datum": ("datum_sicher = 0 AND zielpfad != ''", ()),
}
SEITENGROESSE = 100


def oberflaeche_ordner() -> Path:
    """Statusdatei, Steuerdatei, Auftrag, Protokoll und gemerkter Zustand der
    Oberflaeche: neben den Archiv-Ordnern, immer lokal (SPEC Abschnitt 6)."""
    return db.archiv_ordner("oberflaeche")


def _kommando() -> list[str]:
    """Wie der Arbeitsprozess gestartet wird: im Paket ueber fotosort.exe
    (die Konsolenfassung, auch aus dem Fensterprogramm heraus), sonst ueber
    denselben Python-Interpreter."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        konsole = exe.with_name("fotosort.exe" if exe.suffix.lower() == ".exe" else "fotosort")
        return [str(konsole if konsole.is_file() else exe)]
    return [sys.executable, "-m", "fotosort"]


def _umgebung() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    if not getattr(sys, "frozen", False):
        quelle = str(Path(__file__).resolve().parent.parent.parent)
        bisher = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = quelle + (os.pathsep + bisher if bisher else "")
    return env


def _losgeloest() -> dict:
    """Popen-Argumente, damit der Prozess das Ende der Oberflaeche ueberlebt
    und unter Windows kein Konsolenfenster aufspringt."""
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def pid_lebt(pid: int) -> bool:
    if not pid:
        return False
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        import ctypes
        k32 = ctypes.windll.kernel32
        griff = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not griff:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(griff, ctypes.byref(code)):
                return False
            return code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(griff)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def prozess_beenden(pid: int) -> None:
    """Sofort beenden (nur auf ausdruecklichen Wunsch nach einem Abbruch, der
    nicht greift). Die Datenbank uebersteht das; Reste raeumt der naechste Lauf auf."""
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        import ctypes
        k32 = ctypes.windll.kernel32
        griff = k32.OpenProcess(0x0001, False, int(pid))   # PROCESS_TERMINATE
        if griff:
            try:
                k32.TerminateProcess(griff, 1)
            finally:
                k32.CloseHandle(griff)
        return
    import signal
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        pass


class _StilleKonsole:
    """Nimmt die Meldungen des Kerns entgegen, statt sie irgendwohin zu drucken."""

    def __init__(self) -> None:
        self.zeilen: list[str] = []

    def print(self, *teile, **_egal) -> None:
        self.zeilen.append(" ".join(str(t) for t in teile))


@dataclass
class Lauf:
    schritt: str
    prozess: subprocess.Popen | None
    pid: int
    beginn: float
    auftrag: dict


class Ablauf:
    """Der Zustand der Oberflaeche und alles, was sie tun kann."""

    def __init__(self, ziel: str | None = None, config_pfad: str | None = None, ordner: Path | None = None) -> None:
        self.ordner = Path(ordner) if ordner is not None else oberflaeche_ordner()
        self.status_datei = self.ordner / "status.json"
        self.steuer_datei = self.ordner / "steuer.json"
        self.auftrag_datei = self.ordner / "auftrag.json"
        self.zustand_datei = self.ordner / "zustand.json"
        self.log_datei = self.ordner / "arbeit.log"
        self.sperre = threading.RLock()
        self.lauf: Lauf | None = None
        self.ziel: str = str(ziel) if ziel else ""
        self.config_pfad: str | None = str(config_pfad) if config_pfad else None
        self.quellen: list[str] = []
        self.verschieben = False
        self.profil = "hdd"
        self.fenster = False      # True, wenn ein pywebview-Fenster den Ordnerdialog anbieten kann
        self._laden()

    # -- gemerkter Zustand -------------------------------------------------

    def _laden(self) -> None:
        alt = steuerung.json_lesen(self.zustand_datei) or {}
        if not self.ziel:
            self.ziel = str(alt.get("ziel") or "")
        self.quellen = [str(q) for q in alt.get("quellen") or []]
        self.verschieben = bool(alt.get("verschieben", False))
        profil = str(alt.get("profil") or "hdd")
        self.profil = profil if profil in kopieren.PROFILE else "hdd"
        # Laeuft von einem frueheren Fenster noch ein Schritt? Dann uebernehmen
        # (SPEC Abschnitt 8: Fenster schliessen beeinflusst den Lauf nicht).
        st = steuerung.json_lesen(self.status_datei) or {}
        if st.get("zustand") in (steuerung.ZUSTAND_LAEUFT, steuerung.ZUSTAND_PAUSE, ZUSTAND_STARTET):
            pid = int(st.get("pid") or 0)
            frisch = time.time() - float(st.get("aktualisiert") or 0) < ABGESTUERZT_NACH
            if pid_lebt(pid) or (frisch and st.get("zustand") == ZUSTAND_STARTET):
                auftrag = steuerung.json_lesen(self.auftrag_datei) or {}
                self.lauf = Lauf(str(st.get("schritt") or auftrag.get("schritt") or ""), None, pid,
                                 float(st.get("beginn") or time.time()), auftrag)
                if auftrag.get("ziel") and not self.ziel:
                    self.ziel = str(auftrag["ziel"])

    def _speichern(self) -> None:
        try:
            steuerung.json_schreiben(self.zustand_datei, {
                "ziel": self.ziel, "quellen": self.quellen, "verschieben": self.verschieben, "profil": self.profil,
            })
        except OSError:
            pass

    # -- Arbeitsprozess ----------------------------------------------------

    def lauf_lebt(self) -> bool:
        with self.sperre:
            if self.lauf is None:
                return False
            if self.lauf.prozess is not None:
                return self.lauf.prozess.poll() is None
            st = steuerung.json_lesen(self.status_datei) or {}
            if st.get("zustand") in ENDZUSTAENDE:
                return False
            frisch = time.time() - float(st.get("aktualisiert") or 0) < ABGESTUERZT_NACH
            return pid_lebt(self.lauf.pid) or frisch

    def _log_anfang(self, schritt: str) -> None:
        try:
            if self.log_datei.exists() and self.log_datei.stat().st_size > LOG_GRENZE:
                alt = self.log_datei.with_suffix(".alt.log")
                if alt.exists():
                    alt.unlink()
                self.log_datei.rename(alt)   # eigene Protokolldatei, kein Bild
        except OSError:
            pass
        with open(self.log_datei, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {schritt} ===\n")

    def log_ende(self, zeilen: int = 40) -> str:
        try:
            text = self.log_datei.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-zeilen:])

    def schritt_starten(self, schritt: str, **werte) -> dict:
        """Einen Schritt als eigenen Prozess starten. Nie zwei zugleich."""
        if schritt not in SCHRITTE:
            raise FotosortFehler(meldungen.arbeit_schritt_unbekannt(schritt))
        with self.sperre:
            if self.lauf_lebt():
                raise FotosortFehler(meldungen.ob_laeuft_schon(self.lauf.schritt if self.lauf else schritt))
            if not self.ziel:
                raise FotosortFehler(meldungen.ziel_fehlt())
            self.ordner.mkdir(parents=True, exist_ok=True)
            auftrag = {
                "schritt": schritt, "ziel": self.ziel, "config": self.config_pfad,
                "status_datei": str(self.status_datei), "steuer_datei": str(self.steuer_datei),
                **werte,
            }
            steuerung.json_schreiben(self.auftrag_datei, auftrag)
            steuerung.json_schreiben(self.steuer_datei, {"pause": False, "abbrechen": False, "zeit": time.time()})
            jetzt = time.time()
            steuerung.json_schreiben(self.status_datei, {
                "schritt": schritt, "zustand": ZUSTAND_STARTET, "pid": 0, "beginn": jetzt, "aktualisiert": jetzt,
                "dateien": 0, "gesamt": 0, "bytes": 0, "gesamt_bytes": 0, "bytes_pro_s": 0.0,
                "restzeit_s": None, "sekunden": 0.0, "lauf": None, "rc": None, "hinweis": "",
            })
            self._log_anfang(schritt)
            befehl = _kommando() + ["arbeit", "--auftrag", str(self.auftrag_datei)]
            with open(self.log_datei, "ab") as log:
                prozess = subprocess.Popen(
                    befehl, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    env=_umgebung(), cwd=str(self.ordner), **_losgeloest(),
                )
            self.lauf = Lauf(schritt, prozess, prozess.pid, jetzt, auftrag)
            self._speichern()
            return {"gestartet": schritt, "pid": prozess.pid}

    def lauf_status(self) -> dict:
        """Der Stand des laufenden oder zuletzt gelaufenen Schritts - aus der
        Statusdatei, nie aus der Datenbank."""
        with self.sperre:
            st = steuerung.json_lesen(self.status_datei) or {}
            if not st and self.lauf is None:
                return {"aktiv": False, "zustand": "", "schritt": ""}
            zustand = str(st.get("zustand") or ZUSTAND_STARTET)
            schritt = str(st.get("schritt") or (self.lauf.schritt if self.lauf else ""))
            lebt = self.lauf_lebt()
            if not lebt and zustand not in ENDZUSTAENDE:
                # Verschwunden, ohne sich abzumelden (Absturz, Stromausfall,
                # Task-Manager) - oder ein Prozess, den niemand mehr kennt.
                zustand = ZUSTAND_ABGESTUERZT
                st["zustand"] = zustand
                st["hinweis"] = meldungen.OB_ZUSTAND[ZUSTAND_ABGESTUERZT]
                st["aktualisiert"] = time.time()
                try:
                    steuerung.json_schreiben(self.status_datei, st)
                except OSError:
                    pass
            if zustand in ENDZUSTAENDE and self.lauf is not None:
                if self.lauf.prozess is not None:
                    try:
                        self.lauf.prozess.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                self.lauf = None
            gesamt_bytes = int(st.get("gesamt_bytes") or 0)
            bytes_ = int(st.get("bytes") or 0)
            gesamt = int(st.get("gesamt") or 0)
            dateien = int(st.get("dateien") or 0)
            if gesamt_bytes:
                anteil = min(1.0, bytes_ / gesamt_bytes)
            elif gesamt:
                anteil = min(1.0, dateien / gesamt)
            else:
                anteil = None
            rest = st.get("restzeit_s")
            ergebnis = {
                "aktiv": self.lauf is not None,
                "schritt": schritt,
                "schritt_name": self._schritt_name(schritt),
                "zustand": zustand,
                "zustand_text": meldungen.OB_ZUSTAND.get(zustand, zustand),
                "dateien": dateien, "gesamt": gesamt, "bytes": bytes_, "gesamt_bytes": gesamt_bytes,
                "anteil": anteil,
                "bytes_pro_s": float(st.get("bytes_pro_s") or 0.0),
                "restzeit_s": rest,
                "sekunden": float(st.get("sekunden") or 0.0),
                "rc": st.get("rc"),
                "hinweis": str(st.get("hinweis") or ""),
                "text": {
                    "dateien": meldungen.anzahl(dateien) + (f" von {meldungen.anzahl(gesamt)}" if gesamt else ""),
                    "bytes": meldungen.groesse(bytes_) + (f" von {meldungen.groesse(gesamt_bytes)}" if gesamt_bytes else ""),
                    "rate": (f"{float(st.get('bytes_pro_s') or 0.0) / (1024 * 1024):.1f}".replace(".", ",") + " MB/s")
                    if bytes_ else "",
                    "restzeit": meldungen.dauer(float(rest)) if rest is not None else "",
                    "dauer": meldungen.dauer(float(st.get("sekunden") or 0.0)),
                },
            }
            if zustand in (steuerung.ZUSTAND_FEHLER, ZUSTAND_ABGESTUERZT):
                ergebnis["log"] = self.log_ende()
            return ergebnis

    def _schritt_name(self, schritt: str) -> str:
        if schritt == "kopieren" and self.verschieben:
            return meldungen.SCHRITT_NAME["verschieben"]
        return meldungen.SCHRITT_NAME.get(schritt, schritt)

    def steuern(self, wunsch: str) -> dict:
        with self.sperre:
            if not self.lauf_lebt() or self.lauf is None:
                raise FotosortFehler(meldungen.ob_kein_lauf())
            if wunsch == "pause":
                steuerung.wunsch_schreiben(self.steuer_datei, pause=True)
            elif wunsch == "weiter":
                steuerung.wunsch_schreiben(self.steuer_datei, pause=False)
            elif wunsch == "abbrechen":
                steuerung.wunsch_schreiben(self.steuer_datei, abbrechen=True)
            elif wunsch == "sofort":
                steuerung.wunsch_schreiben(self.steuer_datei, abbrechen=True)
                if self.lauf.prozess is not None:
                    self.lauf.prozess.terminate()
                else:
                    prozess_beenden(self.lauf.pid)
                return {"ok": True, "text": meldungen.ob_abgebrochen_hart(self.lauf.schritt)}
            else:
                raise FotosortFehler(meldungen.ob_kein_lauf())
            return {"ok": True}

    # -- Archiv lesen (nur ohne laufenden Prozess) -------------------------

    def _namensraum(self, befehl: str = "fenster", **extra) -> argparse.Namespace:
        return argparse.Namespace(befehl=befehl, ziel=self.ziel, config=self.config_pfad, **extra)

    def _archiv_da(self) -> bool:
        return bool(self.ziel) and Path(self.ziel).exists() and db.archiv_id_vorhanden(Path(self.ziel))

    def _datenbank_frei(self) -> None:
        if self.lauf_lebt():
            raise FotosortFehler(meldungen.ob_datenbank_belegt())

    def archiv_lesen(self) -> dict:
        """Zaehler und Kennzahlen aus dem Archiv - wie der gefuehrte Modus, nur lesend."""
        with self.sperre:
            self._datenbank_frei()
            if not self._archiv_da():
                raise FotosortFehler(meldungen.ob_kein_archiv(self.ziel or "(kein Ziel)"))
            stille = _StilleKonsole()
            archiv = cli.archiv_oeffnen(self._namensraum(), stille, anlegen=False)
            d = archiv.datenbank
            try:
                zaehler = d.zaehler_je_status()
                loeschbar = d.zu_loeschen_summe()
                niedrigster = next((s for s in db.STUFEN if zaehler.get(s, 0) > 0), None)
                letzter = d.letzter_lauf()
                return {
                    "quellen": [str(z["wurzel"]) for z in d.quellen_liste()],
                    "zaehler": zaehler,
                    "profil": str(archiv.konf.wert("leistung.profil") or "hdd"),
                    "analyse": d.anzahl_zu_analysieren(),
                    "kopieren": d.zu_kopieren_summe(),
                    "pruefen": d.zu_pruefen_summe(),
                    "aufraeumen": (sum(n for n, _ in loeschbar.values()), sum(b for _, b in loeschbar.values())),
                    "loeschbar_je_quelle": {str(w): (n, b) for w, (n, b) in loeschbar.items()},
                    "modelle": [(m, o, n) for m, o, n in d.analyse_zusammenfassung()["modelle"] if m],
                    "konf_pfad": archiv.konf_pfad,
                    "phase": meldungen.ob_phase_kurz(niedrigster, sum(zaehler.values()) > 0),
                    "letzter_lauf": dict(letzter) if letzter is not None else None,
                    "hinweise": stille.zeilen,
                }
            finally:
                d.schliessen()

    @staticmethod
    def _naechster_aus(stand: dict) -> str:
        if stand["analyse"] > 0:
            return "analyse"
        if stand["kopieren"][0] > 0:
            return "kopieren"
        if stand["pruefen"][0] > 0:
            return "pruefen"
        if stand["aufraeumen"][0] > 0:
            return "aufraeumen"
        return "fertig"

    def archiv_info(self) -> dict:
        """Fuer die Startseite: Gibt es hier ein angefangenes Archiv, und wo steht es?"""
        if not self.ziel:
            return {"da": False}
        if not self._archiv_da():
            return {"da": False, "ziel_existiert": Path(self.ziel).exists()}
        if self.lauf_lebt():
            return {"da": True, "laeuft": True}
        try:
            stand = self.archiv_lesen()
        except FotosortFehler as fehler:
            return {"da": True, "fehler": str(fehler)}
        naechster = self._naechster_aus(stand)
        return {
            "da": True, "quellen": stand["quellen"], "phase": stand["phase"], "naechster": naechster,
            "naechster_name": self._schritt_name(naechster) if naechster != "fertig" else "",
            "profil": stand["profil"], "zaehler": stand["zaehler"],
        }

    def zustand(self) -> dict:
        return {
            "version": __version__,
            "ziel": self.ziel,
            "quellen_neu": list(self.quellen),
            "verschieben": self.verschieben,
            "profil": self.profil,
            "profile": [{"name": n, "text": t} for n, t in meldungen.OB_PROFILE],
            "fenster": self.fenster,
            "woerter": dict(meldungen.BESTAETIGUNGSWORT),
            "schritte": {s: self._schritt_name(s) for s in SCHRITTE},
            "erklaerungen": dict(meldungen.SCHRITT_ERKLAERUNG),
            "archiv": self.archiv_info(),
            "lauf": self.lauf_status(),
        }

    # -- Startseite --------------------------------------------------------

    def ziel_setzen(self, ziel: str) -> dict:
        with self.sperre:
            self.ziel = str(ziel or "").strip()
            self._speichern()
            return {"ziel": self.ziel, "archiv": self.archiv_info()}

    def einstellungen_setzen(self, verschieben: bool | None = None, profil: str | None = None) -> dict:
        with self.sperre:
            if verschieben is not None:
                self.verschieben = bool(verschieben)
            if profil is not None:
                if profil not in kopieren.PROFILE:
                    raise FotosortFehler(meldungen.profil_ungueltig(profil, sorted(kopieren.PROFILE)))
                self.profil = profil
            self._speichern()
            return {"verschieben": self.verschieben, "profil": self.profil}

    def _bekannte_quellen(self) -> list[str]:
        if not self._archiv_da() or self.lauf_lebt():
            return []
        try:
            return self.archiv_lesen()["quellen"]
        except FotosortFehler:
            return []

    def quelle_hinzufuegen(self, pfad: str) -> dict:
        pfad = str(pfad or "").strip()
        if not pfad:
            raise FotosortFehler(meldungen.ob_quelle_fehlt_pfad())
        with self.sperre:
            bekannt = self._bekannte_quellen()
            bekannt_auf = {pfade.aufloesen(Path(b)) for b in bekannt}
            ziel = Path(self.ziel) if self.ziel else Path(os.devnull)
            grund = cli._start_quelle_pruefen(pfad, ziel, bekannt_auf, self.quellen)
            if grund is not None:
                raise FotosortFehler(grund)
            self.quellen.append(pfad)
            self._speichern()
            return {"quellen_neu": list(self.quellen)}

    def quelle_entfernen(self, pfad: str) -> dict:
        with self.sperre:
            self.quellen = [q for q in self.quellen if q != pfad]
            self._speichern()
            return {"quellen_neu": list(self.quellen)}

    def los(self, ziel_anlegen: bool = False) -> dict:
        """Der grosse Knopf: Ziel pruefen, ExifTool pruefen, Scan starten."""
        with self.sperre:
            if self.lauf_lebt():
                raise FotosortFehler(meldungen.ob_laeuft_schon(self.lauf.schritt if self.lauf else ""))
            if not self.ziel:
                raise FotosortFehler(meldungen.ziel_fehlt())
            ziel = Path(self.ziel)
            archiv_da = self._archiv_da()
            bekannt = self._bekannte_quellen() if archiv_da else []
            if not bekannt and not self.quellen:
                raise FotosortFehler(meldungen.ob_quelle_noetig())
            if not ziel.exists():
                if not ziel.parent.is_dir():
                    raise FotosortFehler(meldungen.ziel_eltern_fehlt(ziel, ziel.parent))
                if not ziel_anlegen:
                    return {"frage": "ziel_anlegen", "text": meldungen.ob_frage_ziel_anlegen(ziel)}
            # Jede neue Quelle noch einmal pruefen - das Ziel kann sich geaendert haben.
            bekannt_auf = {pfade.aufloesen(Path(b)) for b in bekannt}
            geprueft: list[str] = []
            for q in self.quellen:
                grund = cli._start_quelle_pruefen(q, ziel, bekannt_auf, geprueft)
                if grund is not None:
                    raise FotosortFehler(grund)
                geprueft.append(q)
            # ExifTool zuerst (SPEC Abschnitt 2), mit der Konfiguration des Archivs.
            konf = config.Konfiguration()
            if archiv_da:
                try:
                    stille = _StilleKonsole()
                    archiv = cli.archiv_oeffnen(self._namensraum(), stille, anlegen=False)
                    archiv.datenbank.schliessen()
                    konf = archiv.konf
                except FotosortFehler:
                    raise
            gefunden, wo = cli.exiftool_finden(konf)
            if not gefunden or not cli.exiftool_startbar(gefunden):
                raise FotosortFehler(meldungen.exiftool_fehlt(wo))
            quellen_arg = (bekannt + geprueft) if geprueft else []
            ergebnis = self.schritt_starten("scan", quellen=quellen_arg, ziel_anlegen=bool(ziel_anlegen))
            self.quellen = []   # nach dem Scan sind sie bekannte Quellen des Archivs
            self._speichern()
            return ergebnis

    # -- der naechste Schritt -----------------------------------------------

    def naechster(self) -> dict:
        with self.sperre:
            stand = self.archiv_lesen()
            schritt = self._naechster_aus(stand)
            d: dict = {"schritt": schritt, "phase": stand["phase"], "zaehler": stand["zaehler"]}
            if schritt == "fertig":
                d["text"] = meldungen.ob_fertig_text()
                d["name"] = ""
                return d
            d["name"] = self._schritt_name(schritt)
            d["erklaerung"] = meldungen.SCHRITT_ERKLAERUNG["verschieben" if schritt == "kopieren" and self.verschieben else schritt]
            if schritt == "analyse":
                d["text"] = meldungen.ob_analyse_text(stand["analyse"])
            elif schritt == "kopieren":
                n, b = stand["kopieren"]
                d.update(n=n, bytes=b, verschieben=self.verschieben,
                         wort=meldungen.BESTAETIGUNGSWORT["papierkorb"] if self.verschieben else "",
                         text=meldungen.ob_kopieren_text(n, b, self.verschieben))
            elif schritt == "pruefen":
                n, b = stand["pruefen"]
                d.update(n=n, bytes=b, text=meldungen.ob_pruefen_text(n, b))
            elif schritt == "aufraeumen":
                d["plan"] = self._plan_aus(stand)
            return d

    def schritt(self, schritt: str, wort: str = "", weise: str = "", leere_ordner: bool = False, wort_ordner: str = "") -> dict:
        """Einen Folgeschritt starten - mit den Bestaetigungen, die der Kern verlangt."""
        with self.sperre:
            if schritt == "analyse":
                return self.schritt_starten("analyse")
            if schritt == "kopieren":
                if self.verschieben:
                    erwartet = meldungen.BESTAETIGUNGSWORT["papierkorb"]
                    if str(wort or "").strip().lower() != erwartet:
                        raise FotosortFehler(meldungen.ob_wort_falsch(erwartet))
                return self.schritt_starten("kopieren", verschieben=self.verschieben, profil=self.profil)
            if schritt == "pruefen":
                return self.schritt_starten("pruefen", profil=self.profil)
            if schritt == "aufraeumen":
                weise = weise or loeschen.WEISE_PAPIERKORB
                if weise not in (loeschen.WEISE_PAPIERKORB, loeschen.WEISE_ENDGUELTIG):
                    weise = loeschen.WEISE_PAPIERKORB
                wort = str(wort or "").strip().lower()
                wort_ordner = str(wort_ordner or "").strip().lower()
                if wort and wort != meldungen.BESTAETIGUNGSWORT[weise]:
                    raise FotosortFehler(meldungen.ob_wort_falsch(meldungen.BESTAETIGUNGSWORT[weise]))
                if leere_ordner and wort_ordner != meldungen.BESTAETIGUNGSWORT["ordner"]:
                    raise FotosortFehler(meldungen.ob_wort_falsch(meldungen.BESTAETIGUNGSWORT["ordner"]))
                if not wort and not leere_ordner:
                    raise FotosortFehler(meldungen.ob_nichts_ausgewaehlt())
                return self.schritt_starten(
                    "aufraeumen", weise=weise, leere_ordner=bool(leere_ordner), profil=self.profil,
                    bestaetigung={"dateien": wort, "ordner": wort_ordner if leere_ordner else ""},
                )
            raise FotosortFehler(meldungen.arbeit_schritt_unbekannt(schritt))

    def _plan_aus(self, stand: dict) -> dict:
        je_quelle = [
            {"wurzel": w, "n": n, "bytes": b, "n_text": meldungen.anzahl(n), "groesse": meldungen.groesse(b)}
            for w, (n, b) in sorted(stand["loeschbar_je_quelle"].items())
        ]
        n, b = stand["aufraeumen"]
        return {
            "je_quelle": je_quelle, "n": n, "bytes": b, "n_text": meldungen.anzahl(n), "groesse": meldungen.groesse(b),
            "quellen": stand["quellen"],
            "woerter": dict(meldungen.BESTAETIGUNGSWORT),
        }

    def aufraeumen_plan(self) -> dict:
        with self.sperre:
            return self._plan_aus(self.archiv_lesen())

    # -- Zusammenfassungen -------------------------------------------------

    def zusammenfassung(self, schritt: str) -> dict:
        """Nach einem Schritt: einfache Zeilen (Bezeichnung, Wert) aus der Datenbank."""
        with self.sperre:
            self._datenbank_frei()
            if not self._archiv_da():
                raise FotosortFehler(meldungen.ob_kein_archiv(self.ziel or "(kein Ziel)"))
            stille = _StilleKonsole()
            archiv = cli.archiv_oeffnen(self._namensraum(), stille, anlegen=False)
            d = archiv.datenbank
            try:
                lauf = d.letzter_lauf()
                lauf_nr = int(lauf["nummer"]) if lauf is not None else 0
                zahlen = {}
                if lauf is not None:
                    zeile = d.lauf_zeile(lauf_nr)
                    if zeile is not None and zeile["zusammenfassung"]:
                        try:
                            zahlen = json.loads(zeile["zusammenfassung"])
                        except ValueError:
                            zahlen = {}
                zaehler = d.zaehler_je_status()
                zeilen: list[list[str]] = []
                extra: dict = {}

                def ereignis(art: str) -> int:
                    return d.ereignisse_zaehlen(lauf_nr, art) if lauf_nr else 0

                if schritt == "scan":
                    je_quelle = d.zaehler_je_quelle()
                    echte_gesamt = 0
                    quellen = []
                    for wurzel in sorted(je_quelle):
                        e = je_quelle[wurzel]
                        echte = sum(e.get(t, 0) for t in ("foto", "raw", "video", "sidecar"))
                        echte_gesamt += echte
                        quellen.append({
                            "wurzel": wurzel, "gesamt": e["gesamt"], "echte": echte, "groesse": meldungen.groesse(e["bytes"]),
                            "foto": e.get("foto", 0), "raw": e.get("raw", 0), "video": e.get("video", 0),
                            "sidecar": e.get("sidecar", 0), "sonstiges": e["gesamt"] - echte,
                        })
                    extra["quellen"] = quellen
                    zeilen.append(["Fotos, RAW-Dateien, Videos und Begleitdateien gefunden", meldungen.anzahl(echte_gesamt)])
                    zeilen.append(["Davon neu, noch nicht analysiert", meldungen.anzahl(zaehler.get("gefunden", 0))])
                    zeilen.append(["Andere Dateien (werden nicht angefasst)", meldungen.anzahl(sum(q["sonstiges"] for q in quellen))])
                    zeilen.append(["Datenmenge insgesamt", meldungen.groesse(d.gesamtgroesse())])
                    for art, text in (
                        ("quelle_nicht_erreichbar", "Quellordner nicht erreichbar"),
                        ("quelle_nicht_mehr_vorhanden", "Dateien seit dem letzten Mal aus der Quelle verschwunden"),
                        ("ordner_nicht_lesbar", "Ordner, die nicht gelesen werden konnten"),
                        ("ausgeschlossen", "Dateien durch Ausschlussmuster übersprungen"),
                        ("quelle_veraendert", "Dateien, die sich seit dem letzten Mal geändert haben"),
                    ):
                        n = ereignis(art)
                        if n:
                            zeilen.append([text, meldungen.anzahl(n)])
                elif schritt == "analyse":
                    a = d.analyse_zusammenfassung()
                    je_jahr: dict[str, int] = {}
                    for _w, jahre in a["je_jahr_quelle"].items():
                        for jahr, n in jahre.items():
                            je_jahr[jahr] = je_jahr.get(jahr, 0) + n
                    extra["je_jahr"] = [{"jahr": j, "n": n, "n_text": meldungen.anzahl(n)} for j, n in sorted(je_jahr.items())]
                    extra["modelle"] = [
                        {"modell": m, "ordner": o, "n": n, "n_text": meldungen.anzahl(n)}
                        for m, o, n in a["modelle"] if m
                    ]
                    extra["ohne_modell"] = sum(n for m, _o, n in a["modelle"] if not m)
                    zeilen.append(["Analysierte Dateien", meldungen.anzahl(a["analysiert"])])
                    zeilen.append(["Ohne sicheres Aufnahmedatum (landen im Ordner „_Ohne_Datum“ oder nach Änderungsdatum)", meldungen.anzahl(a["unsicher"])])
                    if a["zeitzone_angenommen"]:
                        zeilen.append(["Videos, bei denen die Zeitzone angenommen wurde", meldungen.anzahl(a["zeitzone_angenommen"])])
                    if a["sidecar_ohne_haupt"]:
                        zeilen.append(["Begleitdateien ohne zugehöriges Foto (übersprungen)", meldungen.anzahl(a["sidecar_ohne_haupt"])])
                    if a["namenskonflikte"]:
                        zeilen.append(["Gleiche Dateinamen im selben Zielordner (bekommen beim Kopieren einen Anhang)", meldungen.anzahl(a["namenskonflikte"])])
                    if a["moegliche_duplikate"]:
                        zeilen.append(["Möglicherweise doppelte Dateien (wird beim Kopieren sicher geprüft)", meldungen.anzahl(a["moegliche_duplikate"])])
                    zeilen.append(["Fehler (nicht lesbare Dateien)", meldungen.anzahl(a["fehler"])])
                    if a["offen"]:
                        zeilen.append(["Noch nicht analysiert", meldungen.anzahl(a["offen"])])
                elif schritt == "kopieren":
                    k = d.kopier_zusammenfassung()
                    s = k["status"]
                    titel = "Verschoben" if self.verschieben else "Kopiert"
                    zeilen.append([f"{titel} in diesem Durchgang", meldungen.anzahl(int(zahlen.get("dateien", 0)))])
                    zeilen.append(["Datenmenge in diesem Durchgang", meldungen.groesse(int(zahlen.get("bytes", 0)))])
                    zeilen.append(["Im Archiv (kopiert, noch nicht geprüft)", meldungen.anzahl(s.get("kopiert", 0))])
                    if s.get("verschoben", 0):
                        zeilen.append(["Verschoben (auf demselben Laufwerk, Prüfung folgt)", meldungen.anzahl(s.get("verschoben", 0))])
                    zeilen.append(["Doppelte Dateien (war inhaltsgleich schon im Archiv, nicht kopiert)", meldungen.anzahl(s.get("duplikat", 0) + s.get("duplikat_bestaetigt", 0))])
                    n = ereignis("namenskonflikt")
                    if n:
                        zeilen.append(["Gleicher Name, anderer Inhalt: mit Anhang _1, _2 … abgelegt", meldungen.anzahl(n)])
                    zeilen.append(["Fehler", meldungen.anzahl(s.get("fehler", 0))])
                    if s.get("analysiert", 0):
                        zeilen.append(["Noch nicht kopiert", meldungen.anzahl(s.get("analysiert", 0))])
                    if s.get("kopieren_laeuft", 0):
                        zeilen.append(["Unterbrochen (wird beim nächsten Mal fortgesetzt)", meldungen.anzahl(s.get("kopieren_laeuft", 0))])
                elif schritt == "pruefen":
                    zeilen.append(["Geprüft in diesem Durchgang", meldungen.anzahl(int(zahlen.get("dateien", 0)))])
                    zeilen.append(["Gelesene Datenmenge", meldungen.groesse(int(zahlen.get("bytes", 0)))])
                    zeilen.append(["Geprüft und in Ordnung (Kopie stimmt mit der Quelle überein)", meldungen.anzahl(zaehler.get("geprueft", 0))])
                    zeilen.append(["Doppelte Dateien bestätigt", meldungen.anzahl(zaehler.get("duplikat_bestaetigt", 0))])
                    n = ereignis("pruefung_fehlgeschlagen")
                    zeilen.append(["Prüfung fehlgeschlagen (Datei wird beim nächsten Mal neu kopiert)", meldungen.anzahl(n)])
                    if zaehler.get("kopiert", 0):
                        zeilen.append(["Noch nicht geprüft", meldungen.anzahl(zaehler.get("kopiert", 0))])
                elif schritt == "aufraeumen":
                    zeilen.append(["Aus der Quelle entfernt in diesem Durchgang", meldungen.anzahl(int(zahlen.get("dateien", 0)))])
                    zeilen.append(["Insgesamt aus der Quelle entfernt", meldungen.anzahl(zaehler.get("quelle_geloescht", 0))])
                    n = ereignis("quelle_in_geloescht_ordner")
                    if n:
                        zeilen.append(["Davon in den Ordner _geloescht_… verschoben", meldungen.anzahl(n)])
                    n = ereignis("leerer_ordner_entfernt")
                    if n:
                        zeilen.append(["Leere Ordner entfernt", meldungen.anzahl(n)])
                    n = ereignis("loeschung_verweigert")
                    if n:
                        zeilen.append(["Löschung verweigert (Quelle und Archiv stimmen nicht überein)", meldungen.anzahl(n)])
                    n = ereignis("quelle_seit_kopieren_geaendert")
                    if n:
                        zeilen.append(["Quelle hat sich seit dem Kopieren geändert (wird neu kopiert)", meldungen.anzahl(n)])
                    if zaehler.get("geprueft", 0):
                        zeilen.append(["Noch in der Quelle (geprüft, nicht entfernt)", meldungen.anzahl(zaehler.get("geprueft", 0))])
                else:
                    raise FotosortFehler(meldungen.arbeit_schritt_unbekannt(schritt))
                sek = float(zahlen.get("sekunden", 0) or 0)
                if sek:
                    zeilen.append(["Dauer", meldungen.dauer(sek)])
                    b = int(zahlen.get("bytes", 0) or 0)
                    if b and sek > 0:
                        zeilen.append(["Geschwindigkeit", f"{b / sek / (1024 * 1024):.1f}".replace(".", ",") + " MB/s"])
                niedrigster = next((s for s in db.STUFEN if zaehler.get(s, 0) > 0), None)
                return {
                    "schritt": schritt, "name": self._schritt_name(schritt), "zeilen": zeilen,
                    "fehler": zaehler.get("fehler", 0),
                    "duplikate": zaehler.get("duplikat", 0) + zaehler.get("duplikat_bestaetigt", 0),
                    "phase": meldungen.ob_phase_kurz(niedrigster, sum(zaehler.values()) > 0),
                    "zaehler": zaehler, **extra,
                }
            finally:
                d.schliessen()

    # -- Aliase --------------------------------------------------------------

    def aliase_setzen(self, aliase: dict) -> dict:
        """Ordnernamen je Kameramodell speichern und die Analyse erneut starten."""
        with self.sperre:
            stand = self.archiv_lesen()
            aktuell = {m: o for m, o, _n in stand["modelle"]}
            neue = {
                str(m): str(n).strip() for m, n in (aliase or {}).items()
                if str(n).strip() and str(m) in aktuell and str(n).strip() != aktuell[str(m)]
            }
            if not neue:
                return {"geaendert": 0, "text": meldungen.ob_keine_aliase()}
            config.aliase_ergaenzen(stand["konf_pfad"], neue)
            stille = _StilleKonsole()
            archiv = cli.archiv_oeffnen(self._namensraum(), stille, anlegen=False, sperren=True)
            try:
                zurueck = archiv.datenbank.analyse_zuruecksetzen_nach_modell(list(neue))
            finally:
                archiv.datenbank.schliessen()
            ergebnis = self.schritt_starten("analyse")
            ergebnis.update(geaendert=len(neue), zurueck=zurueck, text=meldungen.ob_aliase_geschrieben(len(neue), zurueck))
            return ergebnis

    # -- Listen (seitenweise) --------------------------------------------------

    def liste(self, art: str, seite: int = 1) -> dict:
        if art not in LISTEN:
            raise FotosortFehler(meldungen.ob_liste_unbekannt(art))
        with self.sperre:
            self._datenbank_frei()
            if not self._archiv_da():
                raise FotosortFehler(meldungen.ob_kein_archiv(self.ziel or "(kein Ziel)"))
            stille = _StilleKonsole()
            archiv = cli.archiv_oeffnen(self._namensraum(), stille, anlegen=False)
            try:
                bedingung, werte = LISTEN[art]
                zeilen, gesamt = archiv.datenbank.dateien_seite(bedingung, werte, seite, SEITENGROESSE)
            finally:
                archiv.datenbank.schliessen()
            seiten = max(1, (gesamt + SEITENGROESSE - 1) // SEITENGROESSE)
            seite = max(1, min(int(seite), seiten))
            return {
                "art": art, "seite": seite, "seiten": seiten, "gesamt": gesamt, "gesamt_text": meldungen.anzahl(gesamt),
                "zeilen": [self._listenzeile(art, z) for z in zeilen],
            }

    @staticmethod
    def _listenzeile(art: str, z) -> dict:
        d = {
            "quellpfad": str(db.text_pfad(z["quellpfad"])), "groesse": meldungen.groesse(int(z["groesse"])),
            "status": z["status"], "dateityp": z["dateityp"],
        }
        if art == "fehler":
            d["grund"] = z["fehlergrund"]
        elif art == "duplikate":
            d["partner"] = str(db.text_pfad(z["zielpfad"]))
        else:
            d["zielpfad"] = str(db.text_pfad(z["zielpfad"]))
            d["aufnahme_zeit"] = z["aufnahme_zeit"]
        return d

    # -- Bericht und Einstellungen ---------------------------------------------

    def bericht_oeffnen(self) -> dict:
        with self.sperre:
            self._datenbank_frei()
            if not self._archiv_da():
                raise FotosortFehler(meldungen.ob_kein_archiv(self.ziel or "(kein Ziel)"))
            stille = _StilleKonsole()
            archiv = cli.archiv_oeffnen(self._namensraum(), stille, anlegen=False)
            try:
                txt, _csv_d, _csv_e = bericht.schreiben(archiv.ziel, archiv.datenbank)
            finally:
                archiv.datenbank.schliessen()
            geoeffnet = cli._editor_oeffnen(txt)
            return {"pfad": str(txt), "geoeffnet": geoeffnet, "text": meldungen.ob_bericht(txt, geoeffnet)}

    def einstellungen_oeffnen(self) -> dict:
        with self.sperre:
            if self.config_pfad:
                pfad = Path(self.config_pfad)
            else:
                pfad = self.archiv_lesen()["konf_pfad"]
            geoeffnet = cli._editor_oeffnen(Path(pfad))
            return {"pfad": str(pfad), "geoeffnet": geoeffnet, "text": meldungen.ob_einstellungen(pfad, geoeffnet)}
