"""Mehrere Quellen je Archiv (SPEC Abschnitt 4 Phase 1, Abschnitt 6, Abschnitt 8)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import testbaum
from fotosort import FotosortFehler, cli, db, pfade, scan


def _laufen(capsys, *args):
    rueckgabe = cli.main([str(a) for a in args])
    return rueckgabe, capsys.readouterr().out


@pytest.fixture
def zwei_quellen(tmp_path):
    a = testbaum.erzeugen(tmp_path / "baum_a")["quelle"]
    b = testbaum.erzeugen(tmp_path / "baum_b")["quelle"]
    return a, b


def _quellen(nachschauen, ziel):
    with nachschauen(ziel) as d:
        return {z["wurzel"]: dict(z) for z in d.quellen_liste()}


# ------------------------------------------------------------ Grundlagen --


def test_zwei_quellen_werden_beide_erfasst(capsys, zwei_quellen, ziel, nachschauen):
    a, b = zwei_quellen
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    assert rueckgabe == cli.OK, ausgabe
    quellen = _quellen(nachschauen, ziel)
    assert set(quellen) == {str(pfade.aufloesen(a)), str(pfade.aufloesen(b))}
    with nachschauen(ziel) as d:
        je = d.zaehler_je_quelle()
        assert je[str(pfade.aufloesen(a))]["gesamt"] == 22
        assert je[str(pfade.aufloesen(b))]["gesamt"] == 22
        assert d.zaehler_je_status()["gefunden"] == 38  # 2 x 19 echte Typen
    assert "Je Quelle" in ausgabe
    assert "2 Quellen" in ausgabe


def test_jede_datei_merkt_sich_ihre_quelle(capsys, zwei_quellen, ziel, nachschauen):
    a, b = zwei_quellen
    _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    with nachschauen(ziel) as d:
        wurzeln = {
            z["quellwurzel"]
            for z in d.verbindung.execute("SELECT DISTINCT quellwurzel FROM dateien")
        }
    assert wurzeln == {str(pfade.aufloesen(a)), str(pfade.aufloesen(b))}


def test_status_zeigt_zahlen_je_quelle(capsys, zwei_quellen, ziel):
    a, b = zwei_quellen
    _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    _, ausgabe = _laufen(capsys, "status", "--ziel", ziel)
    assert "Quellen" in ausgabe
    assert str(pfade.aufloesen(a)) in ausgabe
    assert str(pfade.aufloesen(b)) in ausgabe
    assert "erreichbar" in ausgabe


# --------------------------------------------------------- Ueberschneidung --


def test_quelle_in_quelle_wird_abgelehnt(capsys, quelle, ziel, nachschauen):
    innen = quelle / "2026"
    assert innen.is_dir()
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", quelle, "--quelle", innen, "--ziel", ziel
    )
    assert rueckgabe == cli.FEHLER  # eine Quelle abgelehnt: nicht alles wie gewuenscht
    assert "abgelehnt" in ausgabe
    quellen = _quellen(nachschauen, ziel)
    assert set(quellen) == {str(pfade.aufloesen(quelle))}
    with nachschauen(ziel) as d:
        assert d.zaehler_je_dateityp()["foto"] == 13  # nichts doppelt
        assert d.ereignisse_zaehlen(1, scan.ART_QUELLE_ABGELEHNT) == 1


def test_bekannte_quelle_als_uebergeordnete_wird_abgelehnt(capsys, quelle, ziel, nachschauen):
    innen = quelle / "2026"
    _laufen(capsys, "scan", "--quelle", innen, "--ziel", ziel)
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", quelle, "--ziel", ziel)
    assert rueckgabe == cli.FEHLER
    assert "abgelehnt" in ausgabe
    assert set(_quellen(nachschauen, ziel)) == {str(pfade.aufloesen(innen))}


def test_dieselbe_quelle_zweimal_genannt_zaehlt_einmal(capsys, quelle, ziel, nachschauen):
    rueckgabe, _ = _laufen(capsys, "scan", "--quelle", quelle, "--quelle", quelle, "--ziel", ziel)
    assert rueckgabe == cli.OK
    with nachschauen(ziel) as d:
        assert d.zaehler_je_dateityp()["foto"] == 13
    assert len(_quellen(nachschauen, ziel)) == 1


# ----------------------------------------------------- nicht erreichbar --


def test_nicht_erreichbare_quelle_laesst_ihre_dateien_nicht_verschwinden(
    capsys, zwei_quellen, ziel, nachschauen
):
    a, b = zwei_quellen
    _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    b_auf = str(pfade.aufloesen(b))
    shutil.rmtree(b)  # Platte abgezogen

    rueckgabe, ausgabe = _laufen(capsys, "scan", "--ziel", ziel)
    assert rueckgabe == cli.FEHLER
    assert "nicht erreichbar" in ausgabe
    quellen = _quellen(nachschauen, ziel)
    assert quellen[b_auf]["erreichbar"] == 0
    assert quellen[str(pfade.aufloesen(a))]["erreichbar"] == 1
    with nachschauen(ziel) as d:
        # Die Dateien von b sind noch alle da - Status unveraendert.
        n = d.verbindung.execute(
            "SELECT COUNT(*) FROM dateien WHERE quellwurzel = ?", (b_auf,)
        ).fetchone()[0]
        assert n == 22
        # und sie gelten nicht als verschwunden
        assert d.nicht_mehr_gesehen_zaehlen(b_auf, 2) == 22  # das waere die naive Zahl ...
        assert d.ereignisse_zaehlen(2, scan.ART_QUELLE_NICHT_ERREICHBAR) == 1
    # ... aber die Ausgabe darf sie nicht als "nicht mehr vorhanden" zaehlen
    assert "nicht mehr vorhanden:  0" in ausgabe or "Quelle nicht mehr vorhanden:  0" in ausgabe


def test_neue_quelle_die_nicht_existiert_wird_gemeldet(capsys, quelle, ziel, tmp_path):
    rueckgabe, ausgabe = _laufen(
        capsys, "scan", "--quelle", quelle, "--quelle", tmp_path / "gibtsnicht", "--ziel", ziel
    )
    assert rueckgabe == cli.FEHLER
    assert "gibtsnicht" in ausgabe


def test_nur_unbrauchbare_quellen_legen_kein_archiv_an(capsys, tmp_path, ziel):
    rueckgabe, _ = _laufen(capsys, "scan", "--quelle", tmp_path / "nix", "--ziel", ziel)
    assert rueckgabe == cli.FEHLER
    assert not db.archiv_id_vorhanden(ziel)


# ------------------------------------------------ welche Quellen laufen --


def test_scan_mit_angabe_scannt_nur_die_genannte(capsys, zwei_quellen, ziel, tmp_path, nachschauen):
    a, b = zwei_quellen
    _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)  # Lauf 1
    c = testbaum.erzeugen(tmp_path / "baum_c")["quelle"]
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--quelle", c, "--ziel", ziel)  # Lauf 2
    assert rueckgabe == cli.OK
    quellen = _quellen(nachschauen, ziel)
    assert quellen[str(pfade.aufloesen(a))]["zuletzt_gescannt_in_lauf"] == 1
    assert quellen[str(pfade.aufloesen(b))]["zuletzt_gescannt_in_lauf"] == 1
    assert quellen[str(pfade.aufloesen(c))]["zuletzt_gescannt_in_lauf"] == 2
    assert "Neu aufgenommene Quelle" in ausgabe


def test_scan_ohne_angabe_scannt_alle_bekannten(capsys, zwei_quellen, ziel, nachschauen):
    a, b = zwei_quellen
    _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--ziel", ziel)
    assert rueckgabe == cli.OK
    quellen = _quellen(nachschauen, ziel)
    assert all(z["zuletzt_gescannt_in_lauf"] == 2 for z in quellen.values())
    assert "unveraendert uebernommen:     44" in ausgabe


def test_erster_scan_ohne_quelle_meldet_das(capsys, ziel):
    rueckgabe, ausgabe = _laufen(capsys, "scan", "--ziel", ziel)
    assert rueckgabe == cli.FEHLENDE_ANGABE
    assert "Quelle" in ausgabe


# ------------------------------------------------------------ Laufwerk --


def test_laufwerk_kennung_ist_fuer_zwei_ordner_desselben_dateisystems_gleich(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    assert pfade.laufwerk_kennung(tmp_path / "x") == pfade.laufwerk_kennung(tmp_path / "y")
    assert pfade.laufwerk_kennung(tmp_path / "x").startswith(("dev:", "laufwerk:", "server:"))


def test_quellen_auf_einem_laufwerk_werden_gemeldet(capsys, zwei_quellen, ziel):
    a, b = zwei_quellen
    _, ausgabe = _laufen(capsys, "scan", "--quelle", a, "--quelle", b, "--ziel", ziel)
    assert "auf einem Laufwerk" in ausgabe


def test_ausfuehren_mehrere_liefert_ergebnis_je_quelle(zwei_quellen, ziel, archiv_basis, konf):
    a, b = zwei_quellen
    dbank = db.Datenbank.oeffnen(archiv_basis / "x")
    try:
        lauf = dbank.lauf_beginnen("test")
        gesamt = scan.ausfuehren_mehrere([a, b], ziel, konf, dbank, lauf)
        assert set(gesamt.je_quelle) == {str(pfade.aufloesen(a)), str(pfade.aufloesen(b))}
        assert gesamt.gesamt.dateien == 44
        assert all(e.dateien == 22 for e in gesamt.je_quelle.values())
        assert gesamt.laufwerke == 1
        assert gesamt.gesamt.verschwunden_ausgewertet
    finally:
        dbank.schliessen()


# --------------------------------------------------------- Schema-Version --


def test_alte_schema_version_wird_abgelehnt(tmp_path):
    ordner = tmp_path / "alt"
    ordner.mkdir()
    alt = sqlite3.connect(str(db.datenbank_pfad(ordner)))
    alt.execute("CREATE TABLE dateien (quellpfad TEXT PRIMARY KEY)")
    alt.execute("PRAGMA user_version=1")
    alt.commit()
    alt.close()
    with pytest.raises(FotosortFehler) as fehler:
        db.Datenbank.oeffnen(ordner)
    assert "Schema-Version 1" in str(fehler.value)


def test_frische_datenbank_bekommt_die_aktuelle_version(tmp_path):
    dbank = db.Datenbank.oeffnen(tmp_path / "neu")
    try:
        version = dbank.verbindung.execute("PRAGMA user_version").fetchone()[0]
        assert version == db.SCHEMA_VERSION
        tabellen = {
            z[0]
            for z in dbank.verbindung.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"quellen", "dateien", "ziel_index", "laeufe", "lauf_ereignisse"} <= tabellen
    finally:
        dbank.schliessen()
