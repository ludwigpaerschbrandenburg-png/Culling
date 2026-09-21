"""Phase 4: Pruefen und Bericht, Ende-zu-Ende am Testbaum (SPEC Abschnitt 4 Phase 4, 10)."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

import testbaum
from fotosort import bericht, cli, db, hashes, kopieren, pruefen
from test_kopieren import _cli, _ereignisse, _parts, _vorbereiten, _zeilen, _zieldateien


def _bis_kopiert(ziel, *quellen):
    _vorbereiten(ziel, *quellen)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK


def _kopierte(nachschauen, ziel) -> list[dict]:
    return [z for z in _zeilen(nachschauen, ziel).values() if z["status"] == "kopiert"]


def _zurueck_auf_kopiert(nachschauen, ziel) -> None:
    """Wie ein zweiter Pruef-Lauf mit unveraendertem Ziel: Status zuruecksetzen."""
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET status = 'kopiert' WHERE status = 'geprueft'")
        d.verbindung.execute("UPDATE dateien SET status = 'duplikat' WHERE status = 'duplikat_bestaetigt'")
        d.verbindung.commit()


# ------------------------------------------------------------ Ablauf ----


def test_pruefen_bestaetigt_alle_kopien_und_duplikate(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    vorher = _zieldateien(ziel)
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Ergebnis des Pruefens" in aus and "Fehler:                      0" in aus
    zeilen = {k: v for k, v in _zeilen(nachschauen, ziel).items() if v["dateityp"] != "sonstiges"}
    assert {z["status"] for z in zeilen.values()} == {"geprueft", "duplikat_bestaetigt"}
    # bestaetigt_in_lauf bleibt leer: Das ist der Frischlesung von Quelle UND Ziel vorbehalten.
    assert all(z["bestaetigt_in_lauf"] is None for z in zeilen.values())
    assert _zieldateien(ziel) == vorher
    with nachschauen(ziel) as d:
        for z in zeilen.values():
            eintrag = d.ziel_index_nach_pfad(Path(z["zielpfad"]))
            assert eintrag is not None and eintrag["hash"] == z["hash"]
    capsys.readouterr()
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert "Nichts zu pruefen" in capsys.readouterr().out


def test_status_zeigt_danach_aufraeumen_offen(baum, quelle, ziel, capsys):
    _bis_kopiert(ziel, quelle)
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    assert _cli("status", "--ziel", ziel) == cli.OK
    assert "Quelle aufraeumen offen" in capsys.readouterr().out


# -------------------------------------------------- Pflichttests -----


def test_zieldatei_um_ein_byte_veraendert_wird_erkannt(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    z = next(z for z in _kopierte(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    zp = Path(z["zielpfad"])
    inhalt = zp.read_bytes()
    kaputt = inhalt[:-1] + bytes([inhalt[-1] ^ 0x01])
    zp.write_bytes(kaputt)
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "Inhalt weicht ab:          1" in aus
    nachher = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert nachher["status"] == "fehler" and nachher["fehlergrund"] == pruefen.meldungen.GRUND_PRUEFUNG_INHALT
    assert nachher["hash"] == z["hash"] and nachher["zielpfad"] == z["zielpfad"]
    # Die fehlerhafte Zieldatei bleibt unangetastet - weder geloescht noch ueberschrieben.
    assert zp.read_bytes() == kaputt
    assert [e for e in _ereignisse(nachschauen, ziel, pruefen.ART_PRUEFUNG_FEHLGESCHLAGEN) if e["pfad"] == str(baum["analog"])]


def test_zieldatei_abgeschnitten_wird_erkannt(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    z = next(z for z in _kopierte(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    zp = Path(z["zielpfad"])
    zp.write_bytes(zp.read_bytes()[:20])
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    assert "Groesse weicht ab:         1" in capsys.readouterr().out
    nachher = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert nachher["status"] == "fehler" and "abgeschnitten" in nachher["fehlergrund"]
    assert zp.stat().st_size == 20


def test_zieldatei_fehlt_wird_erkannt(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    z = next(z for z in _kopierte(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    Path(z["zielpfad"]).unlink()
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    assert "Zieldatei fehlt:           1" in capsys.readouterr().out
    nachher = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert nachher["status"] == "fehler" and nachher["fehlergrund"] == pruefen.meldungen.GRUND_PRUEFUNG_FEHLT
    with nachschauen(ziel) as d:
        assert d.ziel_index_nach_pfad(Path(z["zielpfad"])) is None


def test_abbruch_mitten_im_pruefen_und_fortsetzen_ergibt_dasselbe(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    _bis_kopiert(ziel, quelle)
    original = pruefen.wait
    aufrufe = []

    def unterbrechen(*args, **kwargs):
        aufrufe.append(1)
        if len(aufrufe) == 1:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(pruefen, "wait", unterbrechen)
    assert _cli("pruefen", "--ziel", ziel) == cli.ABGEBROCHEN
    assert "Abgebrochen" in capsys.readouterr().out
    zeilen = {k: v for k, v in _zeilen(nachschauen, ziel).items() if v["dateityp"] != "sonstiges"}
    assert {z["status"] for z in zeilen.values()} <= {"kopiert", "duplikat", "geprueft", "duplikat_bestaetigt"}
    monkeypatch.setattr(pruefen, "wait", original)
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    zeilen = {k: v for k, v in _zeilen(nachschauen, ziel).items() if v["dateityp"] != "sonstiges"}
    assert {z["status"] for z in zeilen.values()} == {"geprueft", "duplikat_bestaetigt"}


# ----------------------------------------------- Duplikate, verschoben -----


def test_duplikat_mit_fehlender_partnerdatei_wird_fehler(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    zeilen = _zeilen(nachschauen, ziel)
    dup = zeilen[str(baum["duplikat_b"])]
    partner = Path(dup["zielpfad"])
    assert dup["status"] == "duplikat" or zeilen[str(baum["duplikat_a"])]["status"] == "duplikat"
    if dup["status"] != "duplikat":
        dup = zeilen[str(baum["duplikat_a"])]
        partner = Path(dup["zielpfad"])
    inhalt = partner.read_bytes()
    partner.write_bytes(inhalt + b"anders")
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    nachher = _zeilen(nachschauen, ziel)
    assert nachher[dup["quellpfad"]]["status"] == "fehler"
    # Auch die Zeile, der die Partnerdatei gehoert, ist jetzt fehlerhaft.
    besitzer = next(z for z in nachher.values() if z["zielpfad"] == dup["zielpfad"] and z["quellpfad"] != dup["quellpfad"])
    assert besitzer["status"] == "fehler"
    assert partner.read_bytes() == inhalt + b"anders"


def test_verschobene_datei_bekommt_hash_aus_dem_ziel(baum, quelle, ziel, nachschauen, capsys):
    """Status verschoben (Phase 5): kein Quell-Hash, Hash wird aus der Zieldatei nachgetragen."""
    _bis_kopiert(ziel, quelle)
    z = next(z for z in _kopierte(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET status = 'verschoben', hash = '' WHERE quellpfad = ?", (z["quellpfad"],))
        d.verbindung.commit()
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert "verschobene Dateien gehasht: 1" in capsys.readouterr().out
    nachher = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert nachher["status"] == "verschoben" and nachher["hash"] == hashes.blake3_datei(Path(z["zielpfad"]))


# ------------------------------------------- Neu kopieren nach Fehler -----


def test_nach_fehlgeschlagener_pruefung_legt_kopieren_frische_kopie_an(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    z = next(z for z in _kopierte(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    zp = Path(z["zielpfad"])
    kaputt = zp.read_bytes()[:20]
    zp.write_bytes(kaputt)
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    capsys.readouterr()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "1 Datei mit fehlgeschlagener Pruefung" in aus
    nachher = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert nachher["status"] == "kopiert"
    assert Path(nachher["zielpfad"]) == zp.with_name("scan_001_1.tif")
    assert Path(nachher["zielpfad"]).read_bytes() == baum["analog"].read_bytes()
    assert zp.read_bytes() == kaputt   # die fehlerhafte Datei bleibt liegen
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert _zeilen(nachschauen, ziel)[str(baum["analog"])]["status"] == "geprueft"
    assert not _parts(ziel)


def test_duplikat_mit_veraenderter_partnerdatei_kommt_wieder_ins_ziel(baum, quelle, ziel, nachschauen):
    """Partnerdatei eines Duplikats veraendert: pruefen meldet beide, kopieren
    bringt den Inhalt wieder ins Ziel - als eigene Kopie oder als Duplikat
    einer frischen, intakten Kopie."""
    _bis_kopiert(ziel, quelle)
    zeilen = _zeilen(nachschauen, ziel)
    dups = [z for z in zeilen.values() if z["status"] == "duplikat"
            and z["quellpfad"] in (str(baum["duplikat_a"]), str(baum["duplikat_b"]))]
    assert len(dups) == 1
    dup = dups[0]
    partner = Path(dup["zielpfad"])
    kaputt = partner.read_bytes() + b"x"
    partner.write_bytes(kaputt)
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    nachher = _zeilen(nachschauen, ziel)[dup["quellpfad"]]
    assert nachher["status"] in ("kopiert", "duplikat")
    assert Path(nachher["zielpfad"]) != partner
    assert hashes.blake3_datei(Path(nachher["zielpfad"])) == dup["hash"]
    assert partner.read_bytes() == kaputt   # die fehlerhafte Datei bleibt liegen
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert _zeilen(nachschauen, ziel)[dup["quellpfad"]]["status"] in ("geprueft", "duplikat_bestaetigt")


# ------------------------------------------------------------ Bericht -----


def test_bericht_wird_nach_jeder_phase_geschrieben(baum, quelle, ziel):
    _bis_kopiert(ziel, quelle)
    ordner = bericht.berichte_ordner(ziel)
    txts = sorted(ordner.glob("*.txt"))
    assert len(txts) == 3   # scan, analyse, kopieren
    assert all(p.with_name(p.stem + "_dateien.csv").exists() for p in txts)
    assert all(p.with_name(p.stem + "_ereignisse.csv").exists() for p in txts)


def test_bericht_inhalt(baum, quelle, ziel, konf, nachschauen, capsys):
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    _bis_kopiert(ziel, quelle)
    z = next(z for z in _kopierte(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    Path(z["zielpfad"]).unlink()
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    capsys.readouterr()
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Bericht fotosort" in aus
    assert "Zahlen je Quelle und gesamt" in aus and "gesamt" in aus
    assert "Laeufe (Dauer und Durchsatz je Phase)" in aus and "fotosort kopieren" in aus
    assert "Fehler (mit Grund): 1" in aus and str(baum["analog"]) in aus and "Zieldatei fehlt" in aus
    assert "Umbenennungen wegen Namenskonflikt" in aus and "DSC01234_1.JPG" in aus
    assert "Duplikate mit Partnerdatei im Ziel" in aus and str(baum["duplikat_b"]) in aus or str(baum["duplikat_a"]) in aus
    assert "Zeitzone angenommen" in aus and str(baum["video_nur_utc"]) in aus
    assert "Ohne sicheres Datum" in aus and str(baum["ohne_datum"]) in aus
    assert "Datum aus dem Dateinamen ohne Uhrzeit (Tagesgrenze nicht angewendet): 1" in aus
    assert "Pruefung fehlgeschlagen" in aus
    # CSV: eine Zeile je Datei, Semikolon, Spaltenkopf
    ordner = bericht.berichte_ordner(ziel)
    neueste = sorted(ordner.glob("*_dateien.csv"))[-1]
    with open(neueste, encoding="utf-8-sig", newline="") as f:
        zeilen = list(csv.reader(f, delimiter=";"))
    assert zeilen[0] == list(bericht.DATEI_SPALTEN)
    assert len(zeilen) - 1 == testbaum.ERWARTET_GESAMT
    pfade_csv = {r[1] for r in zeilen[1:]}
    assert str(baum["jpg"]) in pfade_csv
    ereignisse = sorted(ordner.glob("*_ereignisse.csv"))[-1]
    with open(ereignisse, encoding="utf-8-sig", newline="") as f:
        er = list(csv.reader(f, delimiter=";"))
    assert er[0] == list(bericht.EREIGNIS_SPALTEN)
    assert any(r[1] == kopieren.ART_NAMENSKONFLIKT for r in er[1:])


def test_bericht_nennt_nicht_erreichbare_und_verschwundene_quellen(baum, quelle, ziel, tmp_path, capsys):
    q2 = tmp_path / "Quelle2"
    (q2 / "a").mkdir(parents=True)
    weg = q2 / "a" / "weg.jpg"
    weg.write_bytes(testbaum._JPEG + b"weg")
    _vorbereiten(ziel, quelle, q2)
    weg.unlink()
    assert _cli("scan", "--ziel", ziel, "--quelle", q2) in (cli.OK, cli.FEHLER)
    shutil.rmtree(q2)
    _cli("kopieren", "--ziel", ziel)
    capsys.readouterr()
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Quelle nicht mehr vorhanden: 1" in aus and str(weg) in aus
    assert "Nicht erreichbare Quellen" in aus and str(q2) in aus


def test_bericht_legt_keinen_lauf_an(baum, quelle, ziel, nachschauen):
    _vorbereiten(ziel, quelle)
    with nachschauen(ziel) as d:
        vorher = len(d.laeufe_liste())
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    with nachschauen(ziel) as d:
        assert len(d.laeufe_liste()) == vorher
