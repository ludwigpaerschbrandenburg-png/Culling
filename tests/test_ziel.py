"""Zielpfad und bestehende Zielstruktur (SPEC Abschnitt 3)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from fotosort import config, datum, ziel


def _d(*teile, quelle=1, sicher=True, hinweis=""):
    return datum.Datum(datetime(*teile), quelle, sicher, hinweis)


# ------------------------------------------------------------ Vorlage ----


def test_standardvorlage(konf):
    teile = ziel.ordner_teile(_d(2026, 1, 1, 12, 30), "A7C2", konf)
    assert teile == ["2026", "2026-01 Januar", "2026-01-01", "A7C2"]


def test_vorlage_ist_konfigurierbar():
    k = config.Konfiguration()
    k.alle()["ordner"]["vorlage"] = "{jahr}/{kamera}/{jahr}-{monat}-{tag}"
    assert ziel.ordner_teile(_d(2026, 3, 5), "A7C", k) == ["2026", "A7C", "2026-03-05"]


def test_monatsnamen_deutsch(konf):
    assert ziel.ordner_teile(_d(2026, 3, 1), "X", konf)[1] == "2026-03 März"
    assert ziel.ordner_teile(_d(2026, 12, 1), "X", konf)[1] == "2026-12 Dezember"


def test_unsicheres_datum_geht_nach_ohne_datum(konf):
    teile = ziel.ordner_teile(_d(2026, 1, 1, quelle=6, sicher=False), "A7C", konf)
    assert teile == ["_Ohne_Datum", "A7C"]


def test_unsicheres_datum_wahlweise_nach_mtime():
    k = config.Konfiguration()
    k.alle()["datum"]["unsicheres_datum"] = "mtime"
    teile = ziel.ordner_teile(_d(2026, 1, 1, quelle=6, sicher=False), "A7C", k)
    assert teile == ["2026", "2026-01 Januar", "2026-01-01", "A7C"]


def test_gar_kein_datum(konf):
    teile = ziel.ordner_teile(datum.Datum(None, 0, False), "A7C", konf)
    assert teile == ["_Ohne_Datum", "A7C"]


def test_zeitzone_angenommen_ist_sicher_und_landet_nicht_in_ohne_datum(konf):
    d = _d(2026, 1, 2, 0, 30, quelle=3, hinweis=datum.HINWEIS_ZEITZONE)
    assert ziel.ordner_teile(d, "X", konf) == ["2026", "2026-01 Januar", "2026-01-02", "X"]


def test_tagesgrenze_wirkt_auf_den_tagesordner():
    k = config.Konfiguration()
    k.alle()["datum"]["tagesgrenze"] = "04:00"
    assert ziel.ordner_teile(_d(2026, 1, 2, 1, 30), "X", k)[2] == "2026-01-01"
    ohne_uhrzeit = _d(2026, 1, 2, quelle=5, hinweis=datum.HINWEIS_OHNE_UHRZEIT)
    assert ziel.ordner_teile(ohne_uhrzeit, "X", k)[2] == "2026-01-02"


def test_ohne_datum_vorlage_konfigurierbar():
    k = config.Konfiguration()
    k.alle()["ordner"]["vorlage_ohne_datum"] = "Unsortiert/{kamera}"
    assert ziel.ordner_teile(datum.Datum(None, 0, False), "A7C", k) == ["Unsortiert", "A7C"]


# ---------------------------------------------------- passende Ordner ----


@pytest.mark.parametrize(
    "vorhanden, gewuenscht, passt",
    [
        ("2026-01-01", "2026-01-01", True),
        ("2026-01-01 Geburtstag Oma", "2026-01-01", True),
        ("2026-01-01_Urlaub", "2026-01-01", True),
        ("2026-01-01-Urlaub", "2026-01-01", True),
        ("2026-01-010", "2026-01-01", False),
        ("2026-01-02", "2026-01-01", False),
        ("2026-01 Januar Urlaub", "2026-01 Januar", True),
        ("2026-01 Urlaub", "2026-01 Januar", True),  # Datumsanteil plus Zusatz
        ("2026-01", "2026-01 Januar", False),  # ohne Zusatz aber anders: kein Treffer
        ("2026 Fotos", "2026", True),
        ("2026-01 Januar", "2026", False),  # ein Monatsordner ist kein Jahresordner
        ("A7C2", "A7C2", True),
        ("A7C2 alt", "A7C2", True),
        ("A7C", "A7C2", False),
    ],
)
def test_passt(vorhanden, gewuenscht, passt):
    assert ziel.Zielstruktur.passt(vorhanden, gewuenscht) is passt


def test_ordner_mit_zusatz_wird_wiederverwendet(tmp_path, konf):
    """Pflichttest aus SPEC Abschnitt 11."""
    (tmp_path / "2026" / "2026-01 Januar" / "2026-01-01 Geburtstag Oma").mkdir(parents=True)
    s = ziel.Zielstruktur(tmp_path)
    pfad, ort = ziel.zielpfad(s, _d(2026, 1, 1, 12, 30), "A7C2", "DSC01234.ARW", konf)
    assert pfad == tmp_path / "2026" / "2026-01 Januar" / "2026-01-01 Geburtstag Oma" / "A7C2" / "DSC01234.ARW"
    assert ort.wiederverwendet and not ort.mehrdeutig


def test_ohne_zusatz_wird_bevorzugt(tmp_path, konf):
    basis = tmp_path / "2026" / "2026-01 Januar"
    (basis / "2026-01-01 Geburtstag Oma").mkdir(parents=True)
    (basis / "2026-01-01").mkdir()
    s = ziel.Zielstruktur(tmp_path)
    pfad, ort = ziel.zielpfad(s, _d(2026, 1, 1), "X", "a.jpg", konf)
    assert pfad.parent.parent.name == "2026-01-01"
    assert not ort.mehrdeutig and not ort.wiederverwendet


def test_mehrere_mit_zusatz_alphabetisch_erster_und_mehrdeutig(tmp_path, konf):
    basis = tmp_path / "2026" / "2026-01 Januar"
    (basis / "2026-01-01 Zoo").mkdir(parents=True)
    (basis / "2026-01-01 Geburtstag Oma").mkdir()
    s = ziel.Zielstruktur(tmp_path)
    pfad, ort = ziel.zielpfad(s, _d(2026, 1, 1), "X", "a.jpg", konf)
    assert pfad.parent.parent.name == "2026-01-01 Geburtstag Oma"
    assert ort.mehrdeutig and ort.wiederverwendet


def test_auch_monats_und_jahresordner_mit_zusatz(tmp_path, konf):
    (tmp_path / "2026 Fotos" / "2026-01 Januar Urlaub").mkdir(parents=True)
    s = ziel.Zielstruktur(tmp_path)
    pfad, _ = ziel.zielpfad(s, _d(2026, 1, 15), "X", "a.jpg", konf)
    assert pfad == tmp_path / "2026 Fotos" / "2026-01 Januar Urlaub" / "2026-01-15" / "X" / "a.jpg"


def test_leeres_ziel_ergibt_die_vorlage_pur(tmp_path, konf):
    s = ziel.Zielstruktur(tmp_path)
    pfad, ort = ziel.zielpfad(s, _d(2026, 1, 1), "A7C", "a.jpg", konf)
    assert pfad == tmp_path / "2026" / "2026-01 Januar" / "2026-01-01" / "A7C" / "a.jpg"
    assert not ort.wiederverwendet


def test_zielstruktur_liest_jeden_ordner_nur_einmal(tmp_path, konf, monkeypatch):
    s = ziel.Zielstruktur(tmp_path)
    aufrufe = []
    original = s._ordner_in

    def zaehlen(eltern):
        aufrufe.append(eltern)
        return original(eltern)

    monkeypatch.setattr(s, "_ordner_in", zaehlen)
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        ziel.zielpfad(s, _d(2026, 1, 1), "A7C", name, konf)
    # vier Ebenen, je einmal gelesen (der Cache haelt sie), nicht dreimal vier
    assert len(set(aufrufe)) == 4


def test_zeit_text():
    assert ziel.zeit_text(datetime(2026, 1, 1, 12, 30, 5)) == "2026-01-01T12:30:05"
    assert ziel.zeit_text(None) == ""
