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
ART_GRUPPE_GETRENNT = "gruppe_getrennt"       # SPEC §3 seit v0.8
ART_DATUM_AUFFAELLIG = "datum_auffaellig"
ART_NUR_HERSTELLER = "nur_hersteller"
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
    getrennt: int = 0                # Gruppen, die nach Aufnahmezeit getrennt wurden (v0.8)
    auffaellig: int = 0              # "Datum auffaellig" (v0.8)
    nur_hersteller: int = 0          # Hersteller ohne Modell (v0.8)
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


#: Status, in denen eine Datei schon im Ziel liegt oder gerade dorthin geht:
#: Sie bleibt, wo sie ist; ihre gespeicherten Werte zaehlen fuer die Gruppe.
_FEST = frozenset({"kopieren_laeuft", "kopiert", "geprueft", "verschoben", "duplikat",
                   "duplikat_bestaetigt", "quelle_geloescht"})
_OFFEN = ("gefunden", "analysiert")


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
            if not any(_leer(nach_name[n]) for n in (g.haupt, *g.mitglieder)):
                continue  # nur neue Sidecars: Sie erben, gelesen wird nichts
            # Die Gruppe wird neu bestimmt: Jedes offene Mitglied wird selbst
            # gelesen (SPEC §3 seit v0.8: nach Aufnahmezeit aufteilen), dazu die
            # Sidecars, die ein Datum tragen koennen (Sony-XML, .xmp).
            for n in (g.haupt, *g.mitglieder):
                z = nach_name[n]
                pfad = db.text_pfad(z["quellpfad"])
                if z["status"] in _OFFEN and not metadaten.unzulaessig_fuer_exiftool(pfad):
                    zu_lesen.append((pfad, z["dateityp"]))
            for s in g.sidecars:
                s_pfad = db.text_pfad(nach_name[s]["quellpfad"])
                if s.lower().endswith((".xml", ".xmp")) and not metadaten.unzulaessig_fuer_exiftool(s_pfad):
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

    for _o, g, nach_name in aufgaben:
        if any(_leer(nach_name[n]) for n in (g.haupt, *g.mitglieder)):
            _gruppe_bestimmen(g, nach_name, felder_von, struktur, konf, dbank, lauf, ergebnis, anzeige)
        else:
            _sidecars_erben(g, nach_name, konf, dbank, ergebnis, anzeige)


def _felder(nach_name, name, felder_von) -> dict | None:
    return felder_von.get(metadaten.schluessel(db.text_pfad(nach_name[name]["quellpfad"])))


def _sidecar_felder(g, nach_name, felder_von, fuer: str, endung: str, konf) -> dict | None:
    """Felder des ersten gelesenen Sidecars mit dieser Endung, das zu "fuer" gehoert."""
    for s in g.sidecars:
        if s.lower().endswith(endung) and dateitypen.sidecar_gehoert_zu(s, fuer, konf):
            f = _felder(nach_name, s, felder_von)
            if f and not f.get("Error"):
                return f
    return None


