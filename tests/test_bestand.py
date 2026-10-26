"""Bestand des Archivs kennen und „bereits importiert“ melden (Runde 3a,
Entscheidung vom 26.10.2026).

Ein Archiv, das jemand von Hand angelegt hat ("2021.01/OMA_0001.JPG"), hat
keinen Ziel-Index. Damit ein Bild, das dort schon liegt, nicht ein zweites
Mal kopiert wird, erfasst der Scan den Bestand (nur Namen, Groessen, Zeiten -
nichts wird gelesen), und das Kopieren liest nur die Archivdateien, die genau
so gross sind wie die Quelldatei. Gemeldet wird je Quelle: „N Bilder dieser
Quelle sind bereits importiert“. Im Archiv wird dabei nichts veraendert.
"""

from __future__ import annotations

from pathlib import Path

from fotosort import cli, hashes
from test_kopieren import _cli, _zeilen


def _archiv_von_hand(ziel: Path, *quelldateien: Path) -> dict[str, tuple[bytes, int]]:
    """Kopien einiger Quelldateien unter anderem Namen in einem Ordner anderer
    Schreibweise - wie ein Archiv, das jemand selbst gepflegt hat."""
    ordner = ziel / "2021.01"
    ordner.mkdir(parents=True, exist_ok=True)
    for i, q in enumerate(quelldateien):
        (ordner / f"VON_HAND_{i:04d}{q.suffix}").write_bytes(q.read_bytes())
    (ordner / "ANDERES.JPG").write_bytes(b"ganz anderes Bild" * 10)
    return _stand(ziel)


def _stand(ziel: Path) -> dict[str, tuple[bytes, int]]:
    return {str(p.relative_to(ziel)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(ziel.rglob("*")) if p.is_file() and ".fotosortierer" not in p.parts}


def test_bild_das_schon_im_archiv_liegt_wird_nur_gemeldet(baum, quelle, ziel, nachschauen, capsys):
    analog = Path(baum["analog"])
    vorher = _archiv_von_hand(ziel, analog)
    capsys.readouterr()
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    aus = capsys.readouterr().out
    assert "Bestand des Archivs" in aus and "vermutlich bereits importiert" in aus
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    capsys.readouterr()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "bereits importiert" in aus
    assert _zeilen(nachschauen, ziel)[str(analog)]["status"] == "duplikat"
    # Auch im Fenster und im Bericht, je Quelle.
    from fotosort.oberflaeche import ablauf as ablauf_modul
    zf = ablauf_modul.Ablauf(ziel=str(ziel), ordner=ziel.parent / "ob").zusammenfassung("kopieren")
    assert any(str(z[0]).startswith("bereits importiert") and z[1] == "1" for z in zf["zeilen"]), zf
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    bericht = sorted((ziel / ".fotosortierer" / "berichte").glob("bericht_*.txt"))[-1].read_text(encoding="utf-8")
    assert "bereits importiert" in bericht
    # Nichts im vorhandenen Bestand hat sich veraendert, und das Bild liegt nur einmal da.
    nachher = _stand(ziel)
    assert all(nachher[k] == v for k, v in vorher.items())
    inhalt = analog.read_bytes()
    assert sum(1 for b, _t in nachher.values() if b == inhalt) == 1


def test_gleiche_groesse_anderer_inhalt_wird_kopiert(baum, quelle, ziel, nachschauen):
    analog = Path(baum["analog"])
    ordner = ziel / "2021.01"
    ordner.mkdir(parents=True)
    gleich_gross = bytearray(analog.read_bytes())
    gleich_gross[-3] ^= 0xFF                                 # ein Byte anders, gleiche Groesse
    (ordner / "FAST_GLEICH.JPG").write_bytes(bytes(gleich_gross))
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _zeilen(nachschauen, ziel)[str(analog)]["status"] == "kopiert"
    assert (ordner / "FAST_GLEICH.JPG").read_bytes() == bytes(gleich_gross)


def test_bestand_erfassen_liest_keine_datei(baum, quelle, ziel, monkeypatch):
    """Der Scan liest im Archiv nur Namen und Groessen - auch bei Tausenden von
    Bildern schnell, und auf einer Festplatte ohne Springen."""
    _archiv_von_hand(ziel, Path(baum["analog"]))
    gelesen: list = []
    echt = hashes.blake3_datei
    monkeypatch.setattr(hashes, "blake3_datei", lambda p, *a, **k: gelesen.append(p) or echt(p, *a, **k))
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert not [p for p in gelesen if str(ziel) in str(p)]


def test_quellordner_mit_anderem_datum_wird_gemeldet(tmp_path, ziel, nachschauen, capsys):
    """Ordner sagt März, Bild ist vom Mai: nur ein Hinweis - einsortiert wird
    nach dem Aufnahmedatum, in der Quelle bleibt alles, wie es ist."""
    import testbaum
    from fotosort import analyse
    from test_kopieren import _ereignisse
    q = tmp_path / "Q"
    falsch = testbaum._schreiben(q / "2021.03" / "FALSCH.jpg", testbaum._JPEG)
    richtig = testbaum._schreiben(q / "2021.05" / "RICHTIG.jpg", testbaum._JPEG)
    ohne = testbaum._schreiben(q / "Urlaub" / "OHNE.jpg", testbaum._JPEG)
    reise = testbaum._schreiben(q / "2021-04-28 bis 05-12 Italien" / "REISE.jpg", testbaum._JPEG)
    testbaum._exiftool([["-q", "-overwrite_original", "-DateTimeOriginal=2021:05:10 12:00:00", str(p)]
                        for p in (falsch, richtig, ohne, reise)])
    assert _cli("scan", "--ziel", ziel, "--quelle", q) == cli.OK
    capsys.readouterr()
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Ordner nennt ein anderes Datum" in aus
    gemeldet = {e["pfad"] for e in _ereignisse(nachschauen, ziel, analyse.ART_ORDNER_DATUM)}
    assert gemeldet == {str(falsch)}
