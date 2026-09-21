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

from . import analyse, bericht, kopieren, metadaten, pruefen, FotosortFehler, config, db, meldungen, pfade, scan

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
    "start": 6,
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
    return shutil.which("exiftool"), "exiftool ueber PATH"


def exiftool_pruefen(befehl: str, konf, konsole) -> None:
    """Bei jedem Start pruefen, ob ExifTool da und startbar ist.

    Vorrang nach SPEC Abschnitt 2: FOTOSORT_EXIFTOOL, dann der
    Konfigurationswert exiftool_pfad, dann PATH. Harter Abbruch nur bei den
    Befehlen, die Metadaten brauchen.
    """
    gefunden, wo = exiftool_finden(konf)
    if gefunden and exiftool_startbar(gefunden):
        return
    if befehl in BRAUCHT_EXIFTOOL:
        raise FotosortFehler(meldungen.exiftool_fehlt(wo))
    konsole.print(meldungen.exiftool_hinweis(wo))


def exiftool_startbar(pfad: str) -> bool:
    try:
        fertig = subprocess.run(
            [pfad, "-ver"], capture_output=True, timeout=20, check=False
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
        prozesse = metadaten.prozesse_bestimmen(archiv.konf)
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
    """Phase 3: Uebertragen im Kopier-Modus (SPEC Abschnitt 4 Phase 3)."""
    if getattr(args, "verschieben", False):
        konsole.print(meldungen.verschieben_spaeter())
        return SPAETERE_PHASE
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
        konsole.print(meldungen.pruefen_zusammenfassung(datenbank.zaehler_je_status()))
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
    _gemeinsam(p)

    p = unterbefehle.add_parser("kopieren", help="Dateien ins Ziel uebertragen")
    p.add_argument("--verschieben", action="store_true", help="statt kopieren verschieben (erst Phase 5)")
    p.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts tun")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE), help="Voreinstellung fuer die Worker-Zahlen")
    p.add_argument("--kopier-worker", type=int, metavar="N", help="gleichzeitige Kopiervorgaenge")
    p.add_argument("--hash-worker", type=int, metavar="N", help="gleichzeitige Hash-Berechnungen")
    _gemeinsam(p)

    p = unterbefehle.add_parser("pruefen", help="Zieldateien vollstaendig neu lesen und vergleichen")
    p.add_argument("--profil", choices=sorted(kopieren.PROFILE), help="Voreinstellung fuer die Worker-Zahlen")
    p.add_argument("--hash-worker", type=int, metavar="N", help="gleichzeitige Hash-Berechnungen")
    _gemeinsam(p)

    p = unterbefehle.add_parser("aufraeumen", help="gepruefte Quelldateien entfernen")
    p.add_argument("--leere-ordner", action="store_true", help="leere Ordner entfernen")
    p.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts tun")
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
    p.add_argument("--quelle", metavar="PFAD", help="Quellordner")
    p.add_argument(
        "--ziel-anlegen",
        action="store_true",
        help="einen noch nicht vorhandenen Zielordner wirklich anlegen",
    )
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


def main(argv: list[str] | None = None) -> int:
    global _argumente
    eltern = parser_bauen()
    _argumente = list(sys.argv[1:] if argv is None else argv)
    args = eltern.parse_args(argv)
    if not args.befehl:
        eltern.print_help()
        return FEHLENDE_ANGABE

    konsole = _konsole()

    # Jeder Befehl ausser --help braucht ein Ziel (SPEC Abschnitt 8).
    if not getattr(args, "ziel", None):
        args.ziel = os.environ.get("FOTOSORT_ZIEL", "").strip() or None
    if not args.ziel:
        konsole.print(meldungen.ziel_fehlt())
        return FEHLENDE_ANGABE

    # Die ExifTool-Pruefung nach SPEC Abschnitt 2 geschieht in
    # archiv_oeffnen - erst dort ist die Konfiguration geladen, und nur
    # dann kann der Wert exiftool_pfad ueberhaupt wirken. Befehle, die kein
    # Archiv oeffnen, pruefen hier mit den Standardwerten.
    # Befehle, die ein Archiv oeffnen, pruefen ExifTool erst dort - mit der
    # geladenen Konfiguration, sonst wirkte exiftool_pfad nie (SPEC §2).
    if args.befehl not in ("scan", "status", "config", "analyse", "kopieren", "pruefen", "bericht"):
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
