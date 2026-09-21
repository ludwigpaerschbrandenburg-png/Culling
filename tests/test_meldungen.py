"""Tests fuer meldungen.py - alle deutschen Texte an einer Stelle."""

from __future__ import annotations

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
    "noch_nicht_gebaut",
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
        meldungen.noch_nicht_gebaut("analyse", 2),
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


def test_noch_nicht_gebaut_nennt_befehl_und_phase():
    text = meldungen.noch_nicht_gebaut("kopieren", 3)
    assert "kopieren" in text
    assert "Phase 3" in text


def test_config_unbekannte_werte_nennt_alle_namen():
    text = meldungen.config_unbekannte_werte(["a.b", "c"], "/x/config.toml")
    assert "a.b" in text and "c" in text and "/x/config.toml" in text


def test_status_phase_folgt_der_regel_aus_der_spec():
    assert "1" in meldungen.status_phase(None)
    assert "2" in meldungen.status_phase("gefunden")
    assert "3" in meldungen.status_phase("analysiert")
    assert "3" in meldungen.status_phase("kopieren_laeuft")
    assert "4" in meldungen.status_phase("kopiert")
    assert "5" in meldungen.status_phase("geprueft")
    assert "6" in meldungen.status_phase("quelle_geloescht")


def test_durchsatz_und_dauer():
    assert "Dateien/s" in meldungen.durchsatz(100, 1024, 1.0)
    assert "MB/s" in meldungen.durchsatz(100, 1024, 1.0)
    assert meldungen.dauer(0.5) == "0,5 s"
    assert meldungen.dauer(90) == "1 min 30 s"
    assert meldungen.dauer(3661) == "1 h 1 min 1 s"


# ----------------------------------------- Neue Texte aus der Abnahme ----


def test_status_phase_ohne_stufe_aber_mit_dateien():
    ohne = meldungen.status_phase(None, dateien_erfasst=False)
    mit = meldungen.status_phase(None, dateien_erfasst=True)
    assert "keine Dateien erfasst" in ohne
    assert "keine Dateien erfasst" not in mit
    assert "Phase: 1" in mit


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
