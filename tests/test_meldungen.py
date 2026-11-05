"""Tests fuer meldungen.py - alle deutschen Texte an einer Stelle."""

from __future__ import annotations

from pathlib import Path

import pytest

from fotosort import meldungen

# Die Namen, auf die sich die uebrigen Module verlassen.
PFLICHT = [
    "exiftool_fehlt",
    "quelle_gleich_ziel",
    "ziel_in_quelle",
    "quelle_in_ziel",
    "datenbank_auf_netzlaufwerk",
    "archiv_id_kaputt",
    "archiv_id_angelegt",
    "datenbank_fehlt_sicherung_da",
    "datenbank_fehlt_keine_sicherung",
    "config_erzeugt",
    "config_aus_ziel_uebernommen",
    "config_unbekannte_werte",
    "ziel_fehlt",
    "quelle_fehlt",
    "quelle_existiert_nicht",
    "ziel_index_ergebnis",
    "wiederherstellen_fertig",
    "editor_nicht_gefunden",
    "groesse",
    "anzahl",
]


@pytest.mark.parametrize("name", PFLICHT)
def test_pflichtfunktion_vorhanden(name):
    assert callable(getattr(meldungen, name))


@pytest.mark.parametrize(
    "n,erwartet",
    [(0, "0"), (7, "7"), (999, "999"), (1234, "1.234"), (1234567, "1.234.567")],
)
def test_anzahl_mit_punkt_als_tausendertrenner(n, erwartet):
    assert meldungen.anzahl(n) == erwartet


@pytest.mark.parametrize(
    "bytes_,erwartet",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1,0 KB"),
        (1536, "1,5 KB"),
        (1024 * 1024, "1,0 MB"),
        (int(1.2 * 1024**3), "1,2 GB"),
        (5 * 1024**4, "5,0 TB"),
    ],
)
def test_groesse_mit_komma_als_dezimaltrenner(bytes_, erwartet):
    assert meldungen.groesse(bytes_) == erwartet


def test_alle_texte_sind_deutsch_und_nicht_leer():
    texte = [
        meldungen.exiftool_fehlt(),
        meldungen.quelle_gleich_ziel("/a"),
        meldungen.ziel_in_quelle("/a/b"),
        meldungen.quelle_in_ziel("/a/b"),
        meldungen.datenbank_auf_netzlaufwerk("/netz", "cifs"),
        meldungen.archiv_id_kaputt("/a/id.txt", "quatsch"),
        meldungen.archiv_id_angelegt("a" * 32, "/a/id.txt"),
        meldungen.datenbank_fehlt_sicherung_da("/ziel"),
        meldungen.datenbank_fehlt_keine_sicherung("/ziel"),
        meldungen.config_erzeugt("/a/config.toml"),
        meldungen.config_aus_ziel_uebernommen("/a/config.toml"),
        meldungen.config_unbekannte_werte(["ordner.vorlaage"], "/a/config.toml"),
        meldungen.ziel_fehlt(),
        meldungen.quelle_fehlt(),
        meldungen.quelle_existiert_nicht("/gibt/es/nicht"),
        meldungen.wiederherstellen_keine_sicherung("/z/.fotosortierer/fotosort.db.sicherung", "/z"),
        meldungen.datenbank_neu_fuer_neuaufbau("/a/fotosort.db"),
        meldungen.editor_nicht_gefunden("/a/config.toml"),
    ]
    for text in texte:
        assert isinstance(text, str)
        assert text.strip()


def test_exiftool_meldung_nennt_beide_wege():
    text = meldungen.exiftool_fehlt("/usr/bin/exiftool")
    assert "FOTOSORT_EXIFTOOL" in text
    assert "exiftool_pfad" in text
    assert "/usr/bin/exiftool" in text


def test_archiv_id_kaputt_nennt_datei_und_inhalt():
    text = meldungen.archiv_id_kaputt("/z/.fotosortierer/archiv-id.txt", "hallo")
    assert "/z/.fotosortierer/archiv-id.txt" in text
    assert "hallo" in text


def test_datenbank_fehlt_weist_auf_wiederherstellen_hin():
    assert "wiederherstellen" in meldungen.datenbank_fehlt_sicherung_da("/z")
    assert "ziel-index" in meldungen.datenbank_fehlt_keine_sicherung("/z")


