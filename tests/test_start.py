"""Phase 6: gefuehrter Modus 'fotosort start' (SPEC Abschnitt 8)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import testbaum
from fotosort import cli, config, db
from test_aufraeumen import antwort  # noqa: F401  (input() aus einer Liste, Eingabe erzwungen)
from test_kopieren import _cli, _zeilen


def _echte(zeilen: dict) -> dict:
    return {k: v for k, v in zeilen.items() if v["dateityp"] in ("foto", "raw", "video", "sidecar")}


def _laeufe(nachschauen, ziel) -> list[str]:
    with nachschauen(ziel) as d:
        return [z["befehl"] for z in d.laeufe_liste()]


def _konf_pfad(ziel: Path, archiv_basis: Path) -> Path:
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    return archiv_basis / kennung / "config.toml"


# Antworten des ersten Durchlaufs: Quelle, keine weitere, kopieren, Profil,
# Zusammenfassung ok, Scan ok, Analyse ok, kein Alias, Kopieren ok,
# Pruefen ok, nicht aufraeumen, keine leeren Ordner.
def _antworten_voll(quelle: Path, modus: str = "k", profil: str = "ssd") -> list[str]:
    if modus == "v":
        # Verschieben verlangt vor Schritt 3 das Wort statt Enter.
        return [str(quelle), "", modus, profil, "", "", "", "", "verschieben", "", "nein", "nein"]
    return [str(quelle), "", modus, profil, "", "", "", "", "", "", "nein", "nein"]


def test_start_erster_durchlauf_kopiert_und_prueft(baum, quelle, ziel, nachschauen, antwort, capsys):
    antwort.extend(_antworten_voll(quelle))
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    for schritt in ("Schritt 1", "Schritt 2", "Schritt 3", "Schritt 4", "Schritt 5", "Gefuehrter Ablauf beendet"):
        assert schritt in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"geprueft", "duplikat_bestaetigt"}
    assert all(b.startswith("fotosort start") for b in _laeufe(nachschauen, ziel))
    assert all(Path(qp).exists() for qp in zeilen)   # Kopieren: Quelle unangetastet


def test_start_zweiter_aufruf_macht_dort_weiter_und_ueberspringt_erledigtes(baum, quelle, ziel, nachschauen, antwort, capsys):
    antwort.extend(_antworten_voll(quelle))
    assert _cli("start", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    # keine weitere Quelle, kopieren, Profil, ok, Scan ok, kein Alias, nicht aufraeumen, keine Ordner
    antwort.extend(["", "k", "", "", "", "", "nein", "nein"])
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Bekannte Quellordner" in aus and str(quelle) in aus
    assert "Analyse: nichts zu tun" in aus
    assert "Kopieren: nichts zu tun" in aus
    assert "Pruefen: nichts zu tun" in aus
    assert "Aktuelle Phase: 5" in aus


def test_start_alias_wird_eingetragen_und_neu_analysiert(baum, quelle, ziel, nachschauen, antwort, archiv_basis, capsys):
    # ... Analyse ok, Alias ILCE-7C -> MeineA7C, kein weiterer, Kopieren ok, Pruefen ok, nein, nein
    # ... Alias-Frage kommt nach der Neu-Analyse noch einmal (leer = fertig)
    antwort.extend([str(quelle), "", "k", "hdd", "", "", "", "ILCE-7C", "MeineA7C", "", "", "", "", "nein", "nein"])
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "1 Alias in" in aus and "werden neu analysiert" in aus
    text = _konf_pfad(ziel, archiv_basis).read_text(encoding="utf-8")
    assert '"ILCE-7C" = "MeineA7C"' in text
    assert "# Scanner zaehlen als Analog-Material" in text        # Kommentare bleiben
    assert tomllib.loads(text)["kamera"]["aliase"]["ILCE-7C"] == "MeineA7C"
    z = _zeilen(nachschauen, ziel)[str(baum["kaputtes_datum"])]   # Modell ILCE-7C
    assert z["kamera"] == "MeineA7C" and "MeineA7C" in z["zielpfad"] and Path(z["zielpfad"]).exists()
    assert z["status"] == "geprueft"


def test_start_abbruch_bei_der_zusammenfassung_aendert_nichts(baum, quelle, ziel, antwort, capsys):
    antwort.extend([str(quelle), "", "k", "hdd", "n"])
    assert _cli("start", "--ziel", ziel) == cli.ABGEBROCHEN
    assert "Abgebrochen. Es wurde nichts veraendert." in capsys.readouterr().out
    assert not db.archiv_id_vorhanden(ziel) and list(ziel.iterdir()) == []


def test_start_aufhoeren_vor_einem_schritt_ist_fortsetzbar(baum, quelle, ziel, nachschauen, antwort, capsys):
    antwort.extend([str(quelle), "", "k", "hdd", "", "", "n"])   # nach dem Scan aufhoeren
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Hier aufgehoert" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"gefunden"}


def test_start_ohne_terminal_tut_nichts(baum, quelle, ziel, monkeypatch, capsys):
    monkeypatch.delenv("FOTOSORT_EINGABE_ERZWINGEN", raising=False)
    assert _cli("start", "--ziel", ziel, "--quelle", quelle) == cli.FEHLER
    assert "braucht dafuer ein Terminal" in capsys.readouterr().out
    assert not db.archiv_id_vorhanden(ziel)


def test_start_fragt_nach_dem_ziel_und_legt_es_an(baum, quelle, tmp_path, antwort, capsys):
    neu = tmp_path / "Archiv_neu"
    antwort.extend([str(neu), "ja", str(quelle), "", "k", "hdd", "", "", "n"])
    assert _cli("start") == cli.OK
    aus = capsys.readouterr().out
    assert "gibt es noch nicht" in aus
    assert neu.is_dir() and db.archiv_id_vorhanden(neu)


def test_start_ziel_nicht_anlegen_bricht_ab(baum, quelle, tmp_path, antwort):
    neu = tmp_path / "Archiv_neu"
    antwort.extend([str(neu), "nein"])
    assert _cli("start") == cli.ABGEBROCHEN
    assert not neu.exists()


def test_start_verschieben(baum, quelle, ziel, nachschauen, antwort, capsys):
    antwort.extend(_antworten_voll(quelle, modus="v"))
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Modus:    verschieben" in aus and "Schritt 3: Verschieben" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert "verschoben" in {z["status"] for z in zeilen.values()}
    assert not baum["analog"].exists()


def test_start_falscher_quellordner_wird_erneut_gefragt(baum, quelle, ziel, tmp_path, antwort, capsys):
    antwort.extend([str(tmp_path / "gibt_es_nicht"), str(ziel), str(quelle), "", "k", "hdd", "n"])
    assert _cli("start", "--ziel", ziel) == cli.ABGEBROCHEN
    aus = capsys.readouterr().out
    assert "gibt_es_nicht" in aus
    assert "Quelle und Ziel" in aus or "gleich" in aus.lower()


def test_start_dreimal_leer_bricht_ab(baum, ziel, antwort, capsys):
    antwort.extend(["", "", ""])
    assert _cli("start", "--ziel", ziel) == cli.ABGEBROCHEN


def test_start_schalter_ersetzen_die_fragen(baum, quelle, ziel, nachschauen, antwort, capsys):
    # Quelle und Profil per Schalter: keine weitere Quelle, Modus, ok, Scan, Analyse, Alias,
    # Kopieren, Pruefen, nicht aufraeumen, keine leeren Ordner
    antwort.extend(["", "", "", "", "", "", "", "", "nein", "nein"])
    assert _cli("start", "--ziel", ziel, "--quelle", quelle, "--profil", "ssd") == cli.OK
    aus = capsys.readouterr().out
    assert "Profil:   ssd" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"geprueft", "duplikat_bestaetigt"}


# ----------------------------------------------- config.aliase_ergaenzen ----


def test_aliase_ergaenzen_ersetzt_und_ergaenzt_ohne_kommentare_zu_verlieren(tmp_path):
    pfad = tmp_path / "config.toml"
    config.erzeugen(pfad)
    vorher = pfad.read_text(encoding="utf-8")
    config.aliase_ergaenzen(pfad, {"ILCE-7C": "Neu", "Canon EOS R5": "R5"})
    text = pfad.read_text(encoding="utf-8")
    werte = tomllib.loads(text)["kamera"]["aliase"]
    assert werte["ILCE-7C"] == "Neu" and werte["Canon EOS R5"] == "R5" and werte["ILCE-7CM2"] == "A7C2"
    assert text.count('"ILCE-7C"') == 1
    assert vorher.count("#") == text.count("#")
    # Alles ausserhalb der Alias-Tabelle ist unveraendert.
    assert text.split("[kamera.aliase]")[0] == vorher.split("[kamera.aliase]")[0]
    assert not pfad.with_name("config.toml.neu").exists()


def test_aliase_ergaenzen_in_datei_ohne_tabelle(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[ordner]\nvorlage = "{jahr}"\n', encoding="utf-8")
    config.aliase_ergaenzen(pfad, {"X": "Y"})
    daten = tomllib.loads(pfad.read_text(encoding="utf-8"))
    assert daten["kamera"]["aliase"] == {"X": "Y"} and daten["ordner"]["vorlage"] == "{jahr}"


# --------------------------------------------- Befunde der Pruefung Phase 6 ----


def test_start_nein_zu_dateien_fragt_kein_loeschwort(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Fund 1: 'nein' zum Aufraeumen und 'ja' zu leeren Ordnern darf nie das
    Loeschwort fuer Dateien abfragen (SPEC §8: nur auf ausdrueckliches ja)."""
    antwort.extend(_antworten_voll(quelle))
    assert _cli("start", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    (quelle / "leer").mkdir()
    antwort.extend(["", "k", "", "", "", "nein", "ja", "entfernen"])
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Zum Bestaetigen das Wort 'verschieben'" not in aus
    assert "Zum Bestaetigen das Wort 'loeschen'" not in aus
    assert "Soll ein Kameramodell" not in aus            # Fund 8: keine Liste, keine Frage
    assert not (quelle / "leer").exists()
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"geprueft", "duplikat_bestaetigt"}
    assert all(Path(qp).exists() for qp in zeilen)


