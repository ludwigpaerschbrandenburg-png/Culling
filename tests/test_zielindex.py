"""fotosort ziel-index --neu-aufbauen: das Ziel vollstaendig neu einlesen (SPEC §6, §8).

Der Neuaufbau ist der Rettungsweg, wenn lokale Datenbank und Sicherungskopie
beide fehlen, und der Weg, wenn im Ziel von Hand etwas veraendert wurde. Er
loescht und verschiebt im Ziel nichts.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fotosort import cli, db, hashes, zielindex
from test_kopieren import _cli, _vorbereiten, _zeilen, _zieldateien


def _bis_kopiert(ziel, quelle) -> None:
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK


def _index(nachschauen, ziel) -> dict[str, dict]:
    with nachschauen(ziel) as d:
        return {r["zielpfad"]: dict(r) for r in d.verbindung.execute("SELECT * FROM ziel_index")}


def _archiv_ordner(ziel, archiv_basis) -> Path:
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    return archiv_basis / kennung


def _lokal_loeschen(ziel, archiv_basis, auch_sicherung: bool = False) -> None:
    ordner = _archiv_ordner(ziel, archiv_basis)
    for name in (db.DATEINAME, db.DATEINAME + "-wal", db.DATEINAME + "-shm"):
        if (ordner / name).exists():
            (ordner / name).unlink()
    if auch_sicherung:
        for p in (db.sicherung_pfad(ziel), db.sicherung_vorher_pfad(ziel)):
            if p.exists():
                p.unlink()


def _medien(ziel) -> dict[str, str]:
    """Relativer Pfad -> Hash, ohne Fremddateien dieses Tests."""
    return {k: v for k, v in _zieldateien(ziel).items()
            if not k.endswith(".part") and not k.endswith(".txt")}


# ------------------------------------------------------------ Anzeige ----


def test_ohne_schalter_zeigt_den_stand_und_legt_keinen_lauf_an(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    with nachschauen(ziel) as d:
        laeufe = len(d.laeufe_liste())
        zeilen = d.ziel_index_zusammenfassung()["zeilen"]
    assert zeilen > 0
    capsys.readouterr()
    assert _cli("ziel-index", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert f"Dateien im Index: {zeilen}" in aus and "--neu-aufbauen" in aus
    with nachschauen(ziel) as d:
        assert len(d.laeufe_liste()) == laeufe


# ---------------------------------------------------------- Neuaufbau ----


def test_neuaufbau_ohne_datenbank_und_sicherung_liest_das_ziel(baum, quelle, ziel, archiv_basis, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    erwartet = _medien(ziel)
    _lokal_loeschen(ziel, archiv_basis, auch_sicherung=True)
    # Ein Rest aus einem abgebrochenen Lauf und eine fremde Datei im Ziel.
    rest = ziel / "DSC_rest.JPG.part"
    rest.write_bytes(b"halb geschrieben")
    notiz = ziel / "Notiz.txt"
    notiz.write_text("nicht von fotosort", encoding="utf-8")
    capsys.readouterr()

    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "wird eine neue angelegt" in aus and "Ergebnis des Neuaufbaus" in aus
    assert f"vollstaendig gelesen:        {len(erwartet) + 1}" in aus
    assert ".part-Dateien uebergangen:   1" in aus

    index = _index(nachschauen, ziel)
    for rel, h in erwartet.items():
        eintrag = index[str(ziel / rel)]
        assert eintrag["hash"] == h
        assert eintrag["groesse"] == (ziel / rel).stat().st_size
    assert index[str(notiz)]["hash"] == hashes.blake3_datei(notiz)   # jede Datei, nicht nur Medien
    assert not any(k.endswith(".part") for k in index)
    assert not any(db.ARCHIV_UNTERORDNER in k for k in index)
    assert len(index) == len(erwartet) + 1
    # Im Ziel wurde nichts angefasst; Lauf abgeschlossen, Sicherung und Bericht liegen im Ziel.
    assert rest.exists() and _medien(ziel) == erwartet
    assert db.sicherung_pfad(ziel).is_file()
    with nachschauen(ziel) as d:
        letzter = d.letzter_lauf()
        assert "ziel-index --neu-aufbauen" in letzter["befehl"] and letzter["ende"]
        assert d.ereignisse_liste(zielindex.ART_NEU_AUFGEBAUT)
        assert d.zaehler_je_status()["gefunden"] == 0   # die Datenbank kennt nur das Ziel


def test_nach_dem_neuaufbau_wird_nichts_doppelt_kopiert(baum, quelle, ziel, archiv_basis, nachschauen, capsys):
    """Der Rettungsweg aus SPEC §6: Neuaufbau, dann die Quellen neu durchsuchen -
    was schon im Ziel liegt, erkennt das Kopieren am Inhalt."""
    _bis_kopiert(ziel, quelle)
    vorher = _medien(ziel)
    _lokal_loeschen(ziel, archiv_basis, auch_sicherung=True)
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    assert "Ziel-Index neu aufgebaut" in capsys.readouterr().out
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "kopiert:                     0 Dateien" in aus
    assert _medien(ziel) == vorher
    echte = [z for z in _zeilen(nachschauen, ziel).values() if z["dateityp"] != "sonstiges"]
    assert echte and all(z["status"] == "duplikat" for z in echte)


def test_neuaufbau_mit_datenbank_folgt_dem_ziel_und_nicht_dem_index(baum, quelle, ziel, nachschauen, capsys):
    """Im Ziel von Hand veraendert: eine Datei weg, eine mit neuem Inhalt, dazu
    ein erfundener Eintrag im Index. Danach beschreibt der Index die Platte."""
    _bis_kopiert(ziel, quelle)
    dateien = sorted(p for p in ziel.rglob("*") if p.is_file() and db.ARCHIV_UNTERORDNER not in p.parts)
    weg, geaendert = dateien[0], dateien[1]
    weg.unlink()
    geaendert.write_bytes(b"von Hand bearbeitet")
    with nachschauen(ziel) as d:
        d.ziel_index_setzen(ziel / "erfunden.jpg", 3, 1.0, "abc", 1)
        d.stapel_schreiben()
        zeilen_vorher = {r["quellpfad"]: dict(r) for r in d.verbindung.execute("SELECT * FROM dateien")}
    capsys.readouterr()

    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "alte Eintraege ohne Datei entfernt: 2" in aus

    index = _index(nachschauen, ziel)
    assert str(weg) not in index and str(ziel / "erfunden.jpg") not in index
    assert index[str(geaendert)]["hash"] == hashes.blake3_datei(geaendert)
    assert index[str(geaendert)]["groesse"] == len(b"von Hand bearbeitet")
    assert set(index) == {str(p) for p in dateien[1:]}
    # Die Zeilen der Quelldateien bleiben unangetastet - das Pruefen findet die Abweichungen.
    with nachschauen(ziel) as d:
        assert {r["quellpfad"]: dict(r) for r in d.verbindung.execute("SELECT * FROM dateien")} == zeilen_vorher


def test_abbruch_und_fortsetzen_uebernimmt_das_schon_gelesene(baum, quelle, ziel, archiv_basis, nachschauen, capsys, monkeypatch):
    _bis_kopiert(ziel, quelle)
    erwartet = _medien(ziel)
    _lokal_loeschen(ziel, archiv_basis, auch_sicherung=True)

    # Strg+C, nachdem die ersten Lesungen verbucht sind.
    echt = zielindex.wait
    zaehler = {"n": 0}

    def wait_mit_abbruch(*a, **kw):
        zaehler["n"] += 1
        if zaehler["n"] > 3:
            raise KeyboardInterrupt
        return echt(*a, **kw)

    monkeypatch.setattr(zielindex, "wait", wait_mit_abbruch)
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel, "--hash-worker", "1") == cli.ABGEBROCHEN
    aus = capsys.readouterr().out
    assert "Abgebrochen" in aus
    teil = _index(nachschauen, ziel)
    assert 0 < len(teil) < len(erwartet)
    with nachschauen(ziel) as d:
        abgebrochen = d.letzter_lauf()
        assert abgebrochen["ende"] and d.lauf_zeile(abgebrochen["nummer"])["zusammenfassung"] == ""

    monkeypatch.setattr(zielindex, "wait", echt)
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert f"Lauf {abgebrochen['nummer']}) wurde nicht beendet" in aus
    assert f"uebernommen: {len(teil)}" in aus
    index = _index(nachschauen, ziel)
    assert {k for k in index} == {str(ziel / rel) for rel in erwartet}
    assert all(index[str(ziel / rel)]["hash"] == h for rel, h in erwartet.items())
    with nachschauen(ziel) as d:
        neu = d.letzter_lauf()["nummer"]
    assert all(e["zuletzt_gelesen_in_lauf"] == neu for e in index.values())


def test_uebernommen_wird_nur_unveraendertes(baum, quelle, ziel, archiv_basis, nachschauen, capsys, monkeypatch):
    """Was ein abgebrochener Neuaufbau las, zaehlt nur, wenn Groesse und
    Aenderungsdatum noch stimmen - sonst wird neu gehasht."""
    _bis_kopiert(ziel, quelle)
    _lokal_loeschen(ziel, archiv_basis, auch_sicherung=True)
    echt = zielindex.wait
    zaehler = {"n": 0}

    def wait_mit_abbruch(*a, **kw):
        zaehler["n"] += 1
        if zaehler["n"] > 3:
            raise KeyboardInterrupt
        return echt(*a, **kw)

    monkeypatch.setattr(zielindex, "wait", wait_mit_abbruch)
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel, "--hash-worker", "1") == cli.ABGEBROCHEN
    teil = _index(nachschauen, ziel)
    geaendert = Path(db.text_pfad(next(iter(teil))))
    geaendert.write_bytes(b"nach dem Abbruch veraendert")
    monkeypatch.setattr(zielindex, "wait", echt)
    capsys.readouterr()
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert f"uebernommen: {len(teil) - 1}" in aus
    index = _index(nachschauen, ziel)
    assert index[str(geaendert)]["hash"] == hashes.blake3_datei(geaendert)


def test_verknuepfungen_werden_nicht_verfolgt(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    fremd = ziel.parent / "Fremd"
    fremd.mkdir()
    (fremd / "fremd.jpg").write_bytes(b"x" * 10)
    try:
        os.symlink(fremd, ziel / "Verknuepfung", target_is_directory=True)
        os.symlink(fremd / "fremd.jpg", ziel / "fremd_link.jpg")
    except (OSError, NotImplementedError):
        pytest.skip("keine Verknuepfungen auf diesem System")
    capsys.readouterr()
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Verknuepfungen nicht verfolgt: 2" in aus
    assert not any("fremd" in k.lower() or "Verknuepfung" in k for k in _index(nachschauen, ziel))


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="Leserechte lassen sich nur ohne root pruefen")
def test_nicht_lesbare_datei_wird_gemeldet_und_bleibt(baum, quelle, ziel, nachschauen, capsys):
    _bis_kopiert(ziel, quelle)
    datei = sorted(p for p in ziel.rglob("*.JPG") if p.is_file())[0]
    datei.chmod(0)
    try:
        capsys.readouterr()
        assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.FEHLER
        aus = capsys.readouterr().out
        assert "Fehler (nicht lesbar):       1" in aus
        assert str(datei) not in _index(nachschauen, ziel)
        with nachschauen(ziel) as d:
            ereignisse = d.ereignisse_liste(zielindex.ART_NICHT_LESBAR)
        assert len(ereignisse) == 1 and ereignisse[0]["pfad"] == str(datei)
    finally:
        datei.chmod(0o644)
    assert datei.exists()


def test_leeres_ziel_ergibt_leeren_index(quelle, ziel, nachschauen, capsys):
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    capsys.readouterr()
    assert _cli("ziel-index", "--neu-aufbauen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "keine Dateien" in aus
    assert _index(nachschauen, ziel) == {}