def _gruppe_bestimmen(g, nach_name, felder_von, struktur, konf, dbank, lauf, ergebnis, anzeige) -> None:
    """Eine Namensgruppe mit neuen Mitgliedern: jedes Mitglied fuer sich lesen,
    kaputte heraus, nach Aufnahmezeit aufteilen (SPEC §3 seit v0.8), dann je
    Teilgruppe Datum, Kamera und Zielordner bestimmen und schreiben."""
    toleranz = float(konf.wert("datum.gruppe_toleranz_sekunden"))
    mitglieder: list[gruppen.Mitglied] = []
    grund_von: dict[str, str] = {}
    for n in (g.haupt, *g.mitglieder):
        z = nach_name[n]
        if z["status"] in _FEST:
            zeit = None
            if 1 <= int(z["datum_quelle"] or 0) <= 4:
                zeit, _ = ziel_modul.zeit_aus_text(z["aufnahme_zeit"])
            mitglieder.append(gruppen.Mitglied(n, z["dateityp"], zeit, daten=("fest", z)))
            continue
        if z["status"] not in _OFFEN:
            continue  # fehler oder uebersprungen: gehoert nicht mehr dazu
        pfad = db.text_pfad(z["quellpfad"])
        if metadaten.unzulaessig_fuer_exiftool(pfad):
            grund_von[n] = GRUND_ZEILENUMBRUCH
        else:
            felder = _felder(nach_name, n, felder_von)
            if felder is None:
                grund_von[n] = GRUND_METADATEN
            elif felder.get("Error"):
                grund_von[n] = f"{GRUND_METADATEN}: {felder['Error']}"
        if n in grund_von:
            mitglieder.append(gruppen.Mitglied(n, z["dateityp"], kaputt=True, daten=("kaputt", z)))
            continue
        xml = _sidecar_felder(g, nach_name, felder_von, n, ".xml", konf) if z["dateityp"] == dateitypen.VIDEO else None
        if xml and not kamera.rohmodell(felder):
            # Sony-Sidecar kennt das Modell, die Videodatei nicht.
            felder = dict(felder, Model=xml.get("NonRealTimeMetaDeviceModelName", ""))
        xmp = _sidecar_felder(g, nach_name, felder_von, n, ".xmp", konf)
        d = datum_modul.bestimmen(felder, xml, n, z["dateityp"], z["mtime"] or 0.0, konf, xmp_felder=xmp)
        zeit = d.zeit if 1 <= d.quelle <= 4 else None
        mitglieder.append(gruppen.Mitglied(n, z["dateityp"], zeit, daten=("neu", z, d, felder)))
        _hinweise(n, z, d, felder, dbank, lauf, ergebnis)

    teile, kaputte = gruppen.aufteilen(mitglieder, toleranz)
    for m in kaputte:
        z = nach_name[m.name]
        _fehler_setzen(dbank, z["quellpfad"], grund_von[m.name], z["quellpfad"])
        ergebnis.fehler += 1
        ergebnis.bearbeitet += 1
        if _leer(z):
            anzeige.weiter(1)

    # Sidecars zur Teilgruppe ihres besten lesbaren Mitglieds (SPEC §3).
    teil_von = {m.name: i for i, t in enumerate(teile) for m in t}
    sidecars_je_teil: dict[int, list[str]] = {}
    for s in g.sidecars:
        passende = [m for t in teile for m in t if dateitypen.sidecar_gehoert_zu(s, m.name, konf)]
        if passende:
            beste = min(passende, key=gruppen._rang)
            sidecars_je_teil.setdefault(teil_von[beste.name], []).append(s)
            continue
        z = nach_name[s]
        if z["status"] in _OFFEN:
            # Alle Mitglieder, zu denen es gehoert, sind nicht lesbar.
            kaputt = next((m.name for m in kaputte if dateitypen.sidecar_gehoert_zu(s, m.name, konf)), g.haupt)
            grund = grund_von.get(kaputt) or nach_name[kaputt]["fehlergrund"] or nach_name[kaputt]["status"]
            _fehler_setzen(dbank, z["quellpfad"], f"{GRUND_HAUPTDATEI}: {grund}", nach_name[kaputt]["quellpfad"])
            ergebnis.fehler += 1
            ergebnis.bearbeitet += 1
            if _leer(z):
                anzeige.weiter(1)

    for i, teil in enumerate(teile):
        _teil_schreiben(teil, sidecars_je_teil.get(i, []), nach_name, struktur, konf, dbank, lauf, ergebnis, anzeige)
        if i > 0:
            erste, diese = teile[0][0], teil[0]
            ergebnis.getrennt += 1
            dbank.ereignis(lauf, ART_GRUPPE_GETRENNT, nach_name[diese.name]["quellpfad"], len(teil),
                           meldungen.ereignis_gruppe_getrennt(diese.name, diese.zeit, erste.name, teile[0]))


def _hinweise(name, z, d, felder, dbank, lauf, ergebnis) -> None:
    """Datum auffaellig (SPEC §3) und Hersteller ohne Modell - nur Hinweise."""
    grund = datum_modul.auffaellig(d, name, z["mtime"] or 0.0)
    if grund:
        ergebnis.auffaellig += 1
        dbank.ereignis(lauf, ART_DATUM_AUFFAELLIG, z["quellpfad"], 1, grund)
    hersteller = str((felder or {}).get("Make") or "").strip()
    if hersteller and not kamera.rohmodell(felder):
        ergebnis.nur_hersteller += 1
        dbank.ereignis(lauf, ART_NUR_HERSTELLER, z["quellpfad"], 1, hersteller)


