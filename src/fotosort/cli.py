"""Kommandozeile: argparse, keine CLI-Bibliothek (docs/architektur.md Abs. 3).

In Phase 1 tun nur scan, status und config etwas. Alle uebrigen Unterbefehle
aus SPEC Abschnitt 8 gibt es bereits; sie melden freundlich, in welcher Phase
sie kommen, und beenden sich mit einem von Null verschiedenen Rueckgabewert.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import analyse, aufraeumen, bericht, kopieren, loeschen, messen, metadaten, pruefen, prozesse, steuerung, FotosortFehler, config, db, meldungen, pfade, scan

# Rueckgabewerte
OK = 0
FEHLER = 1
FEHLENDE_ANGABE = 2
SPAETERE_PHASE = 3
ABGEBROCHEN = 130

# Befehle, die Metadaten brauchen: ohne ExifTool harter Abbruch (SPEC Abs. 2).
BRAUCHT_EXIFTOOL = frozenset({"analyse", "start"})

# In welcher Phase ein noch nicht gebauter Befehl kommt (docs/PROMPTS.md,
# Prompt 2 bis 6). "ziel-index" und "wiederherstellen" nennt kein Prompt
# ausdruecklich; sie gehoeren zum Ziel-Index und zur Sicherungskopie und
# damit zum Kopieren (Phase 3). Das ist noch zu bestaetigen.
PHASE_JE_BEFEHL: dict[str, int] = {
    "analyse": 2,
    "kopieren": 3,
    "ziel-index": 3,
    "wiederherstellen": 3,
    "pruefen": 4,
    "bericht": 4,
    "aufraeumen": 5,
}

# ------------------------------------------------------------- ExifTool ----


def exiftool_finden(konf=None) -> tuple[str | None, str]:
    """(Pfad oder None, wo gesucht wurde). Vorrang nach SPEC Abschnitt 2."""
    aus_umgebung = os.environ.get("FOTOSORT_EXIFTOOL", "").strip()
    if aus_umgebung:
        gefunden = shutil.which(aus_umgebung) or (
            aus_umgebung if Path(aus_umgebung).is_file() else None
        )
        return gefunden, f"{aus_umgebung} (FOTOSORT_EXIFTOOL)"
    if konf is not None:
        aus_konf = str(konf.wert("leistung.exiftool_pfad")).strip()
        if aus_konf:
            gefunden = shutil.which(aus_konf) or (
                aus_konf if Path(aus_konf).is_file() else None
            )
            return gefunden, f"{aus_konf} (exiftool_pfad)"
    mitgeliefert = exiftool_mitgeliefert()
    if mitgeliefert is not None:
        return str(mitgeliefert), f"{mitgeliefert} (im Programmordner mitgeliefert)"
    return shutil.which("exiftool"), "exiftool ueber PATH"


def programmordner() -> Path | None:
    """Der Ordner des gepackten Programms (PyInstaller-Ordnervariante), sonst None."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def exiftool_mitgeliefert() -> Path | None:
    """Das im Windows-Paket mitgelieferte ExifTool: <Programmordner>/exiftool/exiftool.exe
    (daneben liegt der Ordner exiftool_files mit den Perl-Bibliotheken)."""
    ordner = programmordner()
    if ordner is None:
        return None
    for name in ("exiftool.exe", "exiftool"):
        kandidat = ordner / "exiftool" / name
        if kandidat.is_file():
            return kandidat
    return None


class _Version(argparse.Action):
    """--version: Programmversion und das gefundene ExifTool, dann Ende."""

    def __init__(self, option_strings, dest, **kw):
        super().__init__(option_strings, dest, nargs=0, help="Version anzeigen und beenden")

    def __call__(self, parser, namespace, values, option_string=None):
        from . import __version__
        gefunden, wo = exiftool_finden(config.Konfiguration())
        exif = "nicht gefunden"
        if gefunden:
            try:
                aus = subprocess.run([gefunden, "-ver"], capture_output=True, text=True, timeout=30,
                                     **prozesse.unsichtbar())
                exif = f"{aus.stdout.strip() or '?'} ({wo})" if aus.returncode == 0 else f"nicht startbar ({wo})"
            except (OSError, subprocess.SubprocessError):
                exif = f"nicht startbar ({wo})"
        print(f"fotosort {__version__}")
        print(f"ExifTool {exif}")
        parser.exit(0)


# ExifTool-Pfade, die in diesem Programmlauf schon einmal erfolgreich
# gestartet wurden (der gefuehrte Modus oeffnet das Archiv mehrmals).
_exiftool_startbar_gemerkt: set[str] = set()


def exiftool_pruefen(befehl: str, konf, konsole) -> None:
    """Bei jedem Start pruefen, ob ExifTool da und startbar ist.

    Vorrang nach SPEC Abschnitt 2: FOTOSORT_EXIFTOOL, dann der
    Konfigurationswert exiftool_pfad, dann PATH. Harter Abbruch nur bei den
    Befehlen, die Metadaten brauchen.
    """
    gefunden, wo = exiftool_finden(konf)
    if gefunden and (gefunden in _exiftool_startbar_gemerkt or exiftool_startbar(gefunden)):
        _exiftool_startbar_gemerkt.add(gefunden)   # je Programmlauf nur einmal starten
        return
    if befehl in BRAUCHT_EXIFTOOL:
        raise FotosortFehler(meldungen.exiftool_fehlt(wo))
    konsole.print(meldungen.exiftool_hinweis(wo))


