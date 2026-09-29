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

from . import FotosortFehler, dateitypen, db, fortschritt, gruppen, kamera, meldungen, metadaten, pfade, steuerung
from . import datum as datum_modul
from . import ziel as ziel_modul

ART_ZIELORDNER_MEHRDEUTIG = "zielordner_mehrdeutig"
GRUND_SIDECAR_OHNE_HAUPT = meldungen.GRUND_SIDECAR_OHNE_HAUPT
GRUND_METADATEN = meldungen.GRUND_METADATEN
GRUND_ZEILENUMBRUCH = meldungen.GRUND_ZEILENUMBRUCH
GRUND_KEIN_UTF8 = meldungen.GRUND_KEIN_UTF8
GRUND_HAUPTDATEI = meldungen.GRUND_HAUPTDATEI

#: Ereignis: eine Zeile mit voruebergehendem Fehler wird erneut versucht.
ART_ERNEUT_VERSUCHT = "neu_nach_fehler"

SEITE = 5000


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
    zeitlimits: int = 0
    abstuerze: int = 0
    erneut_versucht: int = 0         # voruebergehende Fehler frueherer Laeufe
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
    ergebnis.erneut_versucht = _fehler_erneut_versuchen(dbank, lauf)
    if ergebnis.erneut_versucht and konsole is not None:
        konsole.print(meldungen.analyse_erneut_versucht(ergebnis.erneut_versucht))
    gesamt = dbank.anzahl_zu_analysieren()
    anzeige = _Anzeige(konsole, gesamt)

    with metadaten.ExifToolPool(exiftool, ergebnis.prozesse) as pool:
        ab = ""
        # Doppelte Pufferung: Die Stapel der naechsten Seite laufen schon bei
        # ExifTool, waehrend die vorige ausgewertet und geschrieben wird -
        # sonst warten alle Prozesse am Ende jeder Seite.
        vorige: _Seite | None = None
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
                # Ein Ordner, den die vorige Seite schon ganz bearbeitet (er
                # reicht ueber die Seitengrenze), wird nicht ein zweites Mal gelesen.
                schon = vorige.ordner if vorige is not None else set()
                naechste = _seite_vorbereiten([o for o in ordner if o not in schon], trenner, konf, dbank, pool, ergebnis)
                if vorige is not None:
                    _seite_abschliessen(vorige, struktur, konf, dbank, lauf, ergebnis, anzeige)
                vorige = naechste
            if vorige is not None:
                _seite_abschliessen(vorige, struktur, konf, dbank, lauf, ergebnis, anzeige)
        except KeyboardInterrupt:
            ergebnis.abgebrochen = True
        finally:
            ergebnis.zeitlimits = pool.zeitlimits
            ergebnis.abstuerze = pool.abstuerze
            dbank.stapel_schreiben()
            anzeige.stop()

    ergebnis.sekunden = time.monotonic() - begonnen
    return ergebnis


@dataclass
class _Seite:
    """Eine vorbereitete Seite: Gruppen gebildet, Stapel bei ExifTool eingereicht."""
    ordner: set
    aufgaben: list
    ohne_haupt: list
    stapel: list          # (Stapel, Future)


def _seite_bearbeiten(ordner, trenner, struktur, konf, dbank, lauf, pool, ergebnis, anzeige) -> None:
    """Eine Seite am Stueck (ohne Ueberlappung)."""
    seite = _seite_vorbereiten(ordner, trenner, konf, dbank, pool, ergebnis)
    _seite_abschliessen(seite, struktur, konf, dbank, lauf, ergebnis, anzeige)


def _seite_vorbereiten(ordner, trenner, konf, dbank, pool, ergebnis) -> _Seite:
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
    stapel = metadaten.stapel_bilden(zu_lesen)
    ergebnis.stapel += len(stapel)
    return _Seite(set(ordner), aufgaben, ohne_haupt, [(s, pool.einreichen(s)) for s in stapel])


