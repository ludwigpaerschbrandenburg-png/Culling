"""Phase 6, Nacharbeit: Befunde des unabhaengigen Pruefers zum Kopier-Umbau."""

from __future__ import annotations

import os
from pathlib import Path

import testbaum
from fotosort import cli, hashes, kopieren, pfade
from test_kopieren import _cli, _ereignisse, _zeilen


def _zwei_gleiche(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Zwei inhaltsgleiche JPEGs mit gleichem Datum und Modell in zwei Ordnern:
    beide wollen in denselben Zielordner."""
    testbaum.exiftool_pfad()
    quelle = tmp_path / "q"
    a = quelle / "a" / "A.JPG"
    b = quelle / "b" / "B.JPG"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_bytes(testbaum._JPEG)
    testbaum._exiftool([["-overwrite_original", "-EXIF:DateTimeOriginal=2026:01:01 12:30:00",
                         "-EXIF:Model=ILCE-7CM2", str(a)]])
    b.write_bytes(a.read_bytes())
    return quelle, a, b


def test_duplikat_in_derselben_runde_zeigt_auf_den_echten_endnamen(tmp_path, ziel, nachschauen, monkeypatch):
    """Fund 2: Ein Fremdprozess belegt den geplanten Namen zwischen Planung und
    Umbenennen. Das Duplikat derselben Runde muss danach auf die Datei zeigen,
    die wirklich unsere ist (A_1.JPG), nicht auf die fremde."""
    quelle, a, b = _zwei_gleiche(tmp_path)
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    original = pfade.umbenennen_ohne_ueberschreiben
    einmal = []

    def fremder(von, nach):
        if Path(nach).name in ("A.JPG", "B.JPG") and not einmal:
            einmal.append(1)
            Path(nach).write_bytes(b"FREMD")
        return original(von, nach)

    monkeypatch.setattr(kopieren.pfade, "umbenennen_ohne_ueberschreiben", fremder)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    kopiert = [z for z in zeilen.values() if z["status"] == "kopiert"]
    dups = [z for z in zeilen.values() if z["status"] == "duplikat"]
    assert len(kopiert) == 1 and len(dups) == 1
    assert dups[0]["zielpfad"] == kopiert[0]["zielpfad"]
    assert Path(kopiert[0]["zielpfad"]).read_bytes() == a.read_bytes()
    assert Path(kopiert[0]["zielpfad"]).stem.endswith("_1")
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert {z["status"] for z in zeilen.values()} == {"geprueft", "duplikat_bestaetigt"}


def test_ziel_index_traegt_die_zeit_der_zieldatei(baum, quelle, ziel, nachschauen, monkeypatch):
    """Fund 3: Scheitert utime, steht im Ziel-Index trotzdem die Zeit, die die
    Datei wirklich traegt - nicht die der Quelle."""
    from test_kopieren import _vorbereiten
    _vorbereiten(ziel, quelle)
    monkeypatch.setattr(kopieren.os, "utime", lambda *a, **k: (_ for _ in ()).throw(OSError(1, "nein")))
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    with nachschauen(ziel) as d:
        for z in d.verbindung.execute("SELECT * FROM ziel_index"):
            p = Path(z["zielpfad"])
            assert abs(float(z["mtime"]) - p.stat().st_mtime) < 0.001, p
