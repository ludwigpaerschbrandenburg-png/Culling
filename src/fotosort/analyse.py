"""Phase 2: Analyse (SPEC Abschnitt 4 Phase 2).

Metadaten lesen, Ziel fuer jede Datei berechnen, Gruppen bilden. Es wird
keine Datei angefasst - nur die Datenbank bekommt Kamera, Aufnahmezeit,
Gruppe und Zielpfad. Fortsetzbar: bearbeitet werden nur Zeilen mit Status
"gefunden"; ein Abbruch laesst das Bisherige geschrieben.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import FotosortFehler, dateitypen, db, gruppen, kamera, meldungen, metadaten
from . import datum as datum_modul
from . import ziel as ziel_modul

ART_ZIELORDNER_MEHRDEUTIG = "zielordner_mehrdeutig"
GRUND_SIDECAR_OHNE_HAUPT = "Sidecar ohne Hauptdatei"
GRUND_METADATEN = "Metadaten nicht lesbar"
GRUND_ZEILENUMBRUCH = "Zeilenumbruch im Dateinamen - bitte umbenennen"
GRUND_KEIN_UTF8 = "Dateiname ist kein gueltiges UTF-8 - bitte umbenennen"
GRUND_HAUPTDATEI = "Hauptdatei"

SEITE = 5000
_ANZEIGE_ALLE = 100
_STILLE_SEKUNDEN = 5.0


@dataclass
class Ergebnis:
    bearbeitet: int = 0
    gruppen: int = 0
    fehler: int = 0
    sidecar_ohne_haupt: int = 0
    mehrdeutig: int = 0
    wiederverwendet: int = 0
    stapel: int = 0
    prozesse: int = 0
    sekunden: float = 0.0
    abgebrochen: bool = False
    mehrdeutig_gemeldet: set = field(default_factory=set)


def _leer(row) -> bool:
    return row["status"] == "gefunden"


def ausfuehren(
    ziel: Path, konf, dbank: db.Datenbank, lauf: int, exiftool: str,
    konsole=None, prozesse: int | None = None,
) -> Ergebnis:
    begonnen = time.monotonic()
    ergebnis = Ergebnis()
    ergebnis.prozesse = prozesse or metadaten.prozesse_bestimmen(konf)
    try:
        datum_modul.zeitzone_pruefen(konf.wert("datum.heimat_zeitzone"))
    except datum_modul.ZeitzoneUngueltig as fehler:
        raise FotosortFehler(meldungen.zeitzone_ungueltig(fehler)) from fehler
    struktur = ziel_modul.Zielstruktur(ziel)
    trenner = os.sep
    gesamt = dbank.anzahl_zu_analysieren()
    anzeige = _Anzeige(konsole, gesamt)

    with metadaten.ExifToolPool(exiftool, ergebnis.prozesse) as pool:
        ab = ""
        try:
            while True:
                seite = dbank.zu_analysieren(ab, SEITE)
                if not seite:
                    break
                ab = seite[-1]["quellpfad"]
                ordner: dict[str, None] = {}
                for z in seite:
                    if db.ist_roh_kodiert(z["quellpfad"]):
                        # Kein gueltiges UTF-8 im Namen: ExifTool-Antwort und
                        # Ordnersuche koennten nie passen. Sichtbar melden
                        # statt still auf "gefunden" liegen zu lassen.
                        _fehler_setzen(dbank, z["quellpfad"], GRUND_KEIN_UTF8, "")
                        ergebnis.fehler += 1
                        ergebnis.bearbeitet += 1
                        anzeige.weiter(1)
                        continue
                    # Unterordner sortieren zwischen die Dateien eines Ordners
                    # ("o/a.jpg", "o/b/x.jpg", "o/k.jpg"); jeder Ordner darf
                    # trotzdem nur einmal in der Liste stehen.
                    ordner.setdefault(db.pfad_text(Path(db.text_pfad(z["quellpfad"])).parent))
                _seite_bearbeiten(list(ordner), trenner, struktur, konf, dbank, lauf, pool, ergebnis, anzeige)
        except KeyboardInterrupt:
            ergebnis.abgebrochen = True
        finally:
            dbank.stapel_schreiben()
            anzeige.stop()

    ergebnis.sekunden = time.monotonic() - begonnen
    return ergebnis


def _seite_bearbeiten(ordner, trenner, struktur, konf, dbank, lauf, pool, ergebnis, anzeige) -> None:
    # 1. Gruppen je Ordner bilden und die zu lesenden Dateien einsammeln.
    aufgaben: list[tuple[str, gruppen.Gruppe, dict]] = []   # (ordner_text, gruppe, zeilen nach Name)
    zu_lesen: list[tuple[str, str]] = []                      # (pfad, typ)
    ohne_haupt: list[tuple[str, dict]] = []
    for o in ordner:
        zeilen = dbank.ordner_inhalt(o, trenner)
        if not zeilen:
            continue
        nach_name = {Path(db.text_pfad(z["quellpfad"])).name: z for z in zeilen}
        gruppen_liste, verwaist = gruppen.bilden(list(nach_name), konf)
        for name in verwaist:
            if _leer(nach_name[name]):
                ohne_haupt.append((name, nach_name[name]))
        for g in gruppen_liste:
            if not any(_leer(nach_name[n]) for n in g.alle):
                continue  # alles schon analysiert
            aufgaben.append((o, g, nach_name))
            haupt = nach_name[g.haupt]
            if _leer(haupt):
                haupt_pfad = db.text_pfad(haupt["quellpfad"])
                if metadaten.unzulaessig_fuer_exiftool(haupt_pfad):
                    continue  # bekommt unten Status fehler, geht nie an ExifTool
                zu_lesen.append((haupt_pfad, haupt["dateityp"]))
                if haupt["dateityp"] == dateitypen.VIDEO:
                    for s in g.sidecars:
                        s_pfad = db.text_pfad(nach_name[s]["quellpfad"])
                        if s.lower().endswith(".xml") and not metadaten.unzulaessig_fuer_exiftool(s_pfad):
                            zu_lesen.append((s_pfad, dateitypen.SIDECAR))

    # 2. Metadaten in Stapeln lesen, parallel ueber die ExifTool-Prozesse.
    felder_von: dict[str, dict] = {}
    stapel = metadaten.stapel_bilden(zu_lesen)
    ergebnis.stapel += len(stapel)
    for zukunft in [pool.einreichen(s) for s in stapel]:
        try:
            felder_von.update(zukunft.result())
        except metadaten.MetadatenFehler:
            pass  # betroffene Dateien fehlen dann in felder_von -> Status fehler

    # 3. Auswerten und schreiben.
    for name, zeile in ohne_haupt:
        dbank.analyse_setzen(
            zeile["quellpfad"], kamera="", kamera_modell="", aufnahme_zeit="",
            datum_quelle=0, datum_sicher=0, datum_hinweis="", gruppe="",
            zielpfad="", status="uebersprungen", fehlergrund=GRUND_SIDECAR_OHNE_HAUPT,
        )
        ergebnis.sidecar_ohne_haupt += 1
        ergebnis.bearbeitet += 1
        anzeige.weiter(1)

    for o, g, nach_name in aufgaben:
        haupt = nach_name[g.haupt]
        haupt_pfad = db.text_pfad(haupt["quellpfad"])
        haupt_neu = _leer(haupt)
        if haupt_neu:
            if metadaten.unzulaessig_fuer_exiftool(haupt_pfad):
                _gruppe_fehler(g, nach_name, dbank, GRUND_ZEILENUMBRUCH, ergebnis, anzeige)
                continue
            felder = felder_von.get(metadaten.schluessel(haupt_pfad))
            if felder is None:
                _gruppe_fehler(g, nach_name, dbank, GRUND_METADATEN, ergebnis, anzeige)
                continue
            if felder.get("Error"):
                _gruppe_fehler(g, nach_name, dbank, f"{GRUND_METADATEN}: {felder['Error']}", ergebnis, anzeige)
                continue
            sidecar_felder = None
            for s in g.sidecars:
                if s.lower().endswith(".xml"):
                    sidecar_felder = felder_von.get(
                        metadaten.schluessel(db.text_pfad(nach_name[s]["quellpfad"]))
                    )
                    if sidecar_felder and not sidecar_felder.get("Error"):
                        break
                    sidecar_felder = None
            if sidecar_felder and not kamera.rohmodell(felder):
                # Sony-Sidecar kennt das Modell, die Videodatei nicht.
                felder = dict(felder, Model=sidecar_felder.get("NonRealTimeMetaDeviceModelName", ""))
            d = datum_modul.bestimmen(
                felder, sidecar_felder, g.haupt, haupt["dateityp"], haupt["mtime"] or 0.0, konf
            )
            kam, roh = kamera.ordnername(felder, konf)
            _, ort = ziel_modul.zielpfad(struktur, d, kam, g.haupt, konf)
            werte = dict(
                kamera=kam, kamera_modell=roh, aufnahme_zeit=ziel_modul.zeit_text(d.zeit),
                datum_quelle=d.quelle, datum_sicher=1 if d.sicher else 0, datum_hinweis=d.hinweis,
            )
            if ort.mehrdeutig:
                ergebnis.mehrdeutig += 1
                if ort.ordner not in ergebnis.mehrdeutig_gemeldet:
                    ergebnis.mehrdeutig_gemeldet.add(ort.ordner)
                    dbank.ereignis(lauf, ART_ZIELORDNER_MEHRDEUTIG, ort.ordner, 1,
                                   "mehrere passende Ordner mit Zusatz, alphabetisch erster gewaehlt")
            if ort.wiederverwendet:
                ergebnis.wiederverwendet += 1
            zielordner = ort.ordner
        elif haupt["zielpfad"]:
            # Hauptdatei schon analysiert: neue Mitglieder erben ihre Werte.
            werte = dict(
                kamera=haupt["kamera"], kamera_modell=haupt["kamera_modell"],
                aufnahme_zeit=haupt["aufnahme_zeit"], datum_quelle=haupt["datum_quelle"] or 0,
                datum_sicher=haupt["datum_sicher"] or 0, datum_hinweis=haupt["datum_hinweis"],
            )
            zielordner = Path(db.text_pfad(haupt["zielpfad"])).parent
        else:
            # Hauptdatei hat keinen Zielpfad (Status fehler): Ein neues
            # Mitglied darf nicht "analysiert" ohne Ziel werden.
            grund = f"{GRUND_HAUPTDATEI}: {haupt['fehlergrund'] or haupt['status']}"
            _gruppe_fehler(g, nach_name, dbank, grund, ergebnis, anzeige)
            continue

        ergebnis.gruppen += 1
        offen = 0
        for n in g.alle:
            z = nach_name[n]
            # Wird die Hauptdatei neu analysiert, ziehen bereits analysierte,
            # noch nicht kopierte Mitglieder mit (SPEC §3: wandern gemeinsam).
            mitziehen = haupt_neu and z["status"] == "analysiert"
            if not (_leer(z) or mitziehen):
                continue
            dbank.analyse_setzen(
                z["quellpfad"], gruppe=haupt["quellpfad"],
                zielpfad=(zielordner / n) if zielordner is not None else "",
                **werte,
            )
            ergebnis.bearbeitet += 1
            if _leer(z):
                offen += 1
        anzeige.weiter(offen)


def zielpfad_aus_zeile(struktur, zeile, konf) -> Path:
    """Zielpfad einer analysierten Zeile aus ihren gespeicherten Feldern neu
    berechnen (Kamera, Aufnahmezeit, Datumsquelle, Sicherheit, Hinweis).

    Gebraucht, wenn eine Datei nach fehlgeschlagener Pruefung neu kopiert
    werden muss: Ihr zielpfad zeigt dann auf die fehlerhafte Zieldatei oder
    die Partnerdatei eines Duplikats, nicht mehr auf den berechneten Namen.
    Braucht kein ExifTool - die Metadaten stehen in der Zeile.
    """
    zeit = None
    if zeile["aufnahme_zeit"]:
        from datetime import datetime

        zeit = datetime.strptime(zeile["aufnahme_zeit"], "%Y-%m-%dT%H:%M:%S")
    d = datum_modul.Datum(zeit, int(zeile["datum_quelle"] or 0), bool(zeile["datum_sicher"]),
                          zeile["datum_hinweis"] or "")
    name = Path(db.text_pfad(zeile["quellpfad"])).name
    pfad, _ort = ziel_modul.zielpfad(struktur, d, zeile["kamera"] or konf.wert("kamera.unbekannt"), name, konf)
    return pfad


def _fehler_setzen(dbank, quellpfad, grund: str, gruppe) -> None:
    dbank.analyse_setzen(
        quellpfad, kamera="", kamera_modell="", aufnahme_zeit="", datum_quelle=0,
        datum_sicher=0, datum_hinweis="", gruppe=gruppe, zielpfad="",
        status="fehler", fehlergrund=grund,
    )


def _gruppe_fehler(g, nach_name, dbank, grund, ergebnis, anzeige) -> None:
    n_offen = 0
    for n in g.alle:
        z = nach_name[n]
        if not _leer(z):
            continue
        dbank.analyse_setzen(
            z["quellpfad"], kamera="", kamera_modell="", aufnahme_zeit="", datum_quelle=0,
            datum_sicher=0, datum_hinweis="", gruppe=nach_name[g.haupt]["quellpfad"],
            zielpfad="", status="fehler", fehlergrund=grund,
        )
        ergebnis.fehler += 1
        ergebnis.bearbeitet += 1
        n_offen += 1
    anzeige.weiter(n_offen)


# ----------------------------------------------------------- Fortschritt ----


class _Anzeige:
    """Fortschritt: Balken im Terminal, sonst hoechstens alle 5 s eine Zeile."""

    def __init__(self, konsole, gesamt: int) -> None:
        self.konsole = konsole
        self.gesamt = gesamt
        self.bisher = 0
        self._seit = 0
        self._zuletzt = time.monotonic()
        self.balken = None
        self.aufgabe = None
        if konsole is not None and getattr(konsole, "is_terminal", False):
            from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

            self.balken = Progress(
                TextColumn("{task.description}"), BarColumn(bar_width=None),
                TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(),
                console=konsole, refresh_per_second=4, transient=True,
            )
            self.aufgabe = self.balken.add_task(meldungen.analyse_laeuft(0, gesamt), total=gesamt or None)
            self.balken.start()

    def weiter(self, n: int) -> None:
        if n <= 0:
            return
        self.bisher += n
        self._seit += n
        if self.balken is not None:
            if self._seit >= _ANZEIGE_ALLE:
                self.balken.update(self.aufgabe, advance=self._seit,
                                   description=meldungen.analyse_laeuft(self.bisher, self.gesamt))
                self._seit = 0
        elif self.konsole is not None:
            jetzt = time.monotonic()
            if jetzt - self._zuletzt >= _STILLE_SEKUNDEN:
                self._zuletzt = jetzt
                self.konsole.print(meldungen.analyse_laeuft(self.bisher, self.gesamt))

    def stop(self) -> None:
        if self.balken is not None:
            self.balken.stop()
