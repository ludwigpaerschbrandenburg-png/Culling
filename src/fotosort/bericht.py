"""Bericht als Text und CSV (SPEC Abschnitt 10).

Alles, was der Bericht nennt, kommt aus der Datenbank (Tabellen dateien,
lauf_ereignisse, laeufe, quellen); nichts wird nur im Speicher gehalten.
Die Dateien landen im Ziel unter .fotosortierer/berichte/:

  bericht_<Zeit>_lauf<N>.txt             lesbarer Bericht
  bericht_<Zeit>_lauf<N>_dateien.csv     eine Zeile je Datei
  bericht_<Zeit>_lauf<N>_ereignisse.csv  eine Zeile je Ereignis

CSV mit Semikolon und UTF-8 mit Kennzeichen (BOM), damit Excel unter
Windows die Datei direkt richtig oeffnet.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from . import db, meldungen
from .analyse import ART_ZIELORDNER_MEHRDEUTIG, GRUND_SIDECAR_OHNE_HAUPT
from .datum import HINWEIS_OHNE_UHRZEIT, HINWEIS_ZEITZONE
from .kopieren import (ART_ANGEFANGENE_ENTFERNT, ART_DUPLIKAT, ART_EXFAT_RUECKFALL,
                       ART_NACHTRAEGLICH_BESTAETIGT, ART_NAMENSKONFLIKT, ART_PART_AUFGERAEUMT)
from .pruefen import ART_PRUEFUNG_FEHLGESCHLAGEN
from .scan import (ART_AUSGESCHLOSSEN, ART_INS_ZIEL, ART_NICHT_MEHR_VORHANDEN, ART_ORDNER_NICHT_LESBAR,
                   ART_QUELLE_ABGELEHNT, ART_QUELLE_NICHT_ERREICHBAR, ART_QUELLE_VERAENDERT, ART_VERKNUEPFUNG)

# Ereignisarten der Phase 5 (aufraeumen). Hier benannt, damit der Bericht
# sie kennt; geschrieben werden sie erst dort.
ART_QUELLE_SEIT_KOPIEREN_GEAENDERT = "quelle_seit_kopieren_geaendert"
ART_LOESCHUNG_VERWEIGERT = "loeschung_verweigert"
ART_REST_NICHT_ENTFERNT = "rest_nicht_entfernt"
ART_QUELLE_GELOESCHT = "quelle_geloescht"
ART_QUELLE_IN_PAPIERKORB = "quelle_in_geloescht_ordner"
ART_LEERER_ORDNER_ENTFERNT = "leerer_ordner_entfernt"

BERICHTE_ORDNER = "berichte"
CSV_TRENNER = ";"
CSV_KODIERUNG = "utf-8-sig"

DATEI_SPALTEN = (
    "quellwurzel", "quellpfad", "status", "dateityp", "groesse", "mtime", "kamera", "kamera_modell",
    "aufnahme_zeit", "datum_quelle", "datum_sicher", "datum_hinweis", "gruppe", "zielpfad",
    "hash", "fehlergrund", "bestaetigt_in_lauf", "kopiert_in_lauf", "gefunden_in_lauf",
    "zuletzt_gesehen_in_lauf",
)
EREIGNIS_SPALTEN = ("lauf_nummer", "art", "pfad", "anzahl", "text")


def berichte_ordner(ziel: Path) -> Path:
    return Path(ziel) / db.ARCHIV_UNTERORDNER / BERICHTE_ORDNER


def schreiben(ziel: Path, dbank: db.Datenbank, lauf: int | None = None,
              jetzt: datetime | None = None) -> tuple[Path, Path, Path]:
    """Alle drei Dateien schreiben; liefert (txt, dateien.csv, ereignisse.csv)."""
    jetzt = jetzt or datetime.now()
    ordner = berichte_ordner(ziel)
    ordner.mkdir(parents=True, exist_ok=True)
    stamm = f"bericht_{jetzt.strftime('%Y-%m-%d_%H%M%S')}" + (f"_lauf{lauf}" if lauf else "")
    txt = ordner / f"{stamm}.txt"
    csv_dateien = ordner / f"{stamm}_dateien.csv"
    csv_ereignisse = ordner / f"{stamm}_ereignisse.csv"

    txt.write_text(text(ziel, dbank, jetzt), encoding="utf-8")
    with open(csv_dateien, "w", encoding=CSV_KODIERUNG, newline="") as f:
        w = csv.writer(f, delimiter=CSV_TRENNER)
        w.writerow(DATEI_SPALTEN)
        for z in dbank.dateien_liste():
            w.writerow([_csv_wert(z[s]) for s in DATEI_SPALTEN])
    with open(csv_ereignisse, "w", encoding=CSV_KODIERUNG, newline="") as f:
        w = csv.writer(f, delimiter=CSV_TRENNER)
        w.writerow(EREIGNIS_SPALTEN)
        for z in dbank.ereignisse_liste():
            w.writerow([_csv_wert(z[s]) for s in EREIGNIS_SPALTEN])
    return txt, csv_dateien, csv_ereignisse


def _csv_wert(wert):
    if wert is None:
        return ""
    if isinstance(wert, float):
        return f"{wert:.3f}"
    return db.text_pfad(wert) if isinstance(wert, str) else wert


# ------------------------------------------------------------- Text -----


def text(ziel: Path, dbank: db.Datenbank, jetzt: datetime | None = None) -> str:
    jetzt = jetzt or datetime.now()
    z = []  # Zeilen
    z.append("Bericht fotosort")
    z.append(f"  Ziel:           {ziel}")
    try:
        z.append(f"  Archiv-Kennung: {db.archiv_id_datei(ziel).read_text(encoding='utf-8').strip()}")
    except OSError:
        pass
    z.append(f"  Erstellt:       {jetzt.strftime('%Y-%m-%d %H:%M:%S')}")
    z.append("")

    # Quellen
    z.append("Quellen")
    for q in dbank.quellen_liste():
        stand = "erreichbar" if q["erreichbar"] else "beim letzten Scan nicht erreichbar"
        z.append(f"  {q['wurzel']}  ({stand})")
    abgelehnt = dbank.ereignisse_liste(ART_QUELLE_ABGELEHNT)
    nicht_erreichbar = dbank.ereignisse_liste(ART_QUELLE_NICHT_ERREICHBAR)
    if abgelehnt:
        z.append("  Abgelehnte Quellen (Ueberschneidung, siehe Ereignisse):")
        for e in abgelehnt:
            z.append(f"    Lauf {e['lauf_nummer']}: {e['pfad']}  {e['text']}")
    if nicht_erreichbar:
        z.append("  Nicht erreichbare Quellen (je Lauf):")
        for e in nicht_erreichbar:
            z.append(f"    Lauf {e['lauf_nummer']}: {e['pfad']}")
    z.append("")

    # Zahlen je Quelle und gesamt
    zahlen = dbank.bericht_zahlen()
    z.append("Zahlen je Quelle und gesamt")
    kopf = f"  {'':<10}{'gefunden':>10}{'kopiert':>10}{'verschoben':>11}{'geprueft':>10}{'Duplikate':>11}{'ohne Datum':>11}{'Fehler':>8}{'geloescht':>11}"
    z.append(kopf)
    for wurzel in sorted(k for k in zahlen if k != "gesamt") + ["gesamt"]:
        n = zahlen[wurzel]
        if wurzel != "gesamt":
            z.append(f"  {wurzel}")
        name = "gesamt" if wurzel == "gesamt" else ""
        z.append(
            f"  {name:<10}{meldungen.anzahl(n['gefunden']):>10}{meldungen.anzahl(n['kopiert']):>10}"
            f"{meldungen.anzahl(n['verschoben']):>11}{meldungen.anzahl(n['geprueft']):>10}"
            f"{meldungen.anzahl(n['duplikate']):>11}{meldungen.anzahl(n['ohne_datum']):>11}"
            f"{meldungen.anzahl(n['fehler']):>8}{meldungen.anzahl(n['geloescht']):>11}"
            f"   ({meldungen.groesse(n['bytes'])})"
        )
    z.append("")

    # Laeufe: Dauer und Durchsatz je Phase
    z.append("Laeufe (Dauer und Durchsatz je Phase)")
    for l in dbank.laeufe_liste():
        zusammen = {}
        if l["zusammenfassung"]:
            try:
                zusammen = json.loads(l["zusammenfassung"])
            except ValueError:
                zusammen = {}
        ende = l["ende"] or "nicht beendet (abgebrochen oder abgestuerzt)"
        z.append(f"  Lauf {l['nummer']}: {l['befehl']}")
        z.append(f"    Start {l['start']}  Ende {ende}")
        if zusammen:
            dateien = int(zusammen.get("dateien", 0))
            bytes_ = int(zusammen.get("bytes", 0))
            sekunden = float(zusammen.get("sekunden", 0.0))
            z.append(
                f"    {meldungen.anzahl(dateien)} Dateien, {meldungen.groesse(bytes_)},"
                f" Dauer {meldungen.dauer(sekunden)}, Durchsatz {meldungen.durchsatz(dateien, bytes_, sekunden)}"
            )
    z.append("")

    # Listen aus der Tabelle dateien
    _liste(z, "Fehler (mit Grund)", dbank.dateien_liste("status = 'fehler'"),
           lambda r: f"{r['quellpfad']}  —  {r['fehlergrund']}")
    _ereignis_liste(z, "Umbenennungen wegen Namenskonflikt (Quelle -> Ziel)", dbank.ereignisse_liste(ART_NAMENSKONFLIKT),
                    lambda e: f"{e['pfad']}  ->  {e['text']}")
    _liste(z, "Duplikate mit Partnerdatei im Ziel (nicht kopiert)",
           dbank.dateien_liste("status IN ('duplikat', 'duplikat_bestaetigt')"),
           lambda r: f"{r['quellpfad']}  ->  {r['zielpfad']}  [{r['status']}]")
    _liste(z, "Durch Umbenennen verschoben (Status verschoben)", dbank.dateien_liste("status = 'verschoben'"),
           lambda r: f"{r['quellpfad']}  ->  {r['zielpfad']}")
    _liste(z, "Ohne sicheres Datum (nur Aenderungsdatum)",
           dbank.dateien_liste("datum_sicher = 0 AND dateityp IN ('foto','raw','video','sidecar')"
                               " AND status NOT IN ('gefunden','uebersprungen','fehler')"),
           lambda r: f"{r['quellpfad']}  ->  {r['zielpfad']}")
    _liste(z, "Zeitzone angenommen (Video ohne Zeitzonen-Offset)",
           dbank.dateien_liste("datum_hinweis = ?", (HINWEIS_ZEITZONE,)),
           lambda r: f"{r['quellpfad']}  ({r['aufnahme_zeit']})")
    ohne_uhrzeit = sum(1 for _ in dbank.dateien_liste("datum_hinweis = ?", (HINWEIS_OHNE_UHRZEIT,)))
    z.append(f"Datum aus dem Dateinamen ohne Uhrzeit (Tagesgrenze nicht angewendet): {meldungen.anzahl(ohne_uhrzeit)}")
    z.append("")

    # Listen aus den Ereignissen
    _ereignis_liste(z, "QUELLE SEIT DEM KOPIEREN GEAENDERT - nicht geloescht, wird neu kopiert",
                    dbank.ereignisse_liste(ART_QUELLE_SEIT_KOPIEREN_GEAENDERT), lambda e: f"{e['pfad']}  {e['text']}")
    _ereignis_liste(z, "Quelle veraendert, wird neu eingeordnet (zweiter Scan)",
                    dbank.ereignisse_liste(ART_QUELLE_VERAENDERT), lambda e: f"Lauf {e['lauf_nummer']}: {e['pfad']}")
    _ereignis_liste(z, "Quelle nicht mehr vorhanden",
                    dbank.ereignisse_liste(ART_NICHT_MEHR_VORHANDEN), lambda e: f"Lauf {e['lauf_nummer']}: {e['pfad']}")
    _ereignis_liste(z, "Loeschung verweigert (mit Grund)",
                    dbank.ereignisse_liste(ART_LOESCHUNG_VERWEIGERT), lambda e: f"{e['pfad']}  —  {e['text']}")
    _ereignis_liste(z, "Pruefung fehlgeschlagen (Zieldatei | Grund)",
                    dbank.ereignisse_liste(ART_PRUEFUNG_FEHLGESCHLAGEN), lambda e: f"{e['pfad']}  —  {e['text']}")
    _ereignis_liste(z, "Geloeschte Quelldateien",
                    dbank.ereignisse_liste(ART_QUELLE_GELOESCHT), lambda e: f"Lauf {e['lauf_nummer']}: {e['pfad']}")
    _ereignis_liste(z, "In den Ordner _geloescht_ verschobene Quelldateien",
                    dbank.ereignisse_liste(ART_QUELLE_IN_PAPIERKORB), lambda e: f"Lauf {e['lauf_nummer']}: {e['pfad']}  ->  {e['text']}")
    _ereignis_liste(z, "Entfernte leere Ordner",
                    dbank.ereignisse_liste(ART_LEERER_ORDNER_ENTFERNT), lambda e: f"Lauf {e['lauf_nummer']}: {e['pfad']}")
    _ereignis_liste(z, "Reste-Dateien nicht entfernt (stehen mit echtem Dateityp in der Datenbank)",
                    dbank.ereignisse_liste(ART_REST_NICHT_ENTFERNT), lambda e: f"{e['pfad']}")
    _liste(z, "Sidecars ohne Hauptdatei (uebersprungen)",
           dbank.dateien_liste("status = 'uebersprungen' AND fehlergrund = ?", (GRUND_SIDECAR_OHNE_HAUPT,)),
           lambda r: f"{r['quellpfad']}")
    _ereignis_liste(z, "Uebersprungen, weil der Pfad ins Ziel zeigt",
                    dbank.ereignisse_liste(ART_INS_ZIEL), lambda e: f"Lauf {e['lauf_nummer']}: {e['pfad']}")
    _ereignis_liste(z, "Zielordner mehrdeutig (alphabetisch erster gewaehlt)",
                    dbank.ereignisse_liste(ART_ZIELORDNER_MEHRDEUTIG), lambda e: f"{e['pfad']}")

    summen = dbank.ereignisse_summen()
    z.append("Weitere Zaehler (alle Laeufe)")
    z.append(f"  Ordner-Verknuepfungen nicht verfolgt:     {meldungen.anzahl(summen.get(ART_VERKNUEPFUNG, 0))}")
    z.append(f"  Nach Ausschlussmuster uebersprungen:      {meldungen.anzahl(summen.get(ART_AUSGESCHLOSSEN, 0))}")
    z.append(f"  Ordner nicht lesbar:                      {meldungen.anzahl(summen.get(ART_ORDNER_NICHT_LESBAR, 0))}")
    z.append(f"  Rueckfall auf Kopieren statt Umbenennen:  {meldungen.anzahl(summen.get(ART_EXFAT_RUECKFALL, 0))}")
    z.append(f"  Duplikate erkannt (Ereignisse):           {meldungen.anzahl(summen.get(ART_DUPLIKAT, 0))}")
    z.append(f"  Reste abgebrochener Laeufe (.part):       {meldungen.anzahl(summen.get(ART_PART_AUFGERAEUMT, 0))}")
    z.append(f"  Angefangene Zieldateien entfernt:         {meldungen.anzahl(summen.get(ART_ANGEFANGENE_ENTFERNT, 0))}")
    z.append(f"  Kopien nachtraeglich bestaetigt:          {meldungen.anzahl(summen.get(ART_NACHTRAEGLICH_BESTAETIGT, 0))}")
    return "\n".join(z) + "\n"


def _liste(z: list[str], titel: str, zeilen, form) -> None:
    eintraege = [form(r) for r in zeilen]
    z.append(f"{titel}: {meldungen.anzahl(len(eintraege))}")
    for e in eintraege:
        z.append(f"  {e}")
    z.append("")


def _ereignis_liste(z: list[str], titel: str, ereignisse, form) -> None:
    _liste(z, titel, ereignisse, form)
