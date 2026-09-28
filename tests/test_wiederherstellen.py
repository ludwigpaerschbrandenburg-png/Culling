"""fotosort wiederherstellen: die lokale Datenbank aus der Sicherungskopie im
Ziel zurueckholen (SPEC §6 "Sicherungskopie der Datenbank", §8)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from fotosort import cli, config, db
from test_kopieren import _cli, _vorbereiten, _zeilen
from test_zielindex import _archiv_ordner, _lokal_loeschen


def _bis_kopiert(ziel, quelle) -> None:
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK


def test_holt_datenbank_und_konfiguration_zurueck(baum, quelle, ziel, archiv_basis, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    vorher = _zeilen(nachschauen, ziel)
    ordner = _archiv_ordner(ziel, archiv_basis)
    konf_inhalt = (ordner / config.DATEINAME).read_bytes()
    _lokal_loeschen(ziel, archiv_basis)
    (ordner / config.DATEINAME).unlink()
    capsys.readouterr()

    assert _cli("wiederherstellen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "zurueckgeholt" in aus and "Konfiguration aus dem Ziel" in aus
    assert "Letzter Lauf in der Sicherung: Lauf 3: fotosort kopieren" in aus
    assert (ordner / db.DATEINAME).is_file()
    assert (ordner / config.DATEINAME).read_bytes() == konf_inhalt
    assert not (ordner / db.DATENBANK_NEU).exists()
    assert not list(ordner.glob(db.DATENBANK_ERSETZT + "*"))

    assert _zeilen(nachschauen, ziel) == vorher
    with nachschauen(ziel) as d:
        letzter = d.letzter_lauf()
        assert "wiederherstellen" in letzter["befehl"] and letzter["ende"]
        ereignisse = d.ereignisse_liste(db.ART_DATENBANK_WIEDERHERGESTELLT)
        assert len(ereignisse) == 1 and ereignisse[0]["pfad"] == str(db.sicherung_pfad(ziel))

    # Der Bericht nennt es; danach geht es normal weiter.
    capsys.readouterr()
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    assert "Datenbank aus der Sicherungskopie zurueckgeholt" in capsys.readouterr().out
    assert _cli("status", "--ziel", ziel) == cli.OK
    assert "Phase: 4" in capsys.readouterr().out
    assert _cli("pruefen", "--ziel", ziel) == cli.OK


def test_vorhandene_datenbank_wird_nicht_ungefragt_ersetzt(baum, quelle, ziel, archiv_basis, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    ordner = _archiv_ordner(ziel, archiv_basis)
    vorher = (ordner / db.DATEINAME).stat().st_mtime_ns
    capsys.readouterr()
    assert _cli("wiederherstellen", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "nicht ungefragt ersetzt" in aus and "--ersetzen" in aus
    assert "Lauf 3: fotosort kopieren" in aus   # beide Staende werden genannt
    assert (ordner / db.DATEINAME).stat().st_mtime_ns == vorher
    assert not (ordner / db.DATENBANK_NEU).exists()
    assert not list(ordner.glob(db.DATENBANK_ERSETZT + "*"))


def test_ersetzen_hebt_die_bisherige_datenbank_auf(baum, quelle, ziel, archiv_basis, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    assert _cli("pruefen", "--ziel", ziel) == cli.OK     # neue Sicherung; die alte wird .vorher
    assert db.sicherung_vorher_pfad(ziel).is_file()
    ordner = _archiv_ordner(ziel, archiv_basis)
    capsys.readouterr()

    assert _cli("wiederherstellen", "--ersetzen", "--vorheriger-stand", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "aufgehoben unter" in aus
    aufgehoben = list(ordner.glob(db.DATENBANK_ERSETZT + "*"))
    assert len([p for p in aufgehoben if not p.name.endswith(("-wal", "-shm"))]) == 1
    alt = [p for p in aufgehoben if not p.name.endswith(("-wal", "-shm"))][0]
    # Die aufgehobene Datenbank ist vollstaendig und traegt den Stand nach dem Pruefen ...
    con = sqlite3.connect(alt)
    try:
        assert con.execute("SELECT COUNT(*) FROM dateien WHERE status = 'geprueft'").fetchone()[0] > 0
    finally:
        con.close()
    # ... die eingesetzte den Stand nach dem Kopieren.
    zeilen = _zeilen(nachschauen, ziel)
    assert not any(z["status"] == "geprueft" for z in zeilen.values())
    assert any(z["status"] == "kopiert" for z in zeilen.values())


def test_kaputte_sicherung_veraendert_nichts(baum, quelle, ziel, archiv_basis, capsys):
    _bis_kopiert(ziel, quelle)
    ordner = _archiv_ordner(ziel, archiv_basis)
    _lokal_loeschen(ziel, archiv_basis)
    db.sicherung_pfad(ziel).write_bytes(b"kein sqlite, nur Muell " * 100)
    capsys.readouterr()
    assert _cli("wiederherstellen", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "laesst sich nicht als Datenbank lesen" in aus and "--vorheriger-stand" in aus
    assert not (ordner / db.DATEINAME).exists()
    assert not (ordner / db.DATENBANK_NEU).exists()


def test_sicherung_aus_anderem_programmstand_wird_abgelehnt(baum, quelle, ziel, archiv_basis, capsys):
    _bis_kopiert(ziel, quelle)
    ordner = _archiv_ordner(ziel, archiv_basis)
    _lokal_loeschen(ziel, archiv_basis)
    con = sqlite3.connect(db.sicherung_pfad(ziel))
    try:
        con.execute("PRAGMA user_version = 1")
        con.commit()
    finally:
        con.close()
    capsys.readouterr()
    assert _cli("wiederherstellen", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "Schema-Version 1" in aus
    assert not (ordner / db.DATEINAME).exists()
    assert not (ordner / db.DATENBANK_NEU).exists()


def test_ohne_sicherung_verweist_auf_den_neuaufbau(baum, quelle, ziel, archiv_basis, capsys):
    _bis_kopiert(ziel, quelle)
    _lokal_loeschen(ziel, archiv_basis, auch_sicherung=True)
    capsys.readouterr()
    assert _cli("wiederherstellen", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "keine Sicherungskopie" in aus and "ziel-index --neu-aufbauen" in aus


def test_neuer_rechner_ohne_archiv_ordner(baum, quelle, ziel, archiv_basis, nachschauen, capsys):
    """Der Fall aus der LIESMICH: Das Archiv wurde anderswo angelegt, auf diesem
    Rechner gibt es noch nicht einmal den Archiv-Ordner."""
    _bis_kopiert(ziel, quelle)
    vorher = _zeilen(nachschauen, ziel)
    ordner = _archiv_ordner(ziel, archiv_basis)
    konf_im_ziel = (ziel / db.ARCHIV_UNTERORDNER / config.DATEINAME).read_bytes()
    shutil.rmtree(ordner)
    capsys.readouterr()
    assert _cli("wiederherstellen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "zurueckgeholt" in aus and "Konfiguration aus dem Ziel" in aus
    assert (ordner / db.DATEINAME).is_file()
    assert (ordner / config.DATEINAME).read_bytes() == konf_im_ziel
    assert _zeilen(nachschauen, ziel) == vorher
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
