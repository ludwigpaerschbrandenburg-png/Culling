"""Phase 5: kopieren --verschieben (SPEC Abschnitt 4 Phase 3, Abschnitt 5, 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

import testbaum
from fotosort import cli, hashes, kopieren, loeschen, pfade
from test_kopieren import _cli, _ereignisse, _parts, _vorbereiten, _zeilen, _zieldateien


def _echte(zeilen: dict) -> dict:
    return {k: v for k, v in zeilen.items() if v["dateityp"] in ("foto", "raw", "video", "sidecar")}


# --------------------------------------------- gleiches Laufwerk: umbenennen ----


def test_verschieben_auf_demselben_laufwerk_benennt_um(baum, quelle, ziel, nachschauen, capsys):
    """Quelle und Ziel liegen unter tmp_path, also nachweislich auf demselben Laufwerk."""
    _vorbereiten(ziel, quelle)
    vorher = {qp: hashes.blake3_datei(Path(qp)) for qp in _echte(_zeilen(nachschauen, ziel))}
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    aus = capsys.readouterr().out
    assert "Dateien werden umbenannt, nicht kopiert" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} <= {"verschoben", "duplikat"}
    verschoben = {k: v for k, v in zeilen.items() if v["status"] == "verschoben"}
    assert verschoben
    for qp, z in verschoben.items():
        assert not Path(qp).exists()
        assert hashes.blake3_datei(Path(z["zielpfad"])) == vorher[qp]
        assert z["hash"] == ""   # kommt erst in der Pruef-Phase
    # Duplikate bleiben in der Quelle liegen (nur ueber duplikat_bestaetigt, SPEC §5).
    for qp, z in zeilen.items():
        if z["status"] == "duplikat":
            assert Path(qp).exists()
    assert not _parts(ziel)
    # Pruefen traegt den Hash nach; aufraeumen hat nichts zu tun fuer verschobene.
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    nachher = _zeilen(nachschauen, ziel)
    for qp in verschoben:
        assert nachher[qp]["status"] == "verschoben" and nachher[qp]["hash"] == vorher[qp]


def test_umbenennen_auf_belegten_namen_ueberschreibt_nichts(baum, quelle, ziel, konf, nachschauen):
    """Pflichttest SPEC §11: belegter Zielname, vorhandene Zieldatei bleibt, Quelle ist noch da."""
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    belegt = vor["belegt"].read_bytes()
    inhalt_jpg = baum["jpg"].read_bytes()
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    assert vor["belegt"].read_bytes() == belegt
    zeilen = _zeilen(nachschauen, ziel)
    z = zeilen[str(baum["jpg"])]
    assert z["status"] == "verschoben" and Path(z["zielpfad"]) == vor["zusatz_ordner"] / "DSC01234_1.JPG"
    assert Path(z["zielpfad"]).read_bytes() == inhalt_jpg
    assert not baum["jpg"].exists()
    # Die ganze Gruppe traegt denselben Anhang.
    assert Path(zeilen[str(baum["raw"])]["zielpfad"]).name == "DSC01234_1.ARW"
    assert Path(zeilen[str(baum["sidecar_form2"])]["zielpfad"]).name == "DSC01234_1.ARW.xmp"


def test_umbenennen_gleicher_inhalt_am_zielnamen_ist_duplikat(baum, quelle, ziel, konf, nachschauen):
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    vor["belegt"].write_bytes(baum["jpg"].read_bytes())
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    z = _zeilen(nachschauen, ziel)[str(baum["jpg"])]
    assert z["status"] == "duplikat" and Path(z["zielpfad"]) == vor["belegt"]
    assert baum["jpg"].exists()   # Duplikate bleiben, bis aufraeumen sie bestaetigt entfernt


def test_direkte_pruefung_direkt_nach_dem_umbenennen(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """Weicht die Zieldatei nach dem Umbenennen ab (Groesse), wird das gemeldet."""
    _vorbereiten(ziel, quelle)
    original = pfade.umbenennen_ohne_ueberschreiben

    def kaputt(von, nach):
        original(von, nach)
        if Path(nach).name == "scan_001.tif":
            Path(nach).write_bytes(b"kaputt")   # nachgestellter Defekt des Dateisystems

    monkeypatch.setattr(kopieren.pfade, "umbenennen_ohne_ueberschreiben", kaputt)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "fehler" and "Groesse weicht ab" in z["fehlergrund"]


# ------------------------------------- anderes Laufwerk / Netz: kopieren und loeschen ----


@pytest.fixture
def kein_gleiches_laufwerk(monkeypatch):
    """So, als laege die Quelle auf einem Netzlaufwerk: nie 'gleiches Laufwerk'."""
    monkeypatch.setattr(kopieren.pfade, "gleiches_laufwerk", lambda a, b: False)


def test_verschieben_ueber_kopieren_loescht_quelle_nach_frischlesung(baum, quelle, ziel, nachschauen, kein_gleiches_laufwerk, capsys):
    _vorbereiten(ziel, quelle)
    vorher = {qp: hashes.blake3_datei(Path(qp)) for qp in _echte(_zeilen(nachschauen, ziel))}
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    aus = capsys.readouterr().out
    assert "kopieren, Ziel und Quelle frisch lesen, dann Quelle loeschen" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    geloescht = {k: v for k, v in zeilen.items() if v["status"] == "quelle_geloescht"}
    assert geloescht
    for qp, z in geloescht.items():
        assert not Path(qp).exists()
        assert hashes.blake3_datei(Path(z["zielpfad"])) == vorher[qp] == z["hash"]
        assert z["bestaetigt_in_lauf"] is not None
    for qp, z in zeilen.items():
        if z["status"] == "duplikat":
            assert Path(qp).exists()
    assert len(_ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_GELOESCHT)) == len(geloescht)
    assert "Quelle nach Pruefung geloescht:" in aus


def test_verschieben_quelle_waehrend_des_laufs_veraendert_wird_nicht_geloescht(baum, quelle, ziel, nachschauen, kein_gleiches_laufwerk, monkeypatch, capsys):
    """Zwischen Kopieren und Frischlesung aendert sich die Quelle: nicht loeschen, zurueck auf analysiert."""
    _vorbereiten(ziel, quelle)
    datei = baum["analog"]
    original = loeschen.frisch_lesen

    def veraendern_dann_lesen(q, z, byte_vergleich, stop=None, lauf=0):
        if Path(q) == datei:
            Path(q).write_bytes(Path(q).read_bytes() + b"neu")
        return original(q, z, byte_vergleich, stop, lauf)

    monkeypatch.setattr(kopieren.loeschen, "frisch_lesen", veraendern_dann_lesen)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    aus = capsys.readouterr().out
    assert "Quelle seit dem Kopieren geaendert (nicht geloescht): 1" in aus
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert datei.exists() and datei.read_bytes().endswith(b"neu")
    assert z["status"] == "analysiert" and z["hash"] == ""
    assert Path(z["zielpfad"]).exists()   # die alte Kopie bleibt im Ziel
    assert _ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_SEIT_KOPIEREN_GEAENDERT)


def test_verschieben_zieldatei_nach_dem_kopieren_veraendert_wird_nicht_geloescht(baum, quelle, ziel, nachschauen, kein_gleiches_laufwerk, monkeypatch, capsys):
    _vorbereiten(ziel, quelle)
    datei = baum["analog"]
    original = loeschen.frisch_lesen

    def ziel_kaputt_dann_lesen(q, z, byte_vergleich, stop=None, lauf=0):
        if Path(q) == datei:
            Path(z).write_bytes(b"kaputt")
        return original(q, z, byte_vergleich, stop, lauf)

    monkeypatch.setattr(kopieren.loeschen, "frisch_lesen", ziel_kaputt_dann_lesen)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    assert "Loeschung verweigert:         1" in capsys.readouterr().out
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert datei.exists() and z["status"] == "fehler"


def test_verschieben_im_rueckfall_ohne_part(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """exFAT-Ziel: kein Umbenennen, also kopieren, pruefen, loeschen - auch auf demselben Laufwerk."""
    monkeypatch.setattr(kopieren.pfade, "kann_ohne_ueberschreiben", lambda ordner: False)
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    aus = capsys.readouterr().out
    assert "kann kein nicht ueberschreibendes Umbenennen - kopieren, pruefen, dann Quelle loeschen" in aus
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert "verschoben" not in {z["status"] for z in zeilen.values()}
    assert any(z["status"] == "quelle_geloescht" for z in zeilen.values())
    assert not _parts(ziel)


def test_abbruch_im_verschieben_laesst_kopierte_zeilen_stehen(baum, quelle, ziel, nachschauen, kein_gleiches_laufwerk, monkeypatch):
    _vorbereiten(ziel, quelle)
    original = kopieren.wait
    aufrufe = []

    def unterbrechen(*a, **k):
        aufrufe.append(1)
        if len(aufrufe) == 2:
            raise KeyboardInterrupt
        return original(*a, **k)

    monkeypatch.setattr(kopieren, "wait", unterbrechen)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.ABGEBROCHEN
    zeilen = _echte(_zeilen(nachschauen, ziel))
    for qp, z in zeilen.items():
        # Nichts Halbes: entweder Quelle noch da (analysiert/kopiert/duplikat) oder sauber geloescht.
        if z["status"] == "quelle_geloescht":
            assert not Path(qp).exists() and hashes.blake3_datei(Path(z["zielpfad"])) == z["hash"]
        else:
            assert Path(qp).exists()
    assert not _parts(ziel)