def test_start_quelle_schalter_wird_geprueft(baum, quelle, ziel, tmp_path, antwort, capsys):
    """Fund 7: --quelle per Schalter geht durch dieselbe Pruefung wie getippt."""
    antwort.extend([str(quelle), "", "k", "hdd", "n"])
    assert _cli("start", "--ziel", ziel, "--quelle", tmp_path / "nix", "--quelle", ziel) == cli.ABGEBROCHEN
    aus = capsys.readouterr().out
    assert "nicht uebernommen" in aus and "kein Ordner" in aus
    assert f"Quellen:  {quelle}" in aus


def test_start_verschieben_braucht_das_wort(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Fund 9: Enter genuegt nicht, um die Quelle zu leeren."""
    antwort.extend([str(quelle), "", "v", "ssd", "", "", "", "", ""])
    assert _cli("start", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Zum Bestaetigen das Wort 'verschieben'" in aus and "Hier aufgehoert" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert "verschoben" not in {z["status"] for z in zeilen.values()}
    assert baum["analog"].exists()


def test_start_modus_antwort_genau(baum, quelle, ziel, antwort, capsys):
    antwort.extend([str(quelle), "", "vielleicht", "hdd", "n"])
    assert _cli("start", "--ziel", ziel) == cli.ABGEBROCHEN
    assert "Modus:    kopieren" in capsys.readouterr().out


def test_aliase_ergaenzen_behaelt_kommentar_am_zeilenende(tmp_path):
    """Fund 6."""
    pfad = tmp_path / "config.toml"
    pfad.write_text('[kamera.aliase]\n"ILCE-7C" = "A7C"   # meine Sony\n"X" = "Y"\n', encoding="utf-8")
    config.aliase_ergaenzen(pfad, {"ilce-7c": "Neu"})
    text = pfad.read_text(encoding="utf-8")
    assert '"ilce-7c" = "Neu" # meine Sony' in text and text.count("ILCE-7C") == 0
    assert tomllib.loads(text)["kamera"]["aliase"] == {"ilce-7c": "Neu", "X": "Y"}


def test_zuruecksetzen_nach_modell_auch_mit_umlaut(baum, quelle, ziel, nachschauen):
    """Fund 5: Vergleich in Python, nicht mit SQLite-LOWER (nur ASCII)."""
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    with nachschauen(ziel) as d:
        qp = db.pfad_text(baum["analog"])
        d.verbindung.execute("UPDATE dateien SET kamera_modell = 'KAMERA Ü' WHERE quellpfad = ?", (qp,))
        d.verbindung.commit()
        assert d.analyse_zuruecksetzen_nach_modell(["kamera ü"]) == 1
        assert d.zeile(qp)["status"] == "gefunden"
        # Schon kopierte Zeilen fallen nie zurueck.
        d.kopiert_setzen(db.pfad_text(baum["jpg"]), ziel / "x.jpg", "h" * 64, 1)
        d.verbindung.execute("UPDATE dateien SET kamera_modell = 'KAMERA Ü' WHERE quellpfad = ?", (db.pfad_text(baum["jpg"]),))
        d.verbindung.commit()
        assert d.analyse_zuruecksetzen_nach_modell(["KAMERA Ü"]) == 0
        assert d.zeile(db.pfad_text(baum["jpg"]))["status"] == "kopiert"