def _teil_schreiben(teil, sidecars, nach_name, struktur, konf, dbank, lauf, ergebnis, anzeige) -> None:
    """Eine Teilgruppe: Liegt schon ein Mitglied im Ziel, kommen die anderen
    dazu (Ordner, Gruppe, Anhang). Sonst Datum vom ersten Mitglied mit
    Metadaten-Datum, Kamera von der Hauptdatei oder dem ersten mit Modell."""
    from .kopieren import _anhang_aus_namen, mit_anhang

    fest = [m for m in teil if m.daten[0] == "fest"]
    if fest:
        ref = nach_name[fest[0].name]
        werte = dict(
            kamera=ref["kamera"], kamera_modell=ref["kamera_modell"], aufnahme_zeit=ref["aufnahme_zeit"],
            datum_quelle=ref["datum_quelle"] or 0, datum_sicher=ref["datum_sicher"] or 0,
            datum_hinweis=ref["datum_hinweis"],
        )
        gruppe = ref["gruppe"] or ref["quellpfad"]
        ziel_ref = Path(db.text_pfad(ref["zielpfad"])) if ref["zielpfad"] else None
        stamm = Path(db.text_pfad(gruppe)).stem
        anhang = _anhang_aus_namen(Path(db.text_pfad(ref["quellpfad"])).name, ziel_ref.name, stamm) if ziel_ref else None
        zielordner = ziel_ref.parent if ziel_ref else None

        def zielpfad_von(n: str):
            if zielordner is None:
                return ""
            return mit_anhang(zielordner / n, anhang or 0, stamm)
    else:
        haupt = teil[0]
        anker = next((m for m in teil if m.zeit is not None), haupt)
        d = anker.daten[2]
        kam, roh = kamera.ordnername(haupt.daten[3], konf)
        if not roh:
            for m in teil:
                k2, r2 = kamera.ordnername(m.daten[3], konf)
                if r2:
                    kam, roh = k2, r2
                    break
        _, ort = ziel_modul.zielpfad(struktur, d, kam, haupt.name, konf)
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
        gruppe = nach_name[haupt.name]["quellpfad"]
        zielordner = ort.ordner

        def zielpfad_von(n: str):
            return zielordner / n

    ergebnis.gruppen += 1
    offen = 0
    for n in [m.name for m in teil if m.daten[0] == "neu"] + list(sidecars):
        z = nach_name[n]
        if z["status"] not in _OFFEN:
            continue
        dbank.analyse_setzen(z["quellpfad"], gruppe=gruppe, zielpfad=zielpfad_von(n), **werte)
        ergebnis.bearbeitet += 1
        if _leer(z):
            offen += 1
    anzeige.weiter(offen)


def _sidecars_erben(g, nach_name, konf, dbank, ergebnis, anzeige) -> None:
    """Nur neue Sidecars: Sie gehen zu ihrem besten Mitglied, das schon einen
    Platz hat, und uebernehmen dessen Werte (Ordner, Gruppe, Anhang)."""
    from .kopieren import _anhang_aus_namen, mit_anhang

    kandidaten = [n for n in (g.haupt, *g.mitglieder)
                  if nach_name[n]["status"] not in ("gefunden", "fehler", "uebersprungen") and nach_name[n]["zielpfad"]]
    for s in g.sidecars:
        z = nach_name[s]
        if not _leer(z):
            continue
        passende = [n for n in kandidaten if dateitypen.sidecar_gehoert_zu(s, n, konf)]
        if not passende:
            haupt = nach_name[g.haupt]
            grund = f"{GRUND_HAUPTDATEI}: {haupt['fehlergrund'] or haupt['status']}"
            _fehler_setzen(dbank, z["quellpfad"], grund, haupt["quellpfad"])
            ergebnis.fehler += 1
            ergebnis.bearbeitet += 1
            anzeige.weiter(1)
            continue
        ref = nach_name[min(passende, key=lambda n: gruppen._rang(gruppen.Mitglied(n, nach_name[n]["dateityp"])))]
        gruppe = ref["gruppe"] or ref["quellpfad"]
        stamm = Path(db.text_pfad(gruppe)).stem
        ziel_ref = Path(db.text_pfad(ref["zielpfad"]))
        anhang = _anhang_aus_namen(Path(db.text_pfad(ref["quellpfad"])).name, ziel_ref.name, stamm) or 0
        dbank.analyse_setzen(
            z["quellpfad"], gruppe=gruppe, zielpfad=mit_anhang(ziel_ref.parent / s, anhang, stamm),
            kamera=ref["kamera"], kamera_modell=ref["kamera_modell"], aufnahme_zeit=ref["aufnahme_zeit"],
            datum_quelle=ref["datum_quelle"] or 0, datum_sicher=ref["datum_sicher"] or 0,
            datum_hinweis=ref["datum_hinweis"],
        )
        ergebnis.gruppen += 1
        ergebnis.bearbeitet += 1
        anzeige.weiter(1)


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