def exiftool_startbar(pfad: str) -> bool:
    try:
        fertig = subprocess.run(
            [pfad, "-ver"], capture_output=True, timeout=20, check=False, **prozesse.unsichtbar()
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return fertig.returncode == 0


# ---------------------------------------------------------------- Archiv ----


@dataclass
class Archiv:
    ziel: Path
    archiv_id: str
    ordner: Path
    konf: config.Konfiguration
    konf_pfad: Path
    datenbank: db.Datenbank
    neu_angelegt: bool


def _konf_pfad_bestimmen(args, ordner: Path) -> tuple[Path, bool]:
    """(Pfad der Konfiguration, ob sie von aussen angegeben wurde)."""
    if getattr(args, "config", None):
        return Path(args.config), True
    return ordner / config.DATEINAME, False


def archiv_oeffnen(args, konsole, anlegen: bool, sperren: bool = False) -> Archiv:
    """Archiv-Kennung, Archiv-Ordner, Konfiguration und Datenbank bereitstellen.

    "anlegen" ist nur beim Scan wahr: Nur er darf ein Archiv neu anlegen.
    Ein nicht vorhandener Zielordner wird auch dann nicht von selbst
    angelegt, sondern nur auf ausdrueckliche Ansage (--ziel-anlegen).

    "sperren" belegt das Archiv fuer diesen Lauf. Das tun nur Befehle, die
    etwas veraendern; "status" und "config" duerfen auch waehrend eines
    laufenden Scans jederzeit hineinschauen.
    """
    ziel = Path(args.ziel)
    if not ziel.exists():
        if not anlegen:
            raise FotosortFehler(meldungen.ziel_existiert_nicht(ziel))
        if not getattr(args, "ziel_anlegen", False):
            raise FotosortFehler(meldungen.ziel_wird_nicht_angelegt(ziel))
        if not ziel.parent.is_dir():
            raise FotosortFehler(meldungen.ziel_eltern_fehlt(ziel, ziel.parent))
        ziel.mkdir(parents=True, exist_ok=True)
        konsole.print(meldungen.ziel_angelegt(ziel))

    id_war_da = db.archiv_id_vorhanden(ziel)
    if not id_war_da and not anlegen:
        raise FotosortFehler(meldungen.archiv_id_fehlt(ziel))
    archiv_id = db.archiv_id_lesen_oder_anlegen(ziel)
    if not id_war_da:
        konsole.print(meldungen.archiv_id_angelegt(archiv_id, db.archiv_id_datei(ziel)))

    # Der Konfigurationswert datenbank_ort wirkt nur aus einer mit --config
    # angegebenen Datei (SPEC Abschnitt 6).
    von_aussen = bool(getattr(args, "config", None))
    aeussere = config.laden(Path(args.config)) if von_aussen else None
    ordner = db.archiv_ordner(archiv_id, aeussere)

    konf_pfad, _ = _konf_pfad_bestimmen(args, ordner)

    if pfade.ist_netzpfad(ordner):
        raise FotosortFehler(
            meldungen.datenbank_auf_netzlaufwerk(ordner, pfade.dateisystem_typ(ordner))
        )

    # Konfiguration: eine vorhandene wird nie umgeschrieben.
    if not von_aussen and not konf_pfad.exists():
        if config.aus_ziel_uebernehmen(ziel, konf_pfad):
            konsole.print(meldungen.config_aus_ziel_uebernommen(konf_pfad))
        elif anlegen:
            config.erzeugen(konf_pfad)
            konsole.print(meldungen.config_erzeugt(konf_pfad))

    konf = config.laden(konf_pfad)
    if konf.unbekannte:
        konsole.print(meldungen.config_unbekannte_werte(konf.unbekannte, konf_pfad))
    if (
        not von_aussen
        and konf.aus_datei
        and str(konf.wert("datenbank.datenbank_ort")).strip()
    ):
        konsole.print(meldungen.config_datenbank_ort_ignoriert(konf_pfad))

    # Fehlende lokale Datenbank (SPEC Abschnitt 6).
    datenbank_da = db.datenbank_pfad(ordner).is_file()
    if not datenbank_da and id_war_da:
        if db.sicherung_pfad(ziel).is_file():
            raise FotosortFehler(meldungen.datenbank_fehlt_sicherung_da(ziel))
        raise FotosortFehler(meldungen.datenbank_fehlt_keine_sicherung(ziel))

    # Erst hier steht die geltende Konfiguration fest. Deshalb wird die
    # ExifTool-Pruefung (SPEC Abschnitt 2) auch erst jetzt gemacht: Sonst
    # haette die mittlere Stufe der Vorrangfolge - der Konfigurationswert
    # exiftool_pfad - ueberhaupt keine Wirkung.
    exiftool_pruefen(getattr(args, "befehl", ""), konf, konsole)

    datenbank = db.Datenbank.oeffnen(ordner, sperren=sperren)
    return Archiv(
        ziel=ziel,
        archiv_id=archiv_id,
        ordner=ordner,
        konf=konf,
        konf_pfad=konf_pfad,
        datenbank=datenbank,
        neu_angelegt=not id_war_da,
    )


# --------------------------------------------------------------- Befehle ----


def befehl_scan(args, konsole) -> int:
    gewuenscht = [Path(q) for q in (args.quelle or [])]
    ziel = Path(args.ziel)
    archiv_da = ziel.exists() and db.archiv_id_vorhanden(ziel)

    if not gewuenscht and not archiv_da:
        konsole.print(meldungen.keine_quellen_bekannt())
        return FEHLENDE_ANGABE

    # Vorpruefung ohne Archiv: Kann keine der genannten Quellen durchlaufen
    # werden, soll kein halbes Archiv entstehen (SPEC Abschnitt 4 Phase 1).
    # Die Gruende nennt spaeter ausfuehren_mehrere je Quelle; hier faellt
    # nur die Entscheidung, ob das Archiv ueberhaupt angelegt wird.
    if gewuenscht and not archiv_da:
        brauchbar = [
            q for q in gewuenscht
            if q.is_dir() and pfade.lage_pruefen(q, ziel) not in ("gleich", "quelle_in_ziel")
        ]
        if not brauchbar:
            for q in gewuenscht:
                if not q.is_dir():
                    konsole.print(meldungen.quelle_existiert_nicht(q))
                elif pfade.lage_pruefen(q, ziel) == "gleich":
                    konsole.print(meldungen.quelle_gleich_ziel(pfade.aufloesen(q)))
                else:
                    konsole.print(meldungen.quelle_in_ziel(pfade.aufloesen(q)))
            return FEHLER

    archiv = archiv_oeffnen(args, konsole, anlegen=True, sperren=True)
    datenbank = archiv.datenbank
    lauf = datenbank.lauf_beginnen(_befehlszeile())
    try:
        quellen, _bekannt = scan.quellen_bestimmen(gewuenscht, datenbank)
        if not quellen:
            konsole.print(meldungen.keine_quellen_bekannt())
            _lauf_sauber_abbrechen(datenbank, lauf)
            return FEHLENDE_ANGABE

        konsole.print(meldungen.scan_quellen_beginnt([pfade.aufloesen(q) for q in quellen], archiv.ziel))
        try:
            gesamt = scan.ausfuehren_mehrere(
                quellen, archiv.ziel, archiv.konf, datenbank, lauf, konsole
            )
        except FotosortFehler:
            _lauf_sauber_abbrechen(datenbank, lauf)
            raise

        if not gesamt.je_quelle:
            konsole.print(meldungen.scan_nichts_zu_tun(gesamt.abgelehnt, gesamt.nicht_erreichbar))
            _lauf_sauber_abbrechen(datenbank, lauf)
            return FEHLER

        ergebnis = gesamt.gesamt
        text = meldungen.scan_neue_quellen(gesamt.neue_quellen)
        if text:
            konsole.print(text)
        text = meldungen.scan_laufwerke(gesamt.laufwerke, len(gesamt.je_quelle))
        if text:
            konsole.print(text)
        konsole.print(
            meldungen.scan_ergebnis(
                ergebnis.dateien, ergebnis.bytes_gesamt, ergebnis.je_typ, gesamt.sekunden
            )
        )
        konsole.print(
            meldungen.scan_besonderheiten(
                ergebnis.neu,
                ergebnis.unveraendert,
                ergebnis.veraendert,
                ergebnis.verschwunden,
                ergebnis.ausgeschlossen,
                ergebnis.verknuepfungen,
                ergebnis.ins_ziel,
                ergebnis.fehler,
                ergebnis.ordner_nicht_lesbar,
                ergebnis.verschwunden_ausgewertet,
            )
        )
        text = meldungen.scan_je_quelle(gesamt.je_quelle)
        if text:
            konsole.print("")
            konsole.print(text)
        if ergebnis.ordner_nicht_lesbar:
            konsole.print(
                meldungen.scan_ordner_nicht_lesbar(
                    ergebnis.ordner_nicht_lesbar, ergebnis.nicht_lesbare_ordner
                )
            )
        if ergebnis.alles_ausgeschlossen:
            konsole.print("")
            konsole.print(
                meldungen.scan_alles_ausgeschlossen(
                    archiv.konf.wert("quelle.ausschlussmuster")
                )
            )
        if gesamt.abgebrochen:
            konsole.print("")
            konsole.print(meldungen.scan_abgebrochen())
            return ABGEBROCHEN
        _abschliessen(archiv, konsole, lauf, {
            "dateien": ergebnis.dateien, "bytes": ergebnis.bytes_gesamt, "sekunden": ergebnis.sekunden,
        })
        # Nicht alles gesehen - nicht lesbarer Ordner, nicht erreichbare
        # oder abgelehnte Quelle - ist ein Fehler, auch wenn der Rest lief.
        unvollstaendig = (
            ergebnis.ordner_nicht_lesbar or gesamt.nicht_erreichbar or gesamt.abgelehnt
        )
        return FEHLER if unvollstaendig else OK
    finally:
        datenbank.schliessen()

def _abschliessen(archiv, konsole, lauf: int, zusammenfassung: dict | None = None) -> None:
    """Nach jeder abgeschlossenen Phase: Lauf beenden, Sicherungskopie und
    Bericht ins Ziel (SPEC Abschnitt 6 und 10)."""
    datenbank = archiv.datenbank
    datenbank.lauf_beenden(lauf, zusammenfassung)
    datenbank.sichern_nach(archiv.ziel, archiv.konf_pfad)
    konsole.print("")
    konsole.print(meldungen.datenbank_gesichert(db.sicherung_pfad(archiv.ziel)))
    txt, csv_d, csv_e = bericht.schreiben(archiv.ziel, datenbank, lauf)
    konsole.print(meldungen.bericht_geschrieben(txt, csv_d, csv_e))


def _lauf_sauber_abbrechen(datenbank, lauf: int) -> None:
    """Den Lauf mit Ende und Vermerk schliessen (geordneter Abbruch)."""
    try:
        datenbank.ereignis(lauf, scan.ART_ABGEBROCHEN, "", 1, "sauber abgebrochen")
        datenbank.lauf_beenden(lauf)
    except sqlite3.Error:  # pragma: no cover - der Abbruch bleibt wichtiger
        pass


def befehl_status(args, konsole) -> int:
    archiv = archiv_oeffnen(args, konsole, anlegen=False)
    datenbank = archiv.datenbank
    try:
        zaehler = datenbank.zaehler_je_status()
        konsole.print(meldungen.status_zaehler(zaehler))
        niedrigster = None
        for stufe in db.STUFEN:
            if zaehler.get(stufe, 0) > 0:
                niedrigster = stufe
                break
        konsole.print("")
        konsole.print(
            meldungen.status_phase(niedrigster, dateien_erfasst=sum(zaehler.values()) > 0)
        )
        konsole.print("")
        konsole.print(
            meldungen.status_je_quelle(
                datenbank.quellen_liste(),
                datenbank.zaehler_je_quelle(),
                datenbank.zaehler_je_status_und_quelle(),
            )
        )
        zeile = datenbank.letzter_lauf()
        konsole.print("")
        if zeile is None:
            konsole.print(meldungen.status_letzter_lauf(None, "", "", ""))
        else:
            konsole.print(
                meldungen.status_letzter_lauf(
                    zeile["nummer"], zeile["befehl"], zeile["start"], zeile["ende"]
                )
            )
        return OK
    finally:
        datenbank.schliessen()


def befehl_config(args, konsole) -> int:
    # Mit --nur-pfad gehen alle Hinweise auf die Fehlerausgabe: Auf der
    # Standardausgabe steht dann genau eine Zeile, der Pfad, damit sich der
    # Schalter in eigenen Skripten weiterverwenden laesst (SPEC Abschnitt 8).
    hinweise = _konsole(fehlerausgabe=True) if args.nur_pfad else konsole
    archiv = archiv_oeffnen(args, hinweise, anlegen=False)
    archiv.datenbank.schliessen()
    if args.nur_pfad:
        print(archiv.konf_pfad)
        return OK
    konsole.print(meldungen.config_pfad_zeigen(archiv.konf_pfad))
    if not _editor_oeffnen(archiv.konf_pfad):
        konsole.print(meldungen.editor_nicht_gefunden(archiv.konf_pfad))
        return OK
    konsole.print(meldungen.config_wird_geoeffnet(archiv.konf_pfad))
    return OK


def _editor_oeffnen(pfad: Path) -> bool:
    if not pfad.exists():
        return False
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        try:
            os.startfile(str(pfad))  # type: ignore[attr-defined]
            return True
        except OSError:
            return False
    programm = shutil.which("xdg-open")
    if not programm:
        return False
    try:
        subprocess.Popen(
            [programm, str(pfad)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:  # pragma: no cover
        return False
    return True


def befehl_analyse(args, konsole) -> int:
    """Phase 2: Metadaten lesen, Ziel berechnen (SPEC Abschnitt 4 Phase 2)."""
    archiv = archiv_oeffnen(args, konsole, anlegen=False, sperren=True)
    datenbank = archiv.datenbank
    try:
        # archiv_oeffnen hat ExifTool bereits geprueft (harter Abbruch fuer
        # analyse); hier nur noch den Pfad holen.
        gefunden, _wo = exiftool_finden(archiv.konf)
        lauf = datenbank.lauf_beginnen(_befehlszeile())
        offen = datenbank.anzahl_zu_analysieren()
        prozesse = int(getattr(args, "prozesse", 0) or 0) or metadaten.prozesse_bestimmen(
            archiv.konf, getattr(args, "profil", None))
        if offen == 0:
            konsole.print(meldungen.analyse_nichts_zu_tun())
        else:
            konsole.print(meldungen.analyse_beginnt(prozesse, offen))
        ergebnis = None
        if offen:
            try:
                ergebnis = analyse.ausfuehren(
                    archiv.ziel, archiv.konf, datenbank, lauf, gefunden, konsole, prozesse
                )
            except FotosortFehler:
                _lauf_sauber_abbrechen(datenbank, lauf)
                raise
            konsole.print("")
            konsole.print(meldungen.analyse_ergebnis(ergebnis))
        konsole.print("")
        konsole.print(meldungen.analyse_zusammenfassung(datenbank.analyse_zusammenfassung()))
        if ergebnis is not None and ergebnis.abgebrochen:
            konsole.print("")
            konsole.print(meldungen.analyse_abgebrochen())
            _lauf_sauber_abbrechen(datenbank, lauf)
            return ABGEBROCHEN
        _abschliessen(archiv, konsole, lauf, None if ergebnis is None else {
            "dateien": ergebnis.bearbeitet, "bytes": 0, "sekunden": ergebnis.sekunden,
        })
        return FEHLER if (ergebnis is not None and ergebnis.fehler) else OK
    finally:
        datenbank.schliessen()


def befehl_kopieren(args, konsole) -> int:
    """Phase 3: Uebertragen (SPEC Abschnitt 4 Phase 3); --verschieben nach Phase 5."""
    verschieben = bool(getattr(args, "verschieben", False))
    probelauf = bool(getattr(args, "dry_run", False))
    archiv = archiv_oeffnen(args, konsole, anlegen=False, sperren=not probelauf)
    datenbank = archiv.datenbank
    try:
        # Ungueltige Worker-Angaben sollen scheitern, bevor ein Lauf entsteht.
        kopieren.worker_zahlen(archiv.konf, args.profil, args.kopier_worker, args.hash_worker)
        if probelauf:
            konsole.print(meldungen.kopieren_plan(kopieren.planen(archiv.ziel, datenbank)))
            return OK
        lauf = datenbank.lauf_beginnen(_befehlszeile())
        try:
            ergebnis = kopieren.ausfuehren(
                archiv.ziel, archiv.konf, datenbank, lauf, konsole,
                kopier_worker=args.kopier_worker, hash_worker=args.hash_worker, profil=args.profil,
                verschieben=verschieben,
            )
        except FotosortFehler:
            _lauf_sauber_abbrechen(datenbank, lauf)
            raise
        if ergebnis.quellen_nicht_erreichbar:
            konsole.print(meldungen.quellen_uebersprungen(ergebnis.quellen_nicht_erreichbar))
        if ergebnis.geplant == 0 and not ergebnis.abgebrochen:
            konsole.print(meldungen.kopieren_nichts_zu_tun())
        else:
            konsole.print("")
            konsole.print(meldungen.kopieren_ergebnis(ergebnis))
            if verschieben:
                konsole.print(meldungen.verschieben_ergebnis(ergebnis))
        konsole.print("")
        konsole.print(meldungen.kopieren_zusammenfassung(datenbank.kopier_zusammenfassung()))
        if ergebnis.abgebrochen:
            konsole.print("")
            konsole.print(meldungen.kopieren_abgebrochen())
            _lauf_sauber_abbrechen(datenbank, lauf)
            return ABGEBROCHEN
        _abschliessen(archiv, konsole, lauf, {
            "dateien": ergebnis.kopiert, "bytes": ergebnis.bytes_kopiert, "sekunden": ergebnis.sekunden,
        })
        return FEHLER if ergebnis.fehler else OK
    finally:
        datenbank.schliessen()


def befehl_pruefen(args, konsole) -> int:
    """Phase 4: Zieldateien vollstaendig neu lesen (SPEC Abschnitt 4 Phase 4)."""
    archiv = archiv_oeffnen(args, konsole, anlegen=False, sperren=True)
    datenbank = archiv.datenbank
    try:
        kopieren.worker_zahlen(archiv.konf, args.profil, None, args.hash_worker)
        lauf = datenbank.lauf_beginnen(_befehlszeile())
        try:
            ergebnis = pruefen.ausfuehren(
                archiv.ziel, archiv.konf, datenbank, lauf, konsole,
                hash_worker=args.hash_worker, profil=args.profil,
            )
        except FotosortFehler:
            _lauf_sauber_abbrechen(datenbank, lauf)
            raise
        if ergebnis.geplant == 0:
            konsole.print(meldungen.pruefen_nichts_zu_tun())
        else:
            konsole.print("")
            konsole.print(meldungen.pruefen_ergebnis(ergebnis))
        konsole.print("")
        konsole.print(meldungen.pruefen_zusammenfassung(datenbank.zaehler_je_status(), datenbank.zu_pruefen_summe()[0]))
        if ergebnis.abgebrochen:
            konsole.print("")
            konsole.print(meldungen.pruefen_abgebrochen())
            _lauf_sauber_abbrechen(datenbank, lauf)
            return ABGEBROCHEN
        _abschliessen(archiv, konsole, lauf, {
            "dateien": ergebnis.bearbeitet, "bytes": ergebnis.bytes_gelesen, "sekunden": ergebnis.sekunden,
        })
        return FEHLER if ergebnis.fehler else OK
    finally:
        datenbank.schliessen()


# Vom Arbeitsprozess der Oberflaeche gesetzt: das Wort, das der Nutzer im
# Fenster getippt hat, je Bestaetigungsart ("dateien", "ordner"). Die
# Pruefung selbst (Wort == erwartetes Wort) bleibt hier im Kern.
bestaetigung_vorgabe: dict[str, str] | None = None


def _bestaetigung_lesen(konsole, frage: str, wort: str) -> bool:
    """Ein Wort abfragen - nicht nur Enter. Ohne Eingabemoeglichkeit: nein."""
    if bestaetigung_vorgabe is not None:
        konsole.print(frage)
        art = "ordner" if wort == meldungen.BESTAETIGUNGSWORT["ordner"] else "dateien"
        antwort = str(bestaetigung_vorgabe.get(art, ""))
        konsole.print(antwort or "(keine Eingabe)")
        return antwort.strip().lower() == wort
    if not sys.stdin or not sys.stdin.isatty() and os.environ.get("FOTOSORT_EINGABE_ERZWINGEN", "") != "1":
        # In einer Pipe oder ohne Terminal gibt es keine bewusste Bestaetigung.
        konsole.print(frage)
        konsole.print(meldungen.aufraeumen_keine_eingabe())
        return False
    konsole.print(frage, end="")
    try:
        antwort = input()
    except EOFError:
        antwort = ""
    return antwort.strip().lower() == wort


def befehl_aufraeumen(args, konsole) -> int:
    """Phase 5: Quelle aufraeumen, leere Ordner (SPEC Abschnitt 4 Phase 5 und 6)."""
    probelauf = bool(args.dry_run)
    weise = loeschen.WEISE_ENDGUELTIG if args.endgueltig else loeschen.WEISE_PAPIERKORB
    archiv = archiv_oeffnen(args, konsole, anlegen=False, sperren=not probelauf)
    datenbank = archiv.datenbank
    try:
        kopieren.worker_zahlen(archiv.konf, args.profil, None, args.hash_worker)
        plan = aufraeumen.planen(datenbank, args.quelle)
        if plan.unbekannt:
            for q in plan.unbekannt:
                konsole.print(meldungen.quelle_unbekannt(q))
            return FEHLENDE_ANGABE
        for q in plan.nicht_erreichbar:
            konsole.print(meldungen.aufraeumen_quelle_nicht_erreichbar(q))
        konsole.print(meldungen.aufraeumen_plan(plan.je_quelle, weise, plan.nicht_erreichbar))
        if not any(n for n, _ in plan.je_quelle.values()) and not args.leere_ordner:
            konsole.print(meldungen.aufraeumen_nichts_zu_tun())
            return OK if not plan.nicht_erreichbar else FEHLER
        if probelauf:
            ergebnis = aufraeumen.ausfuehren(
                archiv.ziel, archiv.konf, datenbank, 0, konsole, quellen=args.quelle, weise=weise,
                dry_run=True, leere_ordner=args.leere_ordner,
            )
            konsole.print(meldungen.aufraeumen_dry_run_schluss())
            return OK
        lauf = datenbank.lauf_beginnen(_befehlszeile())

        def bestaetigen(wurzel, n, b, w):
            if getattr(args, "nur_ordner", False):
                return False   # gefuehrter Modus: Dateien ausdruecklich verneint
            return _bestaetigung_lesen(konsole, meldungen.aufraeumen_frage(wurzel, n, b, w), meldungen.BESTAETIGUNGSWORT[w])

        def bestaetigen_ordner(wurzel, n):
            return _bestaetigung_lesen(konsole, meldungen.aufraeumen_ordner_frage(wurzel, n), meldungen.BESTAETIGUNGSWORT["ordner"])

        try:
            ergebnis = aufraeumen.ausfuehren(
                archiv.ziel, archiv.konf, datenbank, lauf, konsole, quellen=args.quelle, weise=weise,
                leere_ordner=args.leere_ordner, bestaetigen=bestaetigen, bestaetigen_ordner=bestaetigen_ordner,
                hash_worker=args.hash_worker, profil=args.profil,
            )
        except FotosortFehler:
            _lauf_sauber_abbrechen(datenbank, lauf)
            raise
        konsole.print("")
        konsole.print(meldungen.aufraeumen_ergebnis(ergebnis))
        if ergebnis.abgebrochen:
            konsole.print("")
            konsole.print(meldungen.aufraeumen_abgebrochen())
            _lauf_sauber_abbrechen(datenbank, lauf)
            return ABGEBROCHEN
        _abschliessen(archiv, konsole, lauf, {
            "dateien": ergebnis.bearbeitet, "bytes": ergebnis.bytes_gelesen, "sekunden": ergebnis.sekunden,
        })
        return FEHLER if (ergebnis.verweigert or ergebnis.quelle_veraendert or ergebnis.nicht_erreichbar) else OK
    finally:
        datenbank.schliessen()


def befehl_bericht(args, konsole) -> int:
    """Bericht als Text und CSV (SPEC Abschnitt 10). Legt keinen Lauf an."""
    archiv = archiv_oeffnen(args, konsole, anlegen=False)
    datenbank = archiv.datenbank
    try:
        txt, csv_d, csv_e = bericht.schreiben(archiv.ziel, datenbank)
        konsole.print(txt.read_text(encoding="utf-8"))
        konsole.print(meldungen.bericht_geschrieben(txt, csv_d, csv_e))
        return OK
    finally:
        datenbank.schliessen()


# ------------------------------------------------- Gefuehrter Modus ----


class _Abbruch(Exception):
    """Der Nutzer hat eine Frage nicht beantwortet (Eingabe zu Ende)."""


def _eingabe_moeglich() -> bool:
    """Fragen gehen nur mit Terminal - oder ausdruecklich erzwungen (Tests)."""
    if not sys.stdin:
        return False
    return sys.stdin.isatty() or os.environ.get("FOTOSORT_EINGABE_ERZWINGEN", "") == "1"


def _fragen(konsole, frage: str, standard: str = "") -> str:
    """Eine Frage stellen; Enter allein liefert den Vorschlag."""
    konsole.print(frage, end="")
    try:
        antwort = input()
    except EOFError as fehler:
        konsole.print("")
        raise _Abbruch() from fehler
    antwort = antwort.strip()
    return antwort if antwort else standard


def _ja(konsole, frage: str, standard: bool = False) -> bool:
    antwort = _fragen(konsole, frage).lower()
    if not antwort:
        return standard
    return antwort in ("j", "ja", "y", "yes")


def _weiter(konsole, frage: str) -> bool:
    """Enter = ja; nur ein ausdrueckliches n/nein haelt an."""
    antwort = _fragen(konsole, frage).lower()
    return antwort not in ("n", "nein", "no")


def _mindestens_eins(text: str) -> int:
    zahl = int(text)
    if zahl < 1:
        raise argparse.ArgumentTypeError(meldungen.zahl_mindestens_eins(text))
    return zahl


def _start_namensraum(args, befehl: str, **extra) -> argparse.Namespace:
    return argparse.Namespace(befehl=befehl, ziel=args.ziel, config=args.config, **extra)


def _start_archiv_lesen(args, konsole) -> dict:
    """Bekannte Quellen, Zaehler und Profil-Standard aus dem Archiv (nur lesen)."""
    archiv = archiv_oeffnen(args, konsole, anlegen=False)
    d = archiv.datenbank
    try:
        zaehler = d.zaehler_je_status()
        loeschbar = d.zu_loeschen_summe()
        return {
            "quellen": [z["wurzel"] for z in d.quellen_liste()],
            "zaehler": zaehler,
            "profil": str(archiv.konf.wert("leistung.profil") or "hdd"),
            "analyse": d.anzahl_zu_analysieren(),
            "kopieren": d.zu_kopieren_summe(),
            "pruefen": d.zu_pruefen_summe(),
            "aufraeumen": (sum(n for n, _ in loeschbar.values()), sum(b for _, b in loeschbar.values())),
            "modelle": [(m, o, n) for m, o, n in d.analyse_zusammenfassung()["modelle"] if m],
            "konf_pfad": archiv.konf_pfad,
        }
    finally:
        d.schliessen()


def _start_phase_text(zaehler: dict) -> str:
    niedrigster = next((s for s in db.STUFEN if zaehler.get(s, 0) > 0), None)
    return meldungen.status_phase(niedrigster, dateien_erfasst=sum(zaehler.values()) > 0)


def _start_quelle_pruefen(antwort: str, ziel: Path, bekannt_auf: set, quellen: list[str]) -> str | None:
    """Grund, warum dieser Quellordner nicht genommen wird - oder None."""
    q = Path(antwort)
    if not q.is_dir():
        return meldungen.start_quelle_kein_ordner(q)
    lage = pfade.lage_pruefen(q, ziel) if ziel.exists() else "getrennt"
    if lage == "gleich":
        return meldungen.quelle_gleich_ziel(pfade.aufloesen(q))
    if lage == "quelle_in_ziel":
        return meldungen.quelle_in_ziel(pfade.aufloesen(q))
    auf = pfade.aufloesen(q)
    if auf in bekannt_auf or any(pfade.aufloesen(Path(x)) == auf for x in quellen):
        return meldungen.start_quelle_schon_dabei(auf)
    return None


def _start_quellen_fragen(args, konsole, ziel: Path, bekannt: list[str]) -> list[str]:
    """Quellordner abfragen, bis der Nutzer mit leerer Eingabe fertig ist.
    Per Schalter genannte Quellen werden genauso geprueft wie getippte."""
    quellen: list[str] = []
    bekannt_auf = {pfade.aufloesen(Path(b)) for b in bekannt}
    for q in args.quelle or []:
        grund = _start_quelle_pruefen(str(q), ziel, bekannt_auf, quellen)
        if grund is None:
            quellen.append(str(q))
        else:
            konsole.print(meldungen.start_quelle_abgelehnt(q, grund))
    leer_hintereinander = 0
    while True:
        weitere = bool(quellen or bekannt)
        antwort = _fragen(konsole, meldungen.start_frage_quelle(weitere))
        if not antwort:
            if weitere:
                return quellen
            leer_hintereinander += 1
            if leer_hintereinander >= 3:
                raise _Abbruch()   # dreimal nichts: der Nutzer will nicht
            konsole.print(meldungen.start_quelle_noetig())
            continue
        leer_hintereinander = 0
        grund = _start_quelle_pruefen(antwort, ziel, bekannt_auf, quellen)
        if grund is not None:
            konsole.print(grund)
            continue
        quellen.append(antwort)


def _start_aliase(args, konsole, stand: dict) -> bool:
    """Nach der Analyse: Aliase abfragen, eintragen, betroffene Dateien neu
    analysieren. True, wenn etwas eingetragen wurde."""
    neue: dict[str, str] = {}
    if not stand["modelle"]:
        return False   # nichts analysiert, also nichts zuzuordnen
    konsole.print(meldungen.start_modelle(stand["modelle"]))
    bekannt = {m.lower(): m for m, _o, _n in stand["modelle"]}
    while True:
        modell = _fragen(konsole, meldungen.start_frage_alias())
        if not modell:
            break
        if modell.lower() not in bekannt:
            konsole.print(meldungen.start_alias_unbekannt(modell))
            continue
        name = _fragen(konsole, meldungen.start_frage_alias_ordner(modell))
        if name:
            neue[bekannt[modell.lower()]] = name
    if not neue:
        return False
    config.aliase_ergaenzen(stand["konf_pfad"], neue)
    archiv = archiv_oeffnen(args, konsole, anlegen=False, sperren=True)
    try:
        zurueck = archiv.datenbank.analyse_zuruecksetzen_nach_modell(list(neue))
    finally:
        archiv.datenbank.schliessen()
    konsole.print(meldungen.start_aliase_geschrieben(stand["konf_pfad"], len(neue), zurueck))
    return True


def befehl_start(args, konsole) -> int:
    """Phase 6: gefuehrt durch alle Phasen (SPEC Abschnitt 8).

    Jeder Schritt laeuft ueber denselben Weg wie der einzelne Befehl und
    ist fortsetzbar; ein erneuter Aufruf macht dort weiter, wo aufgehoert
    wurde, und ueberspringt Schritte ohne Arbeit.
    """
    args.quelle = list(args.quelle or [])
    # ExifTool zuerst (SPEC Abschnitt 2): mit der Konfiguration des Archivs,
    # wenn es eins gibt, sonst mit den Standardwerten.
    stand: dict | None = None
    if args.ziel and Path(args.ziel).exists() and db.archiv_id_vorhanden(Path(args.ziel)):
        stand = _start_archiv_lesen(args, konsole)
    else:
        exiftool_pruefen("start", config.Konfiguration(), konsole)
    if not _eingabe_moeglich():
        konsole.print(meldungen.start_keine_eingabe())
        return FEHLER
    konsole.print(meldungen.start_begruessung())
    schlechtester = OK
    try:
        # 1. Ziel
        if not args.ziel:
            args.ziel = _fragen(konsole, meldungen.start_frage_ziel())
            if not args.ziel:
                konsole.print(meldungen.ziel_fehlt())
                return FEHLENDE_ANGABE
        ziel = Path(args.ziel)
        if not ziel.exists():
            konsole.print(meldungen.start_ziel_fehlt(ziel))
            if not getattr(args, "ziel_anlegen", False) and not _ja(konsole, meldungen.start_frage_ziel_anlegen()):
                konsole.print(meldungen.start_abgebrochen())
                return ABGEBROCHEN
            args.ziel_anlegen = True
        elif stand is None and db.archiv_id_vorhanden(ziel):
            stand = _start_archiv_lesen(args, konsole)
        bekannt = stand["quellen"] if stand else []
        if bekannt:
            konsole.print(meldungen.start_quellen_bekannt(bekannt))

        # 2. Quellen, Modus, Profil
        neue_quellen = _start_quellen_fragen(args, konsole, ziel, bekannt)
        verschieben = bool(getattr(args, "verschieben", False))
        if not verschieben:
            verschieben = _fragen(konsole, meldungen.start_frage_modus(), "k").lower() in ("v", "verschieben")
        profil_standard = stand["profil"] if stand else "hdd"
        profil = getattr(args, "profil", None)
        versuche = 0
        while not profil:
            antwort = _fragen(konsole, meldungen.start_frage_profil(profil_standard), profil_standard).lower()
            if antwort in kopieren.PROFILE:
                profil = antwort
            else:
                konsole.print(meldungen.profil_ungueltig(antwort, sorted(kopieren.PROFILE)))
                versuche += 1
                if versuche >= 3:
                    raise _Abbruch()

        # 3. Zusammenfassung
        zaehler = stand["zaehler"] if stand else {}
        konsole.print(meldungen.start_zusammenfassung(
            ziel, bekannt + neue_quellen, verschieben, profil, _start_phase_text(zaehler)))
        if not _weiter(konsole, meldungen.start_frage_ok()):
            konsole.print(meldungen.start_abgebrochen())
            return ABGEBROCHEN

        def pruefen_rueckgabe(rc: int) -> bool:
            """False = hier aufhoeren."""
            nonlocal schlechtester
            if rc in (ABGEBROCHEN, FEHLENDE_ANGABE):
                schlechtester = rc
                return False
            if rc == FEHLER:
                schlechtester = FEHLER
                if not _ja(konsole, meldungen.start_fehler_frage()):
                    konsole.print(meldungen.start_aufgehoert())
                    return False
            return True

        # Schritt 1: Scan (immer - findet neue und geaenderte Dateien)
        konsole.print(meldungen.start_schritt(1, "Quellen durchsuchen"))
        if not _weiter(konsole, meldungen.start_frage_weiter("Quellen durchsuchen")):
            konsole.print(meldungen.start_aufgehoert())
            return schlechtester
        quelle_arg = (bekannt + neue_quellen) if neue_quellen else None
        rc = befehl_scan(_start_namensraum(args, "scan", quelle=quelle_arg,
                                           ziel_anlegen=bool(getattr(args, "ziel_anlegen", False))), konsole)
        if not pruefen_rueckgabe(rc):
            return schlechtester

        # Schritt 2: Analyse (+ Aliase)
        stand = _start_archiv_lesen(args, konsole)
        konsole.print(meldungen.start_schritt(2, "Analyse (Datum, Kamera, Zielordner)"))
        if stand["analyse"] == 0:
            konsole.print(meldungen.start_uebersprungen("Analyse"))
        else:
            if not _weiter(konsole, meldungen.start_frage_weiter("Analyse")):
                konsole.print(meldungen.start_aufgehoert())
                return schlechtester
            rc = befehl_analyse(_start_namensraum(args, "analyse", profil=profil), konsole)
            if not pruefen_rueckgabe(rc):
                return schlechtester
            stand = _start_archiv_lesen(args, konsole)
        while _start_aliase(args, konsole, stand):
            rc = befehl_analyse(_start_namensraum(args, "analyse", profil=profil), konsole)
            if not pruefen_rueckgabe(rc):
                return schlechtester
            stand = _start_archiv_lesen(args, konsole)

        # Schritt 3: Kopieren oder Verschieben
        titel = "Verschieben" if verschieben else "Kopieren"
        konsole.print(meldungen.start_schritt(3, titel))
        if stand["kopieren"][0] == 0:
            konsole.print(meldungen.start_uebersprungen(titel))
        else:
            rc = befehl_kopieren(_start_namensraum(
                args, "kopieren", verschieben=verschieben, dry_run=True, profil=profil,
                kopier_worker=None, hash_worker=None), konsole)
            if verschieben:
                # Verschieben loescht die Quelle: wie beim Aufraeumen ein Wort, kein Enter.
                n, b = stand["kopieren"]
                if not _bestaetigung_lesen(konsole, meldungen.start_verschieben_frage(n, b), "verschieben"):
                    konsole.print(meldungen.start_aufgehoert())
                    return schlechtester
            elif not _weiter(konsole, meldungen.start_frage_weiter(titel)):
                konsole.print(meldungen.start_aufgehoert())
                return schlechtester
            rc = befehl_kopieren(_start_namensraum(
                args, "kopieren", verschieben=verschieben, dry_run=False, profil=profil,
                kopier_worker=None, hash_worker=None), konsole)
            if not pruefen_rueckgabe(rc):
                return schlechtester
            stand = _start_archiv_lesen(args, konsole)

        # Schritt 4: Pruefen
        konsole.print(meldungen.start_schritt(4, "Pruefen (Zieldateien vollstaendig neu lesen)"))
        if stand["pruefen"][0] == 0:
            konsole.print(meldungen.start_uebersprungen("Pruefen"))
        else:
            if not _weiter(konsole, meldungen.start_frage_weiter("Pruefen")):
                konsole.print(meldungen.start_aufgehoert())
                return schlechtester
            rc = befehl_pruefen(_start_namensraum(args, "pruefen", profil=profil, hash_worker=None), konsole)
            if not pruefen_rueckgabe(rc):
                return schlechtester
            stand = _start_archiv_lesen(args, konsole)

        # Schritt 5: Aufraeumen und leere Ordner (nur auf ausdrueckliches Ja)
        konsole.print(meldungen.start_schritt(5, "Quelle aufraeumen"))
        n, b = stand["aufraeumen"]
        aufraeumen_ja = n > 0 and _ja(konsole, meldungen.start_frage_aufraeumen(n, b))
        if n == 0:
            konsole.print(meldungen.start_uebersprungen("Quelle aufraeumen"))
        leere = _ja(konsole, meldungen.start_frage_leere_ordner())
        if aufraeumen_ja or leere:
            rc = befehl_aufraeumen(_start_namensraum(
                args, "aufraeumen", quelle=None, leere_ordner=leere, dry_run=False,
                endgueltig=False, profil=profil, hash_worker=None,
                nur_ordner=not aufraeumen_ja), konsole)
            if not pruefen_rueckgabe(rc):
                return schlechtester
            stand = _start_archiv_lesen(args, konsole)
        konsole.print(meldungen.start_fertig(stand["zaehler"]))
        return schlechtester
    except _Abbruch:
        konsole.print(meldungen.start_abgebrochen())
        return ABGEBROCHEN


def befehl_arbeit(args, konsole) -> int:
    """Ein Schritt im Auftrag der Oberflaeche (Phase 7): laeuft als eigener
    Prozess, meldet seinen Stand in eine Datei und nimmt Pause/Abbruch
    von dort entgegen. Sonst genau derselbe Weg wie der einzelne Befehl."""
    global bestaetigung_vorgabe
    auftrag = steuerung.json_lesen(Path(args.auftrag))
    if not auftrag:
        konsole.print(meldungen.arbeit_auftrag_fehlt(args.auftrag))
        return FEHLENDE_ANGABE
    schritt = str(auftrag.get("schritt", ""))
    st = steuerung.Steuerung(Path(auftrag["status_datei"]), Path(auftrag["steuer_datei"]), schritt)
    steuerung.AKTIV = st
    st.schreiben()
    st.herzschlag_starten()
    ns = argparse.Namespace(befehl=schritt, ziel=auftrag.get("ziel"), config=auftrag.get("config"))
    try:
        if schritt == "scan":
            ns.quelle = list(auftrag.get("quellen") or []) or None
            ns.ziel_anlegen = bool(auftrag.get("ziel_anlegen"))
            rc = befehl_scan(ns, konsole)
        elif schritt == "analyse":
            ns.profil = auftrag.get("profil")
            ns.prozesse = None
            rc = befehl_analyse(ns, konsole)
        elif schritt == "kopieren":
            ns.verschieben = bool(auftrag.get("verschieben"))
            ns.dry_run = False
            ns.profil = auftrag.get("profil")
            ns.kopier_worker = None
            ns.hash_worker = None
            rc = befehl_kopieren(ns, konsole)
        elif schritt == "pruefen":
            ns.profil = auftrag.get("profil")
            ns.hash_worker = None
            rc = befehl_pruefen(ns, konsole)
        elif schritt == "aufraeumen":
            ns.quelle = list(auftrag.get("quellen") or []) or None
            ns.leere_ordner = bool(auftrag.get("leere_ordner"))
            ns.dry_run = False
            ns.endgueltig = auftrag.get("weise") == loeschen.WEISE_ENDGUELTIG
            ns.profil = auftrag.get("profil")
            ns.hash_worker = None
            bestaetigung_vorgabe = dict(auftrag.get("bestaetigung") or {})
            rc = befehl_aufraeumen(ns, konsole)
        else:
            konsole.print(meldungen.arbeit_schritt_unbekannt(schritt))
            rc = FEHLENDE_ANGABE
    except KeyboardInterrupt:
        st.beenden(steuerung.ZUSTAND_ABGEBROCHEN, ABGEBROCHEN, meldungen.abbruch_allgemein())
        return ABGEBROCHEN
    except FotosortFehler as fehler:
        st.beenden(steuerung.ZUSTAND_FEHLER, FEHLER, str(fehler))
        konsole.print(str(fehler))
        return FEHLER
    except Exception as fehler:  # noqa: BLE001 - der Stand muss die Oberflaeche erreichen
        st.beenden(steuerung.ZUSTAND_FEHLER, FEHLER, f"{type(fehler).__name__}: {fehler}")
        raise
    finally:
        bestaetigung_vorgabe = None
        steuerung.AKTIV = None
    if rc == ABGEBROCHEN:
        st.beenden(steuerung.ZUSTAND_ABGEBROCHEN, rc, meldungen.abbruch_allgemein())
    elif rc == OK:
        st.beenden(steuerung.ZUSTAND_FERTIG, rc)
    else:
        st.beenden(steuerung.ZUSTAND_FEHLER, rc, meldungen.arbeit_mit_fehlern(schritt))
    return rc


def befehl_fenster(args, konsole) -> int:
    """Phase 7: die Oberflaeche - das Desktop-Fenster (PySide6) oder nur der
    Server fuer den Browser (--ohne-fenster). Jeder Fehler vor dem Start
    erscheint als verstaendliches Meldungsfenster, nie als Absturz."""
    from .oberflaeche import fenster, meldungsfenster
    durchlauf = tuple(args.durchlauf) if getattr(args, "durchlauf", None) else None
    try:
        return fenster.starten(
            ohne_fenster=bool(args.ohne_fenster), port=args.port, selbsttest=bool(args.selbsttest),
            ziel=args.ziel, konsole=konsole, durchlauf=durchlauf, fotos=getattr(args, "fotos", None),
        )
    except FotosortFehler:
        raise
    except Exception as fehler:  # noqa: BLE001 - verstaendlich zeigen statt Stapelabzug
        protokoll = None
        try:
            protokoll = fenster_protokoll()
        except OSError:
            pass
        meldungsfenster.startfehler(fehler, protokoll)
        konsole.print(meldungsfenster.starttext(fehler, protokoll))
        return FEHLER


def befehl_messen(args, konsole) -> int:
    """Lese- und Schreibtempo messen (Phase 6). Kein Archiv, kein Lauf."""
    quelle = Path(args.quelle)
    ziel = Path(args.ziel)
    if not quelle.is_dir():
        konsole.print(meldungen.quelle_existiert_nicht(quelle))
        return FEHLER
    if not ziel.is_dir():
        konsole.print(meldungen.ziel_existiert_nicht(ziel))
        return FEHLER
    try:
        ergebnis = messen.ausfuehren(quelle, ziel, konsole, mb=args.mb)
    except KeyboardInterrupt:
        konsole.print("")
        konsole.print(meldungen.messen_abgebrochen(messen.reste(ziel)))
        return ABGEBROCHEN
    if not (ergebnis.lesen_gemessen or ergebnis.schreiben_gemessen):
        konsole.print(meldungen.messen_nichts_gemessen())
        return FEHLER
    konsole.print(meldungen.messen_ergebnis(ergebnis))
    return OK


def befehl_spaetere_phase(args, konsole) -> int:
    konsole.print(meldungen.noch_nicht_gebaut(args.befehl, PHASE_JE_BEFEHL[args.befehl]))
    return SPAETERE_PHASE


# ------------------------------------------------------------ argparse ----


# Die Argumente des laufenden Aufrufs - aus main(argv), nicht aus sys.argv,
# damit auch ein Aufruf aus dem Programm heraus (Tests, gefuehrter Modus)
# im Lauf-Protokoll richtig steht.
_argumente: list[str] = []


def _befehlszeile() -> str:
    return " ".join(["fotosort", *_argumente])


def _gemeinsam(unter: argparse.ArgumentParser) -> None:
    unter.add_argument(
        "--ziel",
        metavar="PFAD",
        help="Zielordner des Archivs; ersatzweise FOTOSORT_ZIEL",
    )
    unter.add_argument(
        "--config",
        metavar="PFAD",
        help="andere Konfigurationsdatei benutzen",
    )


def parser_bauen() -> argparse.ArgumentParser:
    eltern = argparse.ArgumentParser(
        prog="fotosort",
        description="Sortiert Fotos und Videos nach Aufnahmedatum und Kamera.",
    )
    eltern.add_argument("--version", action=_Version)
    unterbefehle = eltern.add_subparsers(dest="befehl", metavar="BEFEHL")

    p = unterbefehle.add_parser("scan", help="Quelle durchlaufen und erfassen")
    p.add_argument(
        "--quelle",
        metavar="PFAD",
        action="append",
        help="Quellordner; mehrfach angebbar. Ohne Angabe alle bekannten Quellen",
    )
    p.add_argument(
        "--ziel-anlegen",
        action="store_true",
        help="einen noch nicht vorhandenen Zielordner wirklich anlegen",
    )
    _gemeinsam(p)

    p = unterbefehle.add_parser("analyse", help="Metadaten lesen und Ziel berechnen")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE),
                   help="bestimmt die Zahl der ExifTool-Prozesse (hdd/netzwerk 4, ssd Kerne bis 16)")
    p.add_argument("--prozesse", type=_mindestens_eins, default=None, help="Zahl der ExifTool-Prozesse fest vorgeben (1 oder mehr)")
    _gemeinsam(p)

    p = unterbefehle.add_parser("kopieren", help="Dateien ins Ziel uebertragen")
    p.add_argument("--verschieben", action="store_true",
                   help="verschieben: kopieren, beide Seiten frisch lesen, dann Quelle loeschen; gleiches Laufwerk: umbenennen")
    p.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts tun")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE), help="Voreinstellung fuer die Worker-Zahlen")
    p.add_argument("--kopier-worker", type=int, metavar="N", help="gleichzeitige Kopiervorgaenge")
    p.add_argument("--hash-worker", type=int, metavar="N", help="gleichzeitige Hash-Berechnungen")
    _gemeinsam(p)

    p = unterbefehle.add_parser("pruefen", help="Zieldateien vollstaendig neu lesen und vergleichen")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE), help="Voreinstellung fuer die Worker-Zahlen")
    p.add_argument("--hash-worker", type=int, metavar="N", help="gleichzeitige Hash-Berechnungen")
    _gemeinsam(p)

    p = unterbefehle.add_parser("aufraeumen", help="gepruefte Quelldateien entfernen (nur nach Bestaetigung)")
    p.add_argument("--quelle", metavar="PFAD", action="append", help="nur diese Quelle; mehrfach angebbar")
    p.add_argument("--leere-ordner", action="store_true", help="leere Ordner entfernen")
    p.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts tun")
    p.add_argument("--endgueltig", action="store_true",
                   help="endgueltig loeschen statt in den Ordner _geloescht_<Datum> zu verschieben")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE), help="Voreinstellung fuer die Worker-Zahlen")
    p.add_argument("--hash-worker", type=int, metavar="N", help="gleichzeitige Hash-Berechnungen")
    _gemeinsam(p)

    p = unterbefehle.add_parser("status", help="Zaehler je Status und aktuelle Phase")
    _gemeinsam(p)

    p = unterbefehle.add_parser("bericht", help="Bericht als Text und CSV")
    _gemeinsam(p)

    p = unterbefehle.add_parser("ziel-index", help="Ziel-Index pflegen")
    p.add_argument("--neu-aufbauen", action="store_true", help="Index vollstaendig neu")
    _gemeinsam(p)

    p = unterbefehle.add_parser("wiederherstellen", help="Datenbank aus der Sicherung")
    _gemeinsam(p)

    p = unterbefehle.add_parser("config", help="Konfiguration zeigen und oeffnen")
    p.add_argument("--nur-pfad", action="store_true", help="nur den Pfad ausgeben")
    _gemeinsam(p)

    p = unterbefehle.add_parser("start", help="gefuehrt durch alle Phasen")
    p.add_argument("--quelle", metavar="PFAD", action="append", help="Quellordner; mehrfach angebbar (sonst wird gefragt)")
    p.add_argument(
        "--ziel-anlegen",
        action="store_true",
        help="einen noch nicht vorhandenen Zielordner wirklich anlegen",
    )
    p.add_argument("--verschieben", action="store_true", help="verschieben statt kopieren (sonst wird gefragt)")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE), help="Voreinstellung fuer die Worker-Zahlen (sonst wird gefragt)")
    _gemeinsam(p)

    p = unterbefehle.add_parser("fenster", help="die Oberflaeche mit Fenster und Knoepfen oeffnen")
    p.add_argument("--ohne-fenster", action="store_true", help="nur den Server der Browser-Fassung starten und die Adresse nennen")
    p.add_argument("--port", type=int, default=0, help="Anschluss fuer den Server (0 = frei waehlen)")
    p.add_argument("--selbsttest", action="store_true", help="Fenster oeffnen, Zustand lesen, wieder schliessen (fuer die CI)")
    p.add_argument("--durchlauf", nargs=2, metavar=("ZIEL", "QUELLE"), help="den ganzen Ablauf ueber das Fenster fahren (CI, Bildschirmfotos)")
    p.add_argument("--fotos", metavar="ORDNER", help="beim Durchlauf ein Bildschirmfoto je Ansicht in diesen Ordner legen")
    _gemeinsam(p)

    p = unterbefehle.add_parser("arbeit", help="ein Schritt im Auftrag der Oberflaeche (intern)")
    p.add_argument("--auftrag", metavar="DATEI", required=True, help="JSON-Datei mit dem Auftrag")
    _gemeinsam(p)

    p = unterbefehle.add_parser("messen", help="Lese- und Schreibtempo von Quelle und Ziel messen")
    p.add_argument("--quelle", metavar="PFAD", required=True, help="Quellordner, aus dem gelesen wird")
    p.add_argument("--mb", type=int, default=256, metavar="N", help="Datenmenge je Stufe in MB (Standard 256)")
    _gemeinsam(p)

    return eltern


