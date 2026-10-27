"""Reiter „Sichten“, zweiter Ausbau (Runde 3b, v0.11): Farbmarken, mehr
Filter, Live-Photos als ein Bild, Bewertungen aus vorhandenen XMP-Dateien
lesen und - auf Knopfdruck - neue XMP-Dateien anlegen, Kameradaten.

Entscheidung des Nutzers vom 28.10.2026: XMP-Dateien entstehen nur dort, wo
noch keine liegt. Eine vorhandene XMP-Datei wird nie angefasst, ein Bild
sowieso nicht. Jeder Test, der schreibt, prueft das am Archiv.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import testbaum
from fotosort import FotosortFehler, config, hashes, meldungen, sichten
from fotosort.cli import exiftool_finden


def _stand(ziel: Path) -> dict[str, tuple[str, int]]:
    return {str(p.relative_to(ziel)): (hashes.blake3_datei(p), p.stat().st_mtime_ns)
            for p in sorted(ziel.rglob("*")) if p.is_file()}


def _bew(tmp_path) -> sichten.Bewertungen:
    ordner = tmp_path / "lokal"
    ordner.mkdir(exist_ok=True)
    return sichten.Bewertungen(ordner)


# --- Farbmarken und Filter -------------------------------------------------------


def test_farbmarken_werden_gespeichert_und_einzeln_geaendert(tmp_path):
    bew = _bew(tmp_path)
    bew.setzen(["a.jpg", "b.jpg"], sterne=3)
    bew.setzen(["a.jpg"], farbe="rot")
    bew.setzen(["b.jpg"], markierung="auswahl")
    stand = bew.lesen(["a.jpg", "b.jpg", "c.jpg"])
    assert stand["a.jpg"] == sichten.Bewertung(3, "", "rot")
    assert stand["b.jpg"] == sichten.Bewertung(3, "auswahl", "")
    assert "c.jpg" not in stand
    bew.setzen(["a.jpg"], sterne=0)
    assert bew.lesen(["a.jpg"])["a.jpg"] == sichten.Bewertung(0, "", "rot")     # Farbe allein bleibt
    bew.setzen(["a.jpg"], farbe="")
    assert bew.lesen(["a.jpg"]) == {}
    with pytest.raises(FotosortFehler):
        bew.setzen(["a.jpg"], farbe="pink")


def test_alte_bewertungsdatei_bekommt_die_farbspalte(tmp_path):
    """Eine bewertungen.db aus v0.8 bis v0.10 (ohne Farbe) wird weiter benutzt."""
    import sqlite3
    ordner = tmp_path / "lokal"
    ordner.mkdir()
    with sqlite3.connect(ordner / sichten.DATEINAME) as v:
        v.execute("CREATE TABLE bewertungen (schluessel TEXT PRIMARY KEY, sterne INTEGER NOT NULL DEFAULT 0,"
                  " markierung TEXT NOT NULL DEFAULT '', geaendert REAL NOT NULL DEFAULT 0)")
        v.execute("INSERT INTO bewertungen VALUES ('x.jpg', 4, 'auswahl', 1.0)")
    bew = sichten.Bewertungen(ordner)
    assert bew.lesen(["x.jpg"])["x.jpg"] == sichten.Bewertung(4, "auswahl", "")
    bew.setzen(["x.jpg"], farbe="blau")
    assert bew.lesen(["x.jpg"])["x.jpg"] == sichten.Bewertung(4, "auswahl", "blau")


def test_neue_filter():
    B = sichten.Bewertung
    assert sichten.passt(None, "unbewertet") and sichten.passt(B(0, "", "rot"), "unbewertet")
    assert not sichten.passt(B(1, "", ""), "unbewertet") and not sichten.passt(B(0, "ausschuss", ""), "unbewertet")
    assert sichten.passt(B(0, "", "rot"), "farbe_rot") and not sichten.passt(B(5, "", "gelb"), "farbe_rot")
    assert sichten.passt(B(2, "", ""), "ab2") and sichten.passt((2, ""), "ab2")    # alte Form geht weiter
    for wert, _text in meldungen.SICHTEN_FILTER:
        assert wert in sichten.FILTER


# --- Live-Photos -------------------------------------------------------------------


def test_live_photo_ist_ein_bild(ziel):
    """iPhone: IMG_0001.HEIC und IMG_0001.MOV gleichen Namens sind eine
    Aufnahme (Live-Photo). Ein Video neben einem JPG gleichen Namens bleibt
    ein eigenes Bild - alte Kameras zaehlen Fotos und Videos gemeinsam."""
    ordner = ziel / "2026" / "2026-01-01"
    for name in ("IMG_0001.HEIC", "IMG_0001.MOV", "IMG_0002.JPG", "IMG_0002.MOV"):
        testbaum._schreiben(ordner / name, testbaum._JPEG)
    bilder = sichten.bilder(ordner, ziel, config.Konfiguration())
    namen = [b.name for b in bilder]
    assert namen == ["IMG_0001.HEIC", "IMG_0002.JPG", "IMG_0002.MOV"], namen
    live = bilder[0]
    assert live.art == "foto" and set(p.name for p in live.dateien) == {"IMG_0001.HEIC", "IMG_0001.MOV"}


# --- XMP lesen ------------------------------------------------------------------------


@pytest.mark.parametrize("inhalt, erwartet", [
    ('<rdf:Description xmp:Rating="4" xmp:Label="Red"/>', (4, "", "rot")),
    ("<rdf:Description><xmp:Rating>2</xmp:Rating><xmp:Label>Grün</xmp:Label></rdf:Description>", (2, "", "gruen")),
    ('<rdf:Description xmp:Rating="-1"/>', (0, "ausschuss", "")),
    ('<rdf:Description xmp:Label="Purple"/>', (0, "", "lila")),
    ('<rdf:Description xmp:Rating="0"/>', None),
    ("kaputt <<<", None),
])
def test_bewertung_aus_xmp_lesen(tmp_path, inhalt, erwartet):
    datei = tmp_path / "IMG_0001.xmp"
    datei.write_text(f'<x:xmpmeta xmlns:x="adobe:ns:meta/">{inhalt}</x:xmpmeta>', encoding="utf-8")
    assert sichten.xmp_lesen(datei) == (sichten.Bewertung(*erwartet) if erwartet else None)


def test_bilder_kennen_ihre_xmp_datei(ziel):
    ordner = ziel / "2026" / "a"
    testbaum._schreiben(ordner / "IMG_0001.CR2", testbaum._JPEG)
    testbaum._schreiben(ordner / "img_0001.XMP", b"<x/>")                 # andere Schreibweise
    testbaum._schreiben(ordner / "IMG_0002.JPG", testbaum._JPEG)
    testbaum._schreiben(ordner / "IMG_0002.JPG.xmp", b"<x/>")             # darktable-Form
    testbaum._schreiben(ordner / "IMG_0003.JPG", testbaum._JPEG)
    b1, b2, b3 = sichten.bilder(ordner, ziel, config.Konfiguration())
    assert [p.name for p in b1.xmp] == ["img_0001.XMP"]
    assert [p.name for p in b2.xmp] == ["IMG_0002.JPG.xmp"]
    assert b3.xmp == ()


# --- XMP anlegen ----------------------------------------------------------------------


def _archiv_mit_bewertungen(ziel: Path, tmp_path):
    ordner = ziel / "2026" / "2026-01-01"
    for name in ("IMG_0001.CR2", "IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG", "IMG_0004.JPG"):
        testbaum._schreiben(ordner / name, testbaum._JPEG)
    vorhandene = testbaum._schreiben(ordner / "IMG_0003.xmp", b"<x:xmpmeta>von Lightroom</x:xmpmeta>")
    bew = _bew(tmp_path)
    bilder = {b.name: b for b in sichten.bilder(ordner, ziel, config.Konfiguration())}
    bew.setzen([bilder["IMG_0001.CR2"].schluessel], sterne=5)
    bew.setzen([bilder["IMG_0001.CR2"].schluessel], farbe="gruen")
    bew.setzen([bilder["IMG_0002.JPG"].schluessel], markierung="ausschuss")
    bew.setzen([bilder["IMG_0003.JPG"].schluessel], sterne=2)                 # hat schon eine XMP
    return ordner, vorhandene, bew


def test_xmp_nur_wo_noch_keine_liegt(ziel, tmp_path):
    ordner, vorhandene, bew = _archiv_mit_bewertungen(ziel, tmp_path)
    vorher = _stand(ziel)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert (e.neu, e.vorhanden, e.fehler) == (2, 1, 0), e
    # Die vorhandene XMP-Datei ist Byte fuer Byte und in der Zeit unveraendert.
    nachher = _stand(ziel)
    for name, wert in vorher.items():
        assert nachher[name] == wert, name
    neu = sorted(set(nachher) - set(vorher))
    assert [Path(n).name for n in neu] == ["IMG_0001.xmp", "IMG_0002.xmp"]
    assert not list(ziel.rglob("*.part"))
    eins = (ordner / "IMG_0001.xmp").read_text(encoding="utf-8")
    assert 'xmp:Rating="5"' in eins and 'xmp:Label="Green"' in eins
    assert sichten.xmp_lesen(ordner / "IMG_0001.xmp") == sichten.Bewertung(5, "", "gruen")
    assert sichten.xmp_lesen(ordner / "IMG_0002.xmp") == sichten.Bewertung(0, "ausschuss", "")
    # Zweiter Durchgang: alles hat jetzt eine XMP-Datei - nichts wird neu geschrieben.
    vorher = _stand(ziel)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert (e.neu, e.vorhanden) == (0, 3) and _stand(ziel) == vorher


def test_xmp_anlegen_ueberschreibt_auch_im_wettlauf_nichts(ziel, tmp_path, monkeypatch):
    """Legt ein anderes Programm die XMP-Datei genau zwischen Nachsehen und
    Schreiben an, bleibt seine Datei stehen: Das Umbenennen ueberschreibt nie."""
    ordner, _vorhandene, bew = _archiv_mit_bewertungen(ziel, tmp_path)
    echt = sichten._neu_schreiben

    def gleich_davor_angelegt(datei, inhalt):
        if datei.name == "IMG_0001.xmp":
            datei.write_bytes(b"fremd")
        return echt(datei, inhalt)

    monkeypatch.setattr(sichten, "_neu_schreiben", gleich_davor_angelegt)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert (ordner / "IMG_0001.xmp").read_bytes() == b"fremd"
    assert e.vorhanden == 2 and e.neu == 1
    assert not list(ziel.rglob("*.part"))


def test_xmp_anlegen_nie_ausserhalb_des_archivs(ziel, tmp_path):
    bew = _bew(tmp_path)
    bew.setzen(["../draussen.jpg", "a/../../auch.jpg"], sterne=3)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert e.neu == 0 and not list(tmp_path.glob("*.xmp")) and not (ziel.parent / "draussen.xmp").exists()


def test_xmp_fuer_verschwundene_bilder_wird_uebersprungen(ziel, tmp_path):
    bew = _bew(tmp_path)
    bew.setzen(["2026/weg.jpg"], sterne=3)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert e.neu == 0 and e.fehlt == 1 and not list(ziel.rglob("*.xmp"))


# --- Kameradaten ----------------------------------------------------------------------


def test_kameradaten_als_text():
    werte = {"Make": "SONY", "Model": "ILCE-7CM2", "LensModel": "FE 50mm F1.8", "FNumber": 1.8,
             "ExposureTime": "1/250", "ISO": 400, "FocalLength": "50.0 mm", "DateTimeOriginal": "2026:01:15 14:03:22"}
    text = meldungen.sichten_kameradaten(werte)
    for teil in ("f/1,8", "1/250 s", "ISO 400", "50 mm", "ILCE-7CM2", "FE 50mm F1.8", "15.01.2026 14:03"):
        assert teil in text, (teil, text)
    assert "·" not in text
    assert meldungen.sichten_kameradaten({}) == ""


def test_kameradaten_aus_der_datei(tmp_path):
    programm, _wo = exiftool_finden()
    assert programm, "ExifTool fehlt im Container"
    from fotosort import vorschau
    baum = testbaum.erzeugen(tmp_path / "baum")
    leser = vorschau.Vorschauleser(programm)
    try:
        werte = leser.kameradaten(baum["jpg"])
    finally:
        leser.schliessen()
    assert werte.get("Model") == "ILCE-7CM2"


# --- Nacharbeit nach der Pruefung (v0.11) -----------------------------------------------


def test_geloeschte_bewertung_kommt_nicht_aus_der_xmp_zurueck(tmp_path):
    """Pruefer-Befund: Wer die Sterne eines Bilds mit XMP-Datei auf 0 setzt,
    darf sie nach einem Neustart nicht wieder aus der XMP bekommen. Dafuer
    bleibt eine leere Zeile stehen ("bewusst ohne Bewertung")."""
    bew = _bew(tmp_path)
    bew.setzen(["a.jpg"], sterne=3, leer_merken=True)
    bew.setzen(["a.jpg"], sterne=0, leer_merken=True)
    assert bew.lesen(["a.jpg"]) == {"a.jpg": sichten.Bewertung()}
    assert sichten.passt(bew.lesen(["a.jpg"])["a.jpg"], "unbewertet")
    bew.setzen(["b.jpg"], sterne=3)
    bew.setzen(["b.jpg"], sterne=0)                      # ohne XMP: Zeile weg wie bisher
    assert bew.lesen(["b.jpg"]) == {}


def test_leere_zeile_schreibt_keine_xmp(ziel, tmp_path):
    ordner = ziel / "2026" / "a"
    testbaum._schreiben(ordner / "IMG_0001.JPG", testbaum._JPEG)
    bew = _bew(tmp_path)
    bew.setzen(["2026/a/IMG_0001.JPG"], sterne=0, leer_merken=True)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert (e.neu, e.ohne) == (0, 0) and not list(ziel.rglob("*.xmp"))


def test_gleicher_stamm_bei_zwei_bildern_bekommt_eigene_xmp(ziel, tmp_path):
    """Pruefer-Befund: IMG_1.JPG und IMG_1.MOV (Live-Photo als JPG gespeichert)
    sind zwei Bilder - eine gemeinsame IMG_1.xmp gehoerte keinem eindeutig.
    Dann bekommt jedes "<Name>.<Endung>.xmp", und "a.b.xmp" gehoert nicht zu "a.CR2"."""
    ordner = ziel / "2026" / "b"
    for name in ("IMG_1.JPG", "IMG_1.MOV", "a.CR2", "a.b.CR2"):
        testbaum._schreiben(ordner / name, testbaum._JPEG)
    testbaum._schreiben(ordner / "a.b.xmp", b'<x xmp:Rating="2"/>')
    bilder = {b.name: b for b in sichten.bilder(ordner, ziel, config.Konfiguration())}
    assert bilder["a.CR2"].xmp == () and [p.name for p in bilder["a.b.CR2"].xmp] == ["a.b.xmp"]
    bew = _bew(tmp_path)
    bew.setzen([bilder["IMG_1.JPG"].schluessel], sterne=4)
    bew.setzen([bilder["IMG_1.MOV"].schluessel], sterne=1)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert e.neu == 2 and not (ordner / "IMG_1.xmp").exists()
    assert sichten.xmp_lesen(ordner / "IMG_1.JPG.xmp").sterne == 4
    assert sichten.xmp_lesen(ordner / "IMG_1.MOV.xmp").sterne == 1


def test_xmp_ohne_sicheres_umbenennen_wird_nicht_angelegt(ziel, tmp_path, monkeypatch):
    """Kann das Laufwerk nicht sicher umbenennen, entsteht keine XMP-Datei -
    lieber keine als eine halbe unter dem endgueltigen Namen. Die eigene .part
    wird entfernt, der Grund genannt."""
    from fotosort import pfade
    ordner, _vorhandene, bew = _archiv_mit_bewertungen(ziel, tmp_path)

    def kein_noreplace(von, nach):
        raise pfade.KeinNoReplace("exFAT")

    monkeypatch.setattr(sichten.pfade, "umbenennen_ohne_ueberschreiben", kein_noreplace)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert e.neu == 0 and e.fehler == 2 and e.gruende
    assert not list(ziel.rglob("*.part")) and not (ordner / "IMG_0001.xmp").exists()


def test_schreibfehler_hinterlaesst_keine_part(ziel, tmp_path, monkeypatch):
    ordner, _vorhandene, bew = _archiv_mit_bewertungen(ziel, tmp_path)

    def voll(fd):
        raise OSError(28, "Kein Platz auf dem Geraet")

    monkeypatch.setattr(sichten.os, "fsync", voll)
    e = sichten.xmp_anlegen(ziel, bew, config.Konfiguration())
    assert e.neu == 0 and e.fehler == 2 and "Platz" in " ".join(e.gruende)
    assert not list(ziel.rglob("*.part"))
    monkeypatch.undo()
    assert sichten.xmp_anlegen(ziel, bew, config.Konfiguration()).neu == 2   # spaeter geht es


def test_xmp_ergebnis_einzahl():
    e = sichten.XmpErgebnis(neu=1)
    assert meldungen.sichten_xmp_ergebnis(e).startswith("1 XMP-Datei neu angelegt")