def _seite_abschliessen(seite: _Seite, struktur, konf, dbank, lauf, ergebnis, anzeige) -> None:
    aufgaben, ohne_haupt = seite.aufgaben, seite.ohne_haupt
    felder_von: dict[str, dict] = {}
    for s, zukunft in seite.stapel:
        try:
            felder_von.update(zukunft.result())
        except metadaten.MetadatenFehler as fehler:
            # Der ganze Stapel ist nicht gelesen: Jede Datei bekommt den Grund
            # (Status fehler), damit Bericht und naechster Lauf ihn kennen.
            for pfad, _typ in s:
                felder_von.setdefault(metadaten.schluessel(pfad), {"Error": str(fehler)})

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
                kamera=kam, kamera_modell=roh, aufnahme_zeit=ziel_modul.zeit_text(d.zeit, d.uhrzeit_bekannt),
                datum_quelle=d.quelle, datum_sicher=1 if d.sicher else 0, datum_hinweis=d.hinweis,
            )
            if ort.mehrdeutig:
                ergebnis.mehrdeutig += 1
                if ort.ordner not in ergebnis.mehrdeutig_gemeldet:
                    ergebnis.mehrdeutig_gemeldet.add(ort.ordner)
                    dbank.ereignis(lauf, ART_ZIELORDNER_MEHRDEUTIG, ort.ordner, 1, meldungen.EREIGNIS_ORDNER_MEHRDEUTIG)
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
    zeit, uhrzeit_bekannt = ziel_modul.zeit_aus_text(zeile["aufnahme_zeit"])
    d = datum_modul.Datum(zeit, int(zeile["datum_quelle"] or 0), bool(zeile["datum_sicher"]),
                          zeile["datum_hinweis"] or "", uhrzeit_bekannt=uhrzeit_bekannt)
    name = Path(db.text_pfad(zeile["quellpfad"])).name
    pfad, _ort = ziel_modul.zielpfad(struktur, d, zeile["kamera"] or konf.wert("kamera.unbekannt"), name, konf)
    return pfad


def _voruebergehend(grund: str) -> bool:
    """Liegt der Fehler vermutlich nicht an der Datei? Die Datei war beim Lesen
    nicht da (Karte gezogen, Netz weg), ExifTool ist abgestuerzt, hing oder
    liess sich nicht starten. Ein Fehler, den ExifTool zur Datei selbst meldet
    ("File format error"), bleibt - bis sich die Datei aendert (Scan)."""
    kopf = f"{GRUND_HAUPTDATEI}: "
    if grund.startswith(kopf):
        grund = grund[len(kopf):]
    if grund == GRUND_METADATEN:
        return True
    return grund.startswith(tuple(
        f"{GRUND_METADATEN}: {text}" for text in (
            meldungen.EXIFTOOL_ZEITLIMIT, meldungen.EXIFTOOL_ABGESTUERZT,
            meldungen.EXIFTOOL_STUERZT_WIEDERHOLT, meldungen.EXIFTOOL_NICHT_STARTBAR,
        )
    ))


def _fehler_erneut_versuchen(dbank, lauf: int) -> int:
    """Zeilen mit voruebergehendem Fehler zurueck auf gefunden, wenn ihre
    Quelldatei wieder da ist. Gruppenmitglieder ("Hauptdatei: ...") nur,
    wenn ihre Hauptdatei mitkommt oder nicht mehr auf fehler steht - sonst
    wuerden sie in jedem Lauf nutzlos erneut versucht."""
    zurueck: set[str] = set()
    n = 0

    def zuruecksetzen(z) -> bool:
        try:
            st = os.stat(pfade.lang(Path(db.text_pfad(z["quellpfad"]))))
        except OSError:
            return False
        dbank.zurueck_auf_gefunden(z["quellpfad"], st.st_size, st.st_mtime)
        dbank.ereignis(lauf, ART_ERNEUT_VERSUCHT, z["quellpfad"], 1, z["fehlergrund"])
        return True

    for z in dbank.zeilen_mit_fehlergrund(GRUND_METADATEN):
        if _voruebergehend(z["fehlergrund"]) and zuruecksetzen(z):
            zurueck.add(z["quellpfad"])
            n += 1
    for z in dbank.zeilen_mit_fehlergrund(f"{GRUND_HAUPTDATEI}: "):
        if not _voruebergehend(z["fehlergrund"]):
            continue
        haupt = dbank.zeile(z["gruppe"]) if z["gruppe"] else None
        if z["gruppe"] not in zurueck and (haupt is None or haupt["status"] == "fehler"):
            continue
        if zuruecksetzen(z):
            n += 1
    dbank.stapel_schreiben()
    return n


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


class _Anzeige(fortschritt.Fortschritt):
    """Fortschritt der Analyse wie bei den anderen Phasen: Balken im Terminal
    mit Restzeit (nach der Zahl der Dateien), sonst hoechstens alle 5 s eine
    Zeile; dazu die Meldung an die Oberflaeche (steuerung)."""

    def __init__(self, konsole, gesamt: int) -> None:
        super().__init__(konsole, gesamt, 0, lambda d, g, _b, _gb, _r: meldungen.analyse_laeuft(d, g))

    def weiter(self, n: int, bytes_: int = 0) -> None:
        if n > 0:
            super().weiter(n, 0)