def _konsole(fehlerausgabe: bool = False):
    """Die Ausgabe-Konsole.

    markup=False ist wichtig: Sonst wuerde rich alles in eckigen Klammern
    als eigene Anweisung lesen und stillschweigend aus der Ausgabe
    entfernen. Aus "[leistung]" wuerde nichts, und ein Ordner namens
    "[urlaub] 2026" erschiene dem Nutzer als " 2026" - ein falscher Pfad.
    Das Projekt braucht nirgends rich-Markup.
    """
    from rich.console import Console

    return Console(
        soft_wrap=True, highlight=False, markup=False, stderr=fehlerausgabe
    )


def fenster_protokoll() -> Path:
    """Die Protokolldatei des Fensterprogramms (ohne Konsole geht alles dorthin).
    Der Ordner wird angelegt, bevor jemand hineinschreibt."""
    from .oberflaeche import ablauf
    ordner = ablauf.oberflaeche_ordner()
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner / "fenster.log"


def _ohne_konsole_umleiten() -> None:
    """Gepacktes Fensterprogramm: Es gibt keine Konsole, sys.stdout ist None.
    Alles, was das Programm sagt, landet dann in einer Protokolldatei. Geht
    auch das nicht (Ordner nicht anlegbar), wird verworfen statt abgebrochen."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        protokoll = open(fenster_protokoll(), "a", encoding="utf-8", errors="replace")
    except OSError:
        protokoll = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = protokoll
    if sys.stderr is None:
        sys.stderr = protokoll


def main(argv: list[str] | None = None) -> int:
    global _argumente
    _ohne_konsole_umleiten()
    argumente = list(sys.argv[1:] if argv is None else argv)
    # Das Fensterprogramm (fotosort-fenster.exe) und fotosort.exe per
    # Doppelklick, beide ohne Angaben: das Fenster oeffnen.
    if not argumente and getattr(sys, "frozen", False):
        argumente = ["fenster"]
    eltern = parser_bauen()
    _exiftool_startbar_gemerkt.clear()
    _argumente = argumente
    args = eltern.parse_args(argumente)
    if not args.befehl:
        eltern.print_help()
        return FEHLENDE_ANGABE

    konsole = _konsole()

    # Jeder Befehl ausser --help braucht ein Ziel (SPEC Abschnitt 8).
    if not getattr(args, "ziel", None):
        args.ziel = os.environ.get("FOTOSORT_ZIEL", "").strip() or None
    # Ausnahmen: der gefuehrte Modus und das Fenster fragen nach dem Ziel,
    # statt abzubrechen; der Arbeitsprozess bekommt es aus dem Auftrag.
    if not args.ziel and args.befehl not in ("start", "fenster", "arbeit"):
        konsole.print(meldungen.ziel_fehlt())
        return FEHLENDE_ANGABE

    # Die ExifTool-Pruefung nach SPEC Abschnitt 2 geschieht in
    # archiv_oeffnen - erst dort ist die Konfiguration geladen, und nur
    # dann kann der Wert exiftool_pfad ueberhaupt wirken. Befehle, die kein
    # Archiv oeffnen, pruefen hier mit den Standardwerten.
    # Befehle, die ein Archiv oeffnen, pruefen ExifTool erst dort - mit der
    # geladenen Konfiguration, sonst wirkte exiftool_pfad nie (SPEC §2).
    if args.befehl not in ("scan", "status", "config", "analyse", "kopieren", "pruefen", "bericht", "aufraeumen", "start", "messen", "fenster", "arbeit"):
        gefunden, wo = exiftool_finden(config.Konfiguration())
        if not (gefunden and exiftool_startbar(gefunden)):
            if args.befehl in BRAUCHT_EXIFTOOL:
                konsole.print(meldungen.exiftool_fehlt(wo))
                return FEHLER
            konsole.print(meldungen.exiftool_hinweis(wo))

    _signale_einrichten()
    try:
        if args.befehl == "scan":
            return befehl_scan(args, konsole)
        if args.befehl == "status":
            return befehl_status(args, konsole)
        if args.befehl == "config":
            return befehl_config(args, konsole)
        if args.befehl == "analyse":
            return befehl_analyse(args, konsole)
        if args.befehl == "kopieren":
            return befehl_kopieren(args, konsole)
        if args.befehl == "pruefen":
            return befehl_pruefen(args, konsole)
        if args.befehl == "bericht":
            return befehl_bericht(args, konsole)
        if args.befehl == "aufraeumen":
            return befehl_aufraeumen(args, konsole)
        if args.befehl == "start":
            return befehl_start(args, konsole)
        if args.befehl == "messen":
            return befehl_messen(args, konsole)
        if args.befehl == "fenster":
            return befehl_fenster(args, konsole)
        if args.befehl == "arbeit":
            return befehl_arbeit(args, konsole)
        return befehl_spaetere_phase(args, konsole)
    except FotosortFehler as fehler:
        konsole.print(str(fehler))
        return FEHLER
    except tomllib.TOMLDecodeError as fehler:
        konsole.print(meldungen.config_kaputt(args.config or "config.toml", None, None, str(fehler)))
        return FEHLER
    except sqlite3.OperationalError as fehler:
        if "locked" in str(fehler) or "busy" in str(fehler):
            konsole.print(meldungen.datenbank_belegt(args.ziel))
            return FEHLER
        konsole.print(meldungen.system_fehler(args.ziel, str(fehler)))
        return FEHLER
    except OSError as fehler:
        # Fehlende Rechte, "--ziel zeigt auf eine Datei", ein Netzlaufwerk
        # mit Aussetzer: alles Alltagsfaelle, die der Nutzer auf Deutsch
        # erklaert bekommt statt als rohen Python-Text (CLAUDE.md Abs. 4, 6).
        betroffen = getattr(fehler, "filename", None) or args.ziel
        konsole.print(meldungen.system_fehler(betroffen, fehler.strerror or str(fehler)))
        return FEHLER
    except KeyboardInterrupt:
        konsole.print("")
        konsole.print(meldungen.abbruch_allgemein())
        return ABGEBROCHEN


def _signale_einrichten() -> None:
    """SIGTERM auf denselben Weg legen wie Strg+C.

    SIGTERM ist das Signal, mit dem "docker stop" und TrueNAS einen
    Container beenden. Ohne Behandlung endet das Programm augenblicklich,
    ohne Meldung und ohne die Datenbank sauber zu schliessen.
    """

    def beenden(nummer, rahmen):  # pragma: no cover - nur im echten Betrieb
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP"):
        signal_nummer = getattr(signal, name, None)
        if signal_nummer is None:  # pragma: no cover - Windows kennt SIGHUP nicht
            continue
        try:
            signal.signal(signal_nummer, beenden)
        except (ValueError, OSError):  # pragma: no cover - nicht im Hauptstrang
            pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