def test_wiederherstellen_meldungen_nennen_die_naechsten_schritte():
    text = meldungen.wiederherstellen_lokale_da("/a/fotosort.db", "Lauf 3: fotosort pruefen", "/z/sicherung", "Lauf 2: fotosort kopieren")
    assert "--ersetzen" in text and "Lauf 3" in text and "Lauf 2" in text and "nicht geloescht" in text
    text = meldungen.wiederherstellen_sicherung_kaputt("/z/sicherung", "file is not a database")
    assert "--vorheriger-stand" in text and "ziel-index --neu-aufbauen" in text and "nichts veraendert" in text
    assert "ziel-index --neu-aufbauen" in meldungen.datenbank_schema_veraltet("/a/fotosort.db", 5, 6)


def test_ziel_index_ergebnis_zaehlt_alles_auf():
    from fotosort.zielindex import Ergebnis

    e = Ergebnis(geplant=12, geplant_bytes=3000, gehasht=10, uebernommen=2, entfernt=1, fehler=0,
                 verknuepfungen=1, part_dateien=1, bytes_gelesen=2500, sekunden=2.0, hash_worker=4, profil="hdd")
    text = meldungen.ziel_index_ergebnis(e)
    assert "vollstaendig gelesen:        10" in text
    assert "uebernommen: 2" in text and "ohne Datei entfernt: 1" in text
    assert "Verknuepfungen nicht verfolgt: 1" in text and ".part-Dateien uebergangen:   1" in text
    assert "nichts geloescht" in text


def test_config_unbekannte_werte_nennt_alle_namen():
    text = meldungen.config_unbekannte_werte(["a.b", "c"], "/x/config.toml")
    assert "a.b" in text and "c" in text and "/x/config.toml" in text


def test_status_phase_folgt_der_regel_aus_der_spec():
    """Seit v0.14 (SPEC §8): die Phase des naechsten Schritts mit Arbeit."""
    assert "1 - Scan" in meldungen.status_phase_schritt("scan")
    assert "2 - Analyse" in meldungen.status_phase_schritt("analyse")
    assert "3 - Kopieren" in meldungen.status_phase_schritt("kopieren")
    assert "abgebrochen" in meldungen.status_phase_schritt("kopieren", abgebrochen=True)
    assert "4 - Pruefen" in meldungen.status_phase_schritt("pruefen")
    assert "5 - Quelle aufraeumen" in meldungen.status_phase_schritt("aufraeumen")
    assert "Alles erledigt" in meldungen.status_phase_schritt("fertig")


def test_durchsatz_und_dauer():
    assert "Dateien/s" in meldungen.durchsatz(100, 1024, 1.0)
    assert "MB/s" in meldungen.durchsatz(100, 1024, 1.0)
    assert meldungen.dauer(0.5) == "0,5 s"
    assert meldungen.dauer(90) == "1 min 30 s"
    assert meldungen.dauer(3661) == "1 h 1 min 1 s"


@pytest.mark.parametrize("bearbeitet, sekunden, erwartet", [
    (21, 0.7, "30,0 Dateien/s"),
    (299, 10.0, "29,9 Dateien/s"),
    (123456, 100.0, "1.234,6 Dateien/s"),  # mit Tausenderpunkt wie alle Zahlen
])
def test_durchsatz_der_analyse_mit_deutschem_komma(bearbeitet, sekunden, erwartet):
    # Im Paketlauf von v0.6 stand "29.9 Dateien/s" - mit Punkt statt Komma.
    from fotosort.analyse import Ergebnis

    text = meldungen.analyse_ergebnis(Ergebnis(bearbeitet=bearbeitet, sekunden=sekunden))
    zeile = next(z for z in text.splitlines() if "Durchsatz" in z)
    assert zeile.endswith(" " + erwartet), zeile


# ----------------------------------------- Neue Texte aus der Abnahme ----


def test_status_phase_ohne_arbeit_aber_mit_dateien():
    """Stehen alle Dateien in einem Endzustand (uebersprungen, verschoben ...),
    ist nicht "Scan offen", sondern alles erledigt (Befund F8, v0.14)."""
    assert "keine Dateien erfasst" in meldungen.status_phase_schritt("scan")
    fertig = meldungen.status_phase_schritt("fertig")
    assert "keine Dateien erfasst" not in fertig and "Scan offen" not in fertig


