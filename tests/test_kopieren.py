"""Phase 3 Ende-zu-Ende am Testbaum (SPEC Abschnitt 4 Phase 3, Abschnitt 5, 11).

Alles hier laeuft ueber die Befehlszeile (cli.main), so wie der Nutzer es
aufruft. Die Datenbank landet ueber FOTOSORT_DATENBANK unter tmp_path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import testbaum
from fotosort import cli, db, hashes, kopieren
from fotosort import FotosortFehler

SRC = Path(__file__).resolve().parent.parent / "src"


# ------------------------------------------------------------- Helfer ----


def _cli(*args) -> int:
    return cli.main([str(a) for a in args])


def _vorbereiten(ziel: Path, *quellen: Path) -> None:
    """scan + analyse ueber die Befehlszeile, wie der Nutzer es tut."""
    args = ["scan", "--ziel", ziel]
    for q in quellen:
        args += ["--quelle", q]
    assert _cli(*args) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK


def _zieldateien(ziel: Path) -> dict[str, str]:
    """Relativer Pfad -> Hash aller Dateien im Ziel (ohne .fotosortierer)."""
    ergebnis = {}
    for p in sorted(Path(ziel).rglob("*")):
        if p.is_file() and ".fotosortierer" not in p.parts:
            ergebnis[str(p.relative_to(ziel))] = hashes.blake3_datei(p)
    return ergebnis


def _parts(ziel: Path) -> list[Path]:
    return [p for p in Path(ziel).rglob("*.part") if ".fotosortierer" not in p.parts]


def _zeilen(nachschauen, ziel: Path) -> dict[str, dict]:
    with nachschauen(ziel) as d:
        rows = d.verbindung.execute("SELECT * FROM dateien").fetchall()
        return {r["quellpfad"]: dict(r) for r in rows}


def _ereignisse(nachschauen, ziel: Path, art: str) -> list[dict]:
    with nachschauen(ziel) as d:
        rows = d.verbindung.execute(
            "SELECT * FROM lauf_ereignisse WHERE art = ? ORDER BY rowid", (art,)
        ).fetchall()
        return [dict(r) for r in rows]


def _echte(zeilen: dict) -> dict:
    return {k: v for k, v in zeilen.items() if v["dateityp"] in ("foto", "raw", "video", "sidecar")}


def _zielpfad(nachschauen, ziel, quellpfad) -> Path:
    with nachschauen(ziel) as d:
        return Path(d.zeile(quellpfad)["zielpfad"])


def _beanspruchen(nachschauen, ziel, quellpfad, schreibpfad, lauf=1) -> Path:
    """Eine Zeile so hinstellen, als haette ein frueherer (abgestuerzter) Lauf
    sie beansprucht und unter schreibpfad geschrieben."""
    with nachschauen(ziel) as d:
        d.verbindung.execute(
            "UPDATE dateien SET status = 'kopieren_laeuft', kopiert_in_lauf = ?, schreibpfad = ?"
            " WHERE quellpfad = ?",
            (lauf, db.pfad_text(schreibpfad), db.pfad_text(quellpfad)),
        )
        d.verbindung.commit()
        return Path(d.zeile(quellpfad)["zielpfad"])


# --------------------------------------------------------- Grundablauf ----


def test_ende_zu_ende_alles_landet_im_ziel(baum, quelle, ziel, nachschauen, capsys):
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Ergebnis des Kopierens" in aus and "Fehler:                      0" in aus

    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert zeilen and {z["status"] for z in zeilen.values()} <= {"kopiert", "duplikat"}
    kopiert = {k: v for k, v in zeilen.items() if v["status"] == "kopiert"}
    duplikate = {k: v for k, v in zeilen.items() if v["status"] == "duplikat"}
    assert kopiert
    for qp, z in zeilen.items():
        zp = Path(z["zielpfad"])
        assert zp.exists(), qp
        # Der gespeicherte Hash ist der der Quelle; die Zieldatei traegt ihn auch.
        assert hashes.blake3_datei(Path(qp)) == z["hash"] == hashes.blake3_datei(zp)
        assert zp.is_relative_to(ziel)
    for qp, z in kopiert.items():
        # Aenderungsdatum bleibt erhalten (SPEC Abschnitt 5).
        assert abs(os.stat(qp).st_mtime - os.stat(z["zielpfad"]).st_mtime) < 0.01
    # Ein Duplikat zeigt auf eine wirklich kopierte Datei gleichen Inhalts.
    ziele_kopiert = {z["zielpfad"] for z in kopiert.values()}
    for z in duplikate.values():
        assert z["zielpfad"] in ziele_kopiert
    # Jede kopierte Datei hat ihren eigenen Zielpfad; nichts liegt doppelt.
    assert len(ziele_kopiert) == len(kopiert)
    assert not _parts(ziel)
    # Ziel-Index kennt jede Zieldatei.
    with nachschauen(ziel) as d:
        assert d.verbindung.execute("SELECT COUNT(*) FROM ziel_index").fetchone()[0] == len(ziele_kopiert)
        assert d.verbindung.execute("SELECT COUNT(*) FROM dateien WHERE status = 'kopieren_laeuft'").fetchone()[0] == 0
    # Sonstiges bleibt unangetastet.
    alle = _zeilen(nachschauen, ziel)
    assert all(z["status"] == "uebersprungen" for z in alle.values() if z["dateityp"] == "sonstiges")


def test_zweiter_lauf_kopiert_nichts(baum, quelle, ziel, capsys):
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    vorher = _zieldateien(ziel)
    capsys.readouterr()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Nichts zu kopieren" in aus
    assert _zieldateien(ziel) == vorher


def test_status_zeigt_danach_pruefen_offen(baum, quelle, ziel, capsys):
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    assert _cli("status", "--ziel", ziel) == cli.OK
    assert "Pruefen offen" in capsys.readouterr().out


def test_sidecars_der_gruppe_werden_beide_kopiert(baum, quelle, ziel, nachschauen):
    """DSC01234.xmp und DSC01234.ARW.xmp sind inhaltsgleich - trotzdem gehoert
    jedes zu seiner Hauptdatei und wird kopiert (kein Inhalts-Duplikat)."""
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    a, b = zeilen[str(baum["sidecar_form1"])], zeilen[str(baum["sidecar_form2"])]
    assert a["hash"] == b["hash"]
    assert a["status"] == b["status"] == "kopiert"
    assert Path(a["zielpfad"]).name == "DSC01234.xmp"
    assert Path(b["zielpfad"]).name == "DSC01234.ARW.xmp"


# --------------------------------------- Pflichttests aus SPEC Abschnitt 11 ----


def test_vorbelegtes_ziel_gruppe_bekommt_gemeinsamen_anhang(baum, quelle, ziel, konf, nachschauen):
    """Zusatz-Ordner wird benutzt, belegter Name bleibt unangetastet, die ganze
    Gruppe (RAW, JPG, beide Sidecars) bekommt denselben Anhang _1."""
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    belegt_vorher = vor["belegt"].read_bytes()
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK

    assert vor["belegt"].read_bytes() == belegt_vorher
    zeilen = _zeilen(nachschauen, ziel)
    ordner = vor["zusatz_ordner"]
    erwartet = {
        "raw": "DSC01234_1.ARW",
        "jpg": "DSC01234_1.JPG",
        "sidecar_form1": "DSC01234_1.xmp",
        "sidecar_form2": "DSC01234_1.ARW.xmp",
    }
    for schluessel, name in erwartet.items():
        z = zeilen[str(baum[schluessel])]
        assert z["status"] == "kopiert", schluessel
        assert Path(z["zielpfad"]) == ordner / name, schluessel
        assert (ordner / name).read_bytes() == baum[schluessel].read_bytes()
    # Die zweite DSC01234.JPG (anderer Ordner, anderer Inhalt) bekommt _2.
    z = zeilen[str(baum["namenskonflikt"])]
    assert Path(z["zielpfad"]) == ordner / "DSC01234_2.JPG"
    ereignisse = _ereignisse(nachschauen, ziel, kopieren.ART_NAMENSKONFLIKT)
    assert {e["pfad"] for e in ereignisse} >= {str(baum["jpg"]), str(baum["raw"]), str(baum["namenskonflikt"])}
    assert not _parts(ziel)


@pytest.mark.parametrize("direkt", [False, True], ids=["mit_part", "rueckfall_ohne_part"])
def test_vorhandene_dateien_werden_auf_keinem_weg_ueberschrieben(
    baum, quelle, ziel, konf, nachschauen, monkeypatch, direkt, capsys
):
    """Belegter Name, belegter Name mit _1: beide bleiben Byte fuer Byte gleich."""
    if direkt:
        monkeypatch.setattr(kopieren.pfade, "kann_ohne_ueberschreiben", lambda ordner: False)
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    ordner = vor["zusatz_ordner"]
    fremd = {
        ordner / "DSC01234.JPG": vor["belegt"].read_bytes(),
        ordner / "DSC01234_1.JPG": b"fremd eins",
        ordner / "DSC01234_1.ARW": b"fremd raw",
        ordner / "DSC01234_1.xmp": b"fremd xmp",
    }
    for p, inhalt in fremd.items():
        p.write_bytes(inhalt)
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    for p, inhalt in fremd.items():
        assert p.read_bytes() == inhalt, p
    zeilen = _zeilen(nachschauen, ziel)
    assert Path(zeilen[str(baum["jpg"])]["zielpfad"]) == ordner / "DSC01234_2.JPG"
    assert Path(zeilen[str(baum["raw"])]["zielpfad"]) == ordner / "DSC01234_2.ARW"
    assert (ordner / "DSC01234_2.JPG").read_bytes() == baum["jpg"].read_bytes()
    assert not _parts(ziel)
    if direkt:
        assert "Rueckfall" in aus
        assert _ereignisse(nachschauen, ziel, kopieren.ART_EXFAT_RUECKFALL)
    # Alle Quelldateien sind unveraendert da (Kopier-Modus).
    assert baum["jpg"].exists() and baum["raw"].exists()


def test_gleicher_name_gleicher_inhalt_ist_duplikat_und_rest_der_gruppe_ohne_anhang(
    baum, quelle, ziel, konf, nachschauen
):
    vor = testbaum.ziel_vorbelegen(ziel, konf)
    vor["belegt"].write_bytes(baum["jpg"].read_bytes())   # inhaltsgleich mit der Quelle
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    jpg = zeilen[str(baum["jpg"])]
    assert jpg["status"] == "duplikat" and Path(jpg["zielpfad"]) == vor["belegt"]
    # _1 bekommt nur die andere DSC01234.JPG (Ordner Namenskonflikt, anderer Inhalt).
    konflikt = zeilen[str(baum["namenskonflikt"])]
    assert Path(konflikt["zielpfad"]) == vor["zusatz_ordner"] / "DSC01234_1.JPG"
    assert (vor["zusatz_ordner"] / "DSC01234_1.JPG").read_bytes() == baum["namenskonflikt"].read_bytes()
    raw = zeilen[str(baum["raw"])]
    assert raw["status"] == "kopiert" and Path(raw["zielpfad"]) == vor["zusatz_ordner"] / "DSC01234.ARW"
    assert [e["pfad"] for e in _ereignisse(nachschauen, ziel, kopieren.ART_DUPLIKAT) if e["pfad"] == str(baum["jpg"])]


def test_quelle_seit_analyse_veraendert_wird_nicht_kopiert(baum, quelle, ziel, nachschauen, capsys):
    _vorbereiten(ziel, quelle)
    datei = baum["aendert_sich"]
    datei.write_bytes(datei.read_bytes() + b"neuer inhalt")
    alt = os.stat(datei)
    os.utime(datei, ns=(alt.st_atime_ns, alt.st_mtime_ns + 5_000_000_000))
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "veraendert (neu einordnen):  1" in aus
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert z["status"] == "gefunden" and z["zielpfad"] == "" and z["hash"] == ""
    assert not any("aendert_sich" in p for p in _zieldateien(ziel))
    ereignisse = _ereignisse(nachschauen, ziel, kopieren.ART_QUELLE_VERAENDERT)
    assert any(e["pfad"] == str(datei) for e in ereignisse)
    # Nach scan + analyse kommt sie beim naechsten Lauf mit.
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert z["status"] == "kopiert"
    assert Path(z["zielpfad"]).read_bytes() == datei.read_bytes()


def test_quelldatei_verschwunden_wird_fehler(baum, quelle, ziel, nachschauen, capsys):
    _vorbereiten(ziel, quelle)
    baum["analog"].unlink()
    assert _cli("kopieren", "--ziel", ziel) == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "fehler" and kopieren.GRUND_QUELLE_FEHLT in z["fehlergrund"]
    assert "Fehler:                      1" in capsys.readouterr().out


# ------------------------------------------------- Duplikate ueber Quellen ----


@pytest.fixture
def zwei_quellen(baum, tmp_path):
    """Zweite Quelle: eine Datei inhaltsgleich mit Duplikate/kopie_a.jpg, eine eigene."""
    q2 = tmp_path / "Quelle2"
    (q2 / "Karte").mkdir(parents=True)
    shutil.copy2(baum["duplikat_a"], q2 / "Karte" / "x_gleich.jpg")
    eigen = q2 / "Karte" / "y_eigen.jpg"
    eigen.write_bytes(testbaum._JPEG + b"nur hier")
    return q2


def test_duplikate_ueber_alle_quellen_nur_eine_kopie(baum, quelle, ziel, zwei_quellen, nachschauen):
    _vorbereiten(ziel, quelle, zwei_quellen)
    assert _cli("kopieren", "--ziel", ziel, "--kopier-worker", 1) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    gleich = [zeilen[str(p)] for p in (baum["duplikat_a"], baum["duplikat_b"], zwei_quellen / "Karte" / "x_gleich.jpg")]
    assert len({z["hash"] for z in gleich}) == 1
    kopiert = [z for z in gleich if z["status"] == "kopiert"]
    assert len(kopiert) == 1
    for z in gleich:
        assert z["zielpfad"] == kopiert[0]["zielpfad"]
        assert z["status"] in ("kopiert", "duplikat")
    assert zeilen[str(zwei_quellen / "Karte" / "y_eigen.jpg")]["status"] == "kopiert"
    ereignisse = _ereignisse(nachschauen, ziel, kopieren.ART_DUPLIKAT)
    assert len([e for e in ereignisse if e["text"] == kopiert[0]["zielpfad"]]) == 2


def test_nicht_erreichbare_quelle_wird_uebersprungen(baum, quelle, ziel, zwei_quellen, nachschauen, capsys):
    _vorbereiten(ziel, quelle, zwei_quellen)
    shutil.rmtree(zwei_quellen)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Nicht erreichbare Quellen" in aus and str(zwei_quellen) in aus
    zeilen = _zeilen(nachschauen, ziel)
    assert all(z["status"] == "analysiert" for k, z in zeilen.items() if k.startswith(str(zwei_quellen)))
    assert zeilen[str(baum["jpg"])]["status"] in ("kopiert", "duplikat")
    assert any(e["pfad"] == str(zwei_quellen) for e in _ereignisse(nachschauen, ziel, "quelle_nicht_erreichbar"))
    # Zweiter Lauf: Nur die unerreichbare Quelle hat noch Offenes - das zaehlt nicht als Arbeit.
    capsys.readouterr()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert "Nichts zu kopieren" in capsys.readouterr().out


# ---------------------------------------------------------- Vorpruefungen ----


def test_dry_run_fasst_nichts_an(baum, quelle, ziel, nachschauen, capsys):
    _vorbereiten(ziel, quelle)
    with nachschauen(ziel) as d:
        laeufe_vorher = d.verbindung.execute("SELECT COUNT(*) FROM laeufe").fetchone()[0]
    assert _cli("kopieren", "--ziel", ziel, "--dry-run") == cli.OK
    aus = capsys.readouterr().out
    assert "Probelauf" in aus and "zu kopieren" in aus
    assert _zieldateien(ziel) == {}
    with nachschauen(ziel) as d:
        assert d.verbindung.execute("SELECT COUNT(*) FROM laeufe").fetchone()[0] == laeufe_vorher
        assert d.verbindung.execute("SELECT COUNT(*) FROM dateien WHERE status = 'analysiert'").fetchone()[0] > 0


def test_zu_wenig_platz_bricht_vorher_ab(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    _vorbereiten(ziel, quelle)
    monkeypatch.setattr(kopieren.pfade, "freier_platz", lambda pfad: 10)
    assert _cli("kopieren", "--ziel", ziel) == cli.FEHLER
    assert "Zu wenig Platz" in capsys.readouterr().out
    assert _zieldateien(ziel) == {}
    with nachschauen(ziel) as d:
        assert d.verbindung.execute("SELECT COUNT(*) FROM dateien WHERE status = 'kopieren_laeuft'").fetchone()[0] == 0
        letzter = d.letzter_lauf()
        assert letzter["ende"] != ""


def test_worker_zahlen(konf):
    assert kopieren.worker_zahlen(konf) == (2, max(1, os.cpu_count() or 1), "hdd")
    assert kopieren.worker_zahlen(konf, "ssd")[0] == 8
    assert kopieren.worker_zahlen(konf, "netzwerk")[0] == 4
    konf.alle()["leistung"]["kopier_worker"] = 3
    konf.alle()["leistung"]["hash_worker"] = 5
    assert kopieren.worker_zahlen(konf)[:2] == (3, 5)
    assert kopieren.worker_zahlen(konf, None, 7, 9)[:2] == (7, 9)   # Befehlszeile gewinnt
    konf.alle()["leistung"]["profil"] = "band"
    with pytest.raises(FotosortFehler):
        kopieren.worker_zahlen(konf)


def test_mit_anhang_haengt_hinter_den_stamm_der_hauptdatei():
    assert kopieren.mit_anhang(Path("/z/DSC01234.ARW"), 1, "DSC01234") == Path("/z/DSC01234_1.ARW")
    assert kopieren.mit_anhang(Path("/z/DSC01234.ARW.xmp"), 1, "DSC01234") == Path("/z/DSC01234_1.ARW.xmp")
    assert kopieren.mit_anhang(Path("/z/C0001M01.XML"), 2, "C0001") == Path("/z/C0001_2M01.XML")
    assert kopieren.mit_anhang(Path("/z/a.jpg"), 0, "a") == Path("/z/a.jpg")
    assert kopieren.mit_anhang(Path("/z/a.jpg"), 1, "") == Path("/z/a_1.jpg")
    assert kopieren.part_pfad(Path("/z/DSC01234.ARW")) == Path("/z/DSC01234.ARW.part")


# ------------------------------------------- Reste eines abgebrochenen Laufs ----


def test_liegengebliebene_part_datei_wird_entfernt_und_neu_geschrieben(baum, quelle, ziel, nachschauen, capsys):
    _vorbereiten(ziel, quelle)
    zp = _zielpfad(nachschauen, ziel, baum["analog"])
    part = kopieren.part_pfad(zp)
    _beanspruchen(nachschauen, ziel, baum["analog"], part)
    zp.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"halbfertig")
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert ".part-Dateien entfernt:                 1" in aus
    assert not part.exists()
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopiert" and Path(z["zielpfad"]) == zp
    assert zp.read_bytes() == baum["analog"].read_bytes()
    assert _ereignisse(nachschauen, ziel, kopieren.ART_PART_AUFGERAEUMT)


def test_fertige_kopie_aus_abgebrochenem_lauf_wird_nachtraeglich_bestaetigt(baum, quelle, ziel, nachschauen, capsys):
    _vorbereiten(ziel, quelle)
    zp = _zielpfad(nachschauen, ziel, baum["analog"])
    _beanspruchen(nachschauen, ziel, baum["analog"], zp)   # Absturz zwischen Umbenennen und "kopiert"
    zp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baum["analog"], zp)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert "nachtraeglich bestaetigt: 1" in capsys.readouterr().out
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopiert" and Path(z["zielpfad"]) == zp
    assert z["hash"] == hashes.blake3_datei(zp)
    assert not zp.with_name("scan_001_1.tif").exists()
    with nachschauen(ziel) as d:
        assert d.ziel_index_nach_pfad(zp) is not None


@pytest.mark.parametrize("direkt", [False, True], ids=["mit_part", "rueckfall_ohne_part"])
def test_angefangene_zieldatei_wird_nur_im_rueckfall_entfernt(
    baum, quelle, ziel, nachschauen, monkeypatch, direkt
):
    """Unter dem endgueltigen Namen wird nur im Rueckfall (ohne .part) etwas
    entfernt - und nur, wenn die Zeile es beansprucht und es kleiner als die
    Quelle ist. Im .part-Zweig kann so eine Datei nicht von uns stammen."""
    if direkt:
        monkeypatch.setattr(kopieren.pfade, "kann_ohne_ueberschreiben", lambda ordner: False)
    _vorbereiten(ziel, quelle)
    zp = _zielpfad(nachschauen, ziel, baum["analog"])
    _beanspruchen(nachschauen, ziel, baum["analog"], zp)
    zp.parent.mkdir(parents=True, exist_ok=True)
    zp.write_bytes(baum["analog"].read_bytes()[:10])   # angefangen, kleiner
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopiert"
    if direkt:
        assert Path(z["zielpfad"]) == zp
        assert zp.read_bytes() == baum["analog"].read_bytes()
        assert _ereignisse(nachschauen, ziel, kopieren.ART_ANGEFANGENE_ENTFERNT)
    else:
        assert zp.read_bytes() == baum["analog"].read_bytes()[:10]   # fremd: unangetastet
        assert Path(z["zielpfad"]) == zp.with_name("scan_001_1.tif")
        assert not _ereignisse(nachschauen, ziel, kopieren.ART_ANGEFANGENE_ENTFERNT)


def test_fremde_kopieren_laeuft_zeile_ohne_dateien_faellt_zurueck(baum, quelle, ziel, nachschauen):
    _vorbereiten(ziel, quelle)
    zp = _zielpfad(nachschauen, ziel, baum["analog"])
    _beanspruchen(nachschauen, ziel, baum["analog"], kopieren.part_pfad(zp))
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopiert" and Path(z["zielpfad"]) == zp


def test_rueckfall_fremde_datei_unter_dem_zielnamen_bleibt_nach_absturz(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """Befund B1 der Pruefung: Im Rueckfall lag der Anspruch auf dem berechneten
    Namen, unter dem eine FREMDE Datei lag; nach einem Absturz haette das
    Aufraeumen sie entfernt. Jetzt beansprucht die Zeile den Namen, den sie
    wirklich schreibt (_1), und nur der wird angefasst."""
    monkeypatch.setattr(kopieren.pfade, "kann_ohne_ueberschreiben", lambda ordner: False)
    _vorbereiten(ziel, quelle)
    zp = _zielpfad(nachschauen, ziel, baum["analog"])
    zp.parent.mkdir(parents=True, exist_ok=True)
    zp.write_bytes(b"fremdes Archivbild, klein")           # fremd, kleiner als die Quelle
    eigen = zp.with_name("scan_001_1.tif")
    eigen.write_bytes(baum["analog"].read_bytes()[:4])     # unsere angefangene Kopie
    _beanspruchen(nachschauen, ziel, baum["analog"], eigen)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert zp.read_bytes() == b"fremdes Archivbild, klein"
    assert "angefangene Zieldateien entfernt:       1" in aus
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopiert" and Path(z["zielpfad"]) == eigen
    assert eigen.read_bytes() == baum["analog"].read_bytes()
    assert not zp.with_name("scan_001_2.tif").exists()
    assert not zp.with_name("scan_001_1_1.tif").exists()


def test_absturz_zwischen_umbenennen_und_kopiert_hinterlaesst_keine_waise(baum, quelle, ziel, nachschauen, capsys):
    """Befund B2: fertige Kopie unter X_1, Zeile beansprucht noch X. Der Neustart
    findet sie ueber den schreibpfad und legt keine zweite Kopie X_2 an."""
    _vorbereiten(ziel, quelle)
    zp = _zielpfad(nachschauen, ziel, baum["analog"])
    zp.parent.mkdir(parents=True, exist_ok=True)
    zp.write_bytes(b"fremd")
    fertig = zp.with_name("scan_001_1.tif")
    shutil.copy2(baum["analog"], fertig)
    _beanspruchen(nachschauen, ziel, baum["analog"], fertig)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert "nachtraeglich bestaetigt: 1" in capsys.readouterr().out
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "kopiert" and Path(z["zielpfad"]) == fertig
    assert not zp.with_name("scan_001_2.tif").exists()
    assert zp.read_bytes() == b"fremd"


# ------------------------------------------------------------- Abbruch ----


def test_strg_c_laesst_nichts_halbes_liegen_und_fortsetzen_klappt(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    original = kopieren.wait
    aufrufe = []

    def unterbrechen(*args, **kwargs):
        aufrufe.append(1)
        if len(aufrufe) == 1:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    _vorbereiten(ziel, quelle)
    monkeypatch.setattr(kopieren, "wait", unterbrechen)
    assert _cli("kopieren", "--ziel", ziel) == cli.ABGEBROCHEN
    assert "Abgebrochen" in capsys.readouterr().out
    assert not _parts(ziel)
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert all(z["status"] in ("analysiert", "kopiert", "duplikat") for z in zeilen.values())
    for z in zeilen.values():
        if z["status"] == "kopiert":
            assert hashes.blake3_datei(Path(z["zielpfad"])) == z["hash"]
    with nachschauen(ziel) as d:
        assert d.letzter_lauf()["ende"] != ""
    # Fortsetzen: am Ende alles da.
    monkeypatch.setattr(kopieren, "wait", original)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert all(z["status"] in ("kopiert", "duplikat") for z in zeilen.values())
    assert not _parts(ziel)


_KIND = textwrap.dedent(
    """
    import os, sys, time, threading
    import blake3
    from fotosort import hashes, cli

    def langsam(quelle, ziel, stop=None, fd=None):
        h = blake3.blake3(); n = 0
        if fd is None:
            fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        with open(quelle, "rb") as ein, os.fdopen(fd, "wb") as aus:
            while True:
                block = ein.read(65536)
                if not block:
                    break
                aus.write(block); h.update(block); n += len(block)
                time.sleep(0.01)
        return h.hexdigest(), n

    hashes.kopieren_mit_hash = langsam
    sys.exit(cli.main(["kopieren", "--ziel", sys.argv[1], "--kopier-worker", "2"]))
    """
)


def _grosser_baum(wurzel: Path, anzahl: int) -> Path:
    """Dateien mit je eigenem Inhalt, damit es keine Duplikate gibt."""
    quelle = wurzel / "Quelle"
    for i in range(anzahl):
        ordner = quelle / f"ordner_{i // 8}"
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / f"IMG_{i:04d}.JPG").write_bytes(testbaum._JPEG + os.urandom(1_000_000))
    return quelle


def test_absturz_mitten_im_kopieren_und_neustart(tmp_path, archiv_basis):
    """Pflichttest: SIGKILL waehrend des Kopierens, Neustart, Ergebnis wie ungestoert."""
    quelle = _grosser_baum(tmp_path / "gross", 24)
    ziel_a = tmp_path / "ZielA"
    ziel_b = tmp_path / "ZielB"
    ziel_a.mkdir()
    ziel_b.mkdir()
    # Vergleichslauf ohne Stoerung.
    _vorbereiten(ziel_b, quelle)
    assert _cli("kopieren", "--ziel", ziel_b) == cli.OK
    erwartet = _zieldateien(ziel_b)
    assert len(erwartet) == 24

    _vorbereiten(ziel_a, quelle)
    skript = tmp_path / "kind.py"
    skript.write_text(_KIND, encoding="utf-8")
    umgebung = dict(os.environ, PYTHONPATH=str(SRC))
    kind = subprocess.Popen(
        [sys.executable, str(skript), str(ziel_a)], env=umgebung,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        frist = time.monotonic() + 60
        while time.monotonic() < frist:
            fertig = [p for p in _zieldateien(ziel_a)]
            if len(fertig) >= 3 and _parts(ziel_a):
                break
            if kind.poll() is not None:
                pytest.fail("Kindprozess war fertig, bevor er unterbrochen werden konnte")
            time.sleep(0.01)
        else:
            pytest.fail("Kindprozess kam nicht in den erwarteten Zustand")
        kind.kill()   # SIGKILL unter Linux, TerminateProcess unter Windows
    finally:
        kind.wait(timeout=30)
    assert _cli("kopieren", "--ziel", ziel_a) == cli.OK
    assert _zieldateien(ziel_a) == erwartet
    assert not _parts(ziel_a)
    kennung = db.archiv_id_datei(ziel_a).read_text(encoding="utf-8").strip()
    d = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        status = {z[0]: z[1] for z in d.verbindung.execute("SELECT status, COUNT(*) FROM dateien GROUP BY status")}
    finally:
        d.schliessen()
    assert status == {"kopiert": 24}


def test_entfernen_eigene_wartet_auf_den_virenscanner(tmp_path, monkeypatch):
    """Windows-CI: 'Zugriff verweigert' auf eine frische .part-Datei, weil der
    Virenscanner sie kurz haelt. Ein paar Versuche, dann erst ein Fehler."""
    datei = tmp_path / "x.JPG.part"
    datei.write_bytes(b"x")
    monkeypatch.setattr(kopieren, "_ENTFERNEN_VERSUCHE", (0.0, 0.0))
    echt = os.unlink
    verweigert = [2]

    def zickig(pfad):
        if verweigert[0] > 0:
            verweigert[0] -= 1
            raise PermissionError(13, "Zugriff verweigert", str(pfad))
        echt(pfad)

    monkeypatch.setattr(kopieren.os, "unlink", zickig)
    kopieren._entfernen_eigene(datei)
    assert not datei.exists() and verweigert[0] == 0
    # Dauerhaft verweigert: nach den Versuchen kommt der Fehler durch.
    datei.write_bytes(b"x")
    verweigert[0] = 99
    with pytest.raises(PermissionError):
        kopieren._entfernen_eigene(datei)
    assert datei.exists()
    # Eine fehlende Datei ist kein Fehler.
    monkeypatch.setattr(kopieren.os, "unlink", echt)
    kopieren._entfernen_eigene(tmp_path / "gibt_es_nicht.part")
