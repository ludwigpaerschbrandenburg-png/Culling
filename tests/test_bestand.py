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

import pytest

from fotosort import cli, hashes
from test_aufraeumen import antwort  # noqa: F401
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


def test_viele_gleich_grosse_archivdateien_werden_nicht_ganz_gelesen(baum, quelle, ziel, nachschauen, monkeypatch):
    """Pruefer-Befund (v0.9): Unkomprimierte RAWs sind alle gleich gross. Vor
    dem vollstaendigen Lesen vergleicht das Programm Anfang und Ende der Datei;
    nur wer dort gleich ist, wird ganz gelesen."""
    analog = Path(baum["analog"])
    groesse = analog.stat().st_size
    ordner = ziel / "2019"
    ordner.mkdir(parents=True)
    for i in range(40):
        (ordner / f"RAW_{i:04d}.JPG").write_bytes(bytes([i + 1]) * groesse)
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    gelesen: list = []
    echt = hashes.blake3_datei
    monkeypatch.setattr(hashes, "blake3_datei", lambda p, *a, **k: gelesen.append(str(p)) or echt(p, *a, **k))
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert not [p for p in gelesen if "RAW_" in p]
    assert _zeilen(nachschauen, ziel)[str(analog)]["status"] == "kopiert"


def test_abbruch_waehrend_des_bestands_schliesst_den_lauf_sauber(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """Pruefer-Befund (v0.9): Strg+C oder „Fenster zu“ waehrend der Bestand
    erfasst wird: Der Lauf endet sauber als abgebrochen, nichts haengt offen."""
    from fotosort import bestand
    _archiv_von_hand(ziel, Path(baum["analog"]))

    def abbruch(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(bestand, "erfassen", abbruch)
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.ABGEBROCHEN
    with nachschauen(ziel) as d:
        lauf = d.verbindung.execute("SELECT * FROM laeufe ORDER BY nummer DESC LIMIT 1").fetchone()
        assert lauf["ende"]                                   # Lauf ist beendet eingetragen


def test_gleich_byteweise_mit_kurzen_lesungen(tmp_path, monkeypatch):
    """Pruefer-Befund (v0.9): Ein Netzlaufwerk liefert manchmal weniger Bytes je
    Lesung. Gleiche Dateien muessen trotzdem als gleich gelten."""
    import io
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    daten = bytes(range(256)) * 40000
    a.write_bytes(daten)
    b.write_bytes(daten)
    echt_open = open

    class Kurz(io.RawIOBase):
        def __init__(self, f):
            self.f = f

        def read(self, n=-1):
            return self.f.read(min(n, 1000) if n and n > 0 else n)

        def close(self):
            self.f.close()

    def oeffnen(p, mode="r", *args, **kw):
        f = echt_open(p, mode, *args, **kw)
        return Kurz(f) if str(p) == str(b) and "b" in mode else f

    monkeypatch.setattr("builtins.open", oeffnen)
    assert hashes.gleich_byteweise(a, b) is True


def test_bereits_importiertes_bleibt_beim_aufraeumen_in_der_quelle(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Entscheidung vom 27.10.2026: Bilder, die schon im Archiv lagen, werden
    nie aus der Quelle entfernt - auch nicht beim Aufraeumen. Alles andere
    (auch Doppelte innerhalb der Quelle) wie bisher."""
    from fotosort import loeschen
    analog = Path(baum["analog"])
    _archiv_von_hand(ziel, analog)
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(analog)]["status"] == "duplikat_bestaetigt" and zeilen[str(analog)]["schon_im_archiv"] == 1
    innerhalb = [k for k, z in zeilen.items() if z["status"] == "duplikat_bestaetigt" and not z["schon_im_archiv"]]
    assert innerhalb                                          # der Testbaum hat Doppelte in der Quelle
    antwort.append("loeschen")
    capsys.readouterr()
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    aus = capsys.readouterr().out
    assert analog.exists(), aus                               # bleibt in der Quelle
    assert "bereits importiert" in aus
    nachher = _zeilen(nachschauen, ziel)
    assert nachher[str(analog)]["status"] == "duplikat_bestaetigt"
    assert all(nachher[k]["status"] == "quelle_geloescht" for k in innerhalb), \
        {k: (nachher[k]["status"], nachher[k]["fehlergrund"], nachher[k]["dateityp"]) for k in innerhalb}
    # Auch die einzige Loeschstelle selbst weigert sich (zweite Sicherung).
    with nachschauen(ziel) as d:
        zeile = d.zeile(str(analog))
    try:
        loeschen.bedingungen_pruefen(zeile, loeschen.Lesung("ok"), 0, False)
    except loeschen.Verweigert as v:
        assert "bereits importiert" in str(v)
    else:
        raise AssertionError("haette sich weigern muessen")


def test_verschieben_laesst_bereits_importiertes_stehen(baum, quelle, ziel, nachschauen):
    analog = Path(baum["analog"])
    _archiv_von_hand(ziel, analog)
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert analog.exists()
    assert _zeilen(nachschauen, ziel)[str(analog)]["schon_im_archiv"] == 1


@pytest.mark.parametrize("verschieben", [False, True])
def test_begleitdatei_eines_bereits_importierten_bildes_bleibt(baum, quelle, ziel, nachschauen, antwort, verschieben):
    """Pruefer-Befund (v0.9): Liegt ein Bild schon im Archiv, bleibt auch
    seine XMP-Datei in der Quelle - beim Aufraeumen und beim Verschieben."""
    jpg = Path(baum["sidecar_form1"]).with_suffix(".JPG")
    if not jpg.exists():
        jpg = next(p for p in Path(baum["sidecar_form1"]).parent.iterdir() if p.suffix.lower() == ".jpg")
    xmp = Path(baum["sidecar_form1"])
    _archiv_von_hand(ziel, jpg)
    assert _cli("scan", "--ziel", ziel, "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    args = ("--verschieben",) if verschieben else ()
    assert _cli("kopieren", "--ziel", ziel, *args) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(jpg)]["schon_im_archiv"] == 1
    assert zeilen[str(xmp)]["schon_im_archiv"] == 1, zeilen[str(xmp)]["status"]
    assert zeilen[str(xmp)]["status"] != "fehler", zeilen[str(xmp)]["fehlergrund"]
    if not verschieben:
        antwort.append("loeschen")
        assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert jpg.exists() and xmp.exists()


def test_jede_gleich_grosse_archivdatei_wird_nur_einmal_angelesen(tmp_path, ziel, nachschauen, monkeypatch):
    """Pruefer-Befund (v0.9): Bei vielen gleich grossen Quell- UND Archivdateien
    (unkomprimierte RAWs) wird der Anfang und das Ende jeder Archivdatei nur
    einmal je Lauf gelesen, nicht einmal je Quelldatei."""
    import testbaum
    from fotosort import kopieren
    q = tmp_path / "Q"
    quellen = [testbaum._schreiben(q / f"NEU_{i}.jpg", testbaum._JPEG + bytes([i + 1]) * 300_000) for i in range(6)]
    groesse = quellen[0].stat().st_size
    ordner = ziel / "2019"
    ordner.mkdir(parents=True)
    for i in range(15):
        (ordner / f"RAW_{i:04d}.JPG").write_bytes(bytes([200 + i]) * groesse)
    assert _cli("scan", "--ziel", ziel, "--quelle", q) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    angelesen: list = []
    echt = kopieren._rand_abdruck
    monkeypatch.setattr(kopieren, "_rand_abdruck", lambda p, g: angelesen.append(str(p)) or echt(p, g))
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    archiv = [p for p in angelesen if "RAW_" in p]
    assert archiv and len(archiv) == len(set(archiv)), sorted(archiv)
    zeilen = _zeilen(nachschauen, ziel)
    assert all(zeilen[str(p)]["status"] == "kopiert" for p in quellen)


def test_ziel_ueber_verknuepfung_oder_relativ_wird_einheitlich_gespeichert(baum, quelle, tmp_path, nachschauen, monkeypatch):
    """Pruefer-Befund (v0.11): Ein Ziel, das ueber eine Verknuepfung (unter
    Windows: Laufwerksbuchstabe eines Netzlaufwerks) oder relativ angegeben
    wird, steht in der Datenbank in genau einer Schreibweise - sonst passen
    Ziel-Index und kopierte Dateien nicht zusammen, und die Pruefsummen-Liste
    wird nie erneuert."""
    import os
    import sys
    if sys.platform.startswith("win"):
        pytest.skip("Symlinks brauchen unter Windows besondere Rechte")
    echt = tmp_path / "EchtesZiel"
    echt.mkdir()
    link = tmp_path / "ZielLink"
    link.symlink_to(echt, target_is_directory=True)
    _archiv_von_hand(echt, Path(baum["analog"]))
    monkeypatch.chdir(tmp_path)
    assert _cli("scan", "--ziel", "ZielLink", "--quelle", quelle) == cli.OK
    assert _cli("analyse", "--ziel", "ZielLink") == cli.OK
    assert _cli("kopieren", "--ziel", str(link)) == cli.OK
    wurzel = str(echt.resolve()) + os.sep
    with nachschauen(echt) as d:
        index = [r["zielpfad"] for r in d.verbindung.execute("SELECT zielpfad FROM ziel_index")]
        ziele = [r["zielpfad"] for r in d.verbindung.execute("SELECT zielpfad FROM dateien WHERE zielpfad != ''")]
    assert index and ziele
    assert all(p.startswith(wurzel) for p in index + ziele), [p for p in index + ziele if not p.startswith(wurzel)][:3]