def test_scan_besonderheiten_nennt_nicht_lesbare_ordner():
    text = meldungen.scan_besonderheiten(1, 0, 0, 0, 0, 0, 0, 0, ordner_nicht_lesbar=2)
    assert "Ordner nicht lesbar" in text
    assert "2" in text


def test_scan_besonderheiten_sagt_wenn_verschwundene_nicht_geprueft_wurden():
    text = meldungen.scan_besonderheiten(
        1, 0, 0, 0, 0, 0, 0, 0, ordner_nicht_lesbar=1, verschwunden_ausgewertet=False
    )
    assert "nicht geprueft" in text


def test_ordner_nicht_lesbar_nennt_pfade_und_folgen():
    text = meldungen.scan_ordner_nicht_lesbar(3, ["/q/a", "/q/b"])
    assert "/q/a" in text and "/q/b" in text
    assert "1 weitere" in text
    assert "Der Scan ist damit nicht" in text


def test_archiv_belegt_nennt_den_pfad():
    text = meldungen.archiv_belegt("/archiv/abc")
    assert "laeuft bereits ein Vorgang" in text
    assert "/archiv/abc" in text


def test_config_kaputt_nennt_datei_zeile_und_spalte():
    text = meldungen.config_kaputt("/a/config.toml", 121, 11, "Invalid value")
    assert "/a/config.toml" in text
    assert "Zeile 121" in text
    assert "Spalte 11" in text
    assert "unveraendert" in text


def test_config_falscher_typ_nennt_schluessel_gefunden_und_erwartet():
    text = meldungen.config_falscher_typ(
        "quelle.ausschlussmuster", "Zeichenkette", "Liste", "/a/config.toml"
    )
    assert "quelle.ausschlussmuster" in text
    assert "Zeichenkette" in text
    assert "Liste" in text


def test_ziel_wird_nicht_angelegt_nennt_den_schalter():
    text = meldungen.ziel_wird_nicht_angelegt("/z/vertippt")
    assert "--ziel-anlegen" in text
    assert "/z/vertippt" in text


def test_system_fehler_nennt_pfad_und_grund():
    text = meldungen.system_fehler("/q/gesperrt", "Permission denied")
    assert "/q/gesperrt" in text
    assert "Permission denied" in text


def test_exiftool_texte_nennen_die_gruppe_in_klammern():
    # Die Gruppenangabe darf nicht aus der Ausgabe verschwinden.
    assert "[leistung]" in meldungen.exiftool_fehlt("/x")
    assert "[leistung]" in meldungen.exiftool_hinweis("/x")
    assert "[datenbank]" in meldungen.datenbank_auf_netzlaufwerk("/n", "cifs")


def test_eine_datei_heisst_datei():
    """Befund F16 (v0.14): "1 Dateien", "1 Quellen". Eine Zahl vor „Dateien“
    oder „Quellen“ laeuft ueber n_dateien/n_quellen - ausser nach „von“ oder
    „/“ (1 von 3 Dateien). Das Verb richtet sich nach der Zahl."""
    import re
    text = Path(meldungen.__file__).read_text(encoding="utf-8")
    roh = re.findall(r"(?<!von )(?<!/)\{anzahl\([^)]*\)\} (?:Dateien|Quellen)\b", text)
    assert roh == []
    assert meldungen.n_dateien(1) == "1 Datei" and meldungen.n_dateien(1234) == "1.234 Dateien"
    assert meldungen.n_quellen(1) == "1 Quelle" and meldungen.n_quellen(2) == "2 Quellen"
    assert meldungen.ob_analyse_text(1) == "1 Datei wartet auf die Analyse."
    assert meldungen.ob_analyse_text(2) == "2 Dateien warten auf die Analyse."
    assert meldungen.ob_kopieren_text(1, 10, False).startswith("1 Datei (10 B) wird ins Archiv kopiert.")
    assert meldungen.ob_pruefen_text(3, 10).startswith("3 Dateien (10 B) werden")
    assert "1 Datei, die beim Aufräumen" in meldungen.ob_frage_zuruecklegen(1) and "kommt an" in meldungen.ob_frage_zuruecklegen(1)
