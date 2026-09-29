"""Reiter „Sichten“, erster Ausbau (Entscheidung 15, v0.8; SPEC §8).

Der Reiter zeigt das Archiv und nimmt Bewertungen auf - er veraendert,
verschiebt oder loescht nie eine Datei. Jeder Test, der bewertet, prueft
deshalb am Ende, dass das Archiv Byte fuer Byte und mit denselben
Aenderungszeiten dasteht wie vorher.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import testbaum
from fotosort import FotosortFehler, config, hashes, sichten, vorschau
from fotosort.cli import exiftool_finden


def _archiv(ziel: Path) -> dict[str, Path]:
    """Ein kleines Archiv nach der Standardvorlage, wie es nach dem Kopieren aussieht."""
    tag = ziel / "2026" / "2026-01-01 Geburtstag Oma"
    frueher = ziel / "2025" / "2025-12-24"
    dateien = {
        "raw": tag / "IMG_0001.CR2",
        "jpg_zu_raw": tag / "IMG_0001.JPG",
        "xmp": tag / "IMG_0001.xmp",
        "jpg": tag / "IMG_0002.jpg",
        "heic": tag / "IMG_0003.HEIC",
        "video": tag / "MVI_0004.MP4",
        "notiz": tag / "notiz.txt",
        "frueher": frueher / "DSC_0100.JPG",
    }
    for name, pfad in dateien.items():
        testbaum._schreiben(pfad, testbaum._JPEG if pfad.suffix.lower() in (".jpg", ".cr2", ".heic") else b"x" * 10)
    testbaum._schreiben(ziel / ".fotosortierer" / "fotosort.db.sicherung", b"db")
    return {"tag": tag, "frueher": frueher, **dateien}


def _stand(ziel: Path) -> dict[str, tuple[str, int]]:
    """Inhalt und Aenderungszeit jeder Datei im Archiv."""
    return {str(p.relative_to(ziel)): (hashes.blake3_datei(p), p.stat().st_mtime_ns)
            for p in sorted(ziel.rglob("*")) if p.is_file()}


def test_ordner_neueste_zuerst_ohne_programmordner(ziel):
    a = _archiv(ziel)
    (ziel / ".fotosort_messung_x").mkdir()
    (ziel / "_Ohne_Datum").mkdir()
    (ziel / "Analog").mkdir()
    assert sichten.ordner(ziel) == [ziel / "2026", ziel / "2025", ziel / "Analog", ziel / "_Ohne_Datum"]
    assert sichten.ordner(ziel, ziel / "2026") == [a["tag"]]
    assert sichten.ordner(ziel, a["tag"]) == []


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="ohne Verknuepfungen")
def test_ordner_folgt_keiner_verknuepfung_aus_dem_archiv(ziel, tmp_path):
    _archiv(ziel)
    draussen = tmp_path / "draussen"
    draussen.mkdir()
    try:
        (ziel / "2026" / "verlinkt").symlink_to(draussen, target_is_directory=True)
    except OSError:
        pytest.skip("Verknuepfungen nicht erlaubt")
    assert ziel / "2026" / "verlinkt" not in sichten.ordner(ziel, ziel / "2026")
    with pytest.raises(FotosortFehler):
        sichten.bilder(draussen, ziel, config.Konfiguration())


def test_bilder_einer_aufnahme_sind_ein_bild(ziel):
    a = _archiv(ziel)
    bilder = sichten.bilder(a["tag"], ziel, config.Konfiguration())
    assert [b.name for b in bilder] == ["IMG_0001.CR2", "IMG_0002.jpg", "IMG_0003.HEIC", "MVI_0004.MP4"]
    raw = bilder[0]
    # Die Bewertung gehoert zur Hauptdatei (RAW vor Foto, wie beim Gruppieren),
    # gezeigt wird das JPG daneben - das ist schneller als die Vorschau im RAW.
    assert raw.haupt == a["raw"] and raw.anzeige == a["jpg_zu_raw"]
    assert set(raw.dateien) == {a["raw"], a["jpg_zu_raw"]}           # Sidecar und Notiz zaehlen nicht
    assert raw.schluessel == "2026/2026-01-01 Geburtstag Oma/IMG_0001.CR2"
    assert bilder[3].art == "video"


def test_bewertungen_bleiben_und_das_archiv_bleibt_unberuehrt(ziel, tmp_path):
    a = _archiv(ziel)
    vorher = _stand(ziel)
    lokal = tmp_path / "archive" / "kennung"
    lokal.mkdir(parents=True)
    bew = sichten.Bewertungen(lokal)
    bilder = sichten.bilder(a["tag"], ziel, config.Konfiguration())
    s = [b.schluessel for b in bilder]
    bew.setzen(s[:2], sterne=4)
    bew.setzen([s[1]], markierung="auswahl")
    bew.setzen([s[2]], markierung="ausschuss")
    bew.setzen([s[3]], sterne=2)
    bew.setzen([s[3]], sterne=0)                                   # zurueck auf nichts
    neu = sichten.Bewertungen(lokal)                               # nach einem Neustart
    assert neu.lesen(s) == {s[0]: (4, ""), s[1]: (4, "auswahl"), s[2]: (0, "ausschuss")}
    assert (lokal / sichten.DATEINAME).is_file()
    # Nichts im Archiv hat sich veraendert - kein Byte, keine Aenderungszeit, keine neue Datei.
    assert _stand(ziel) == vorher


def test_bewertung_nur_mit_gueltigen_werten(tmp_path):
    bew = sichten.Bewertungen(tmp_path)
    for falsch in ({"sterne": 6}, {"sterne": -1}, {"markierung": "loeschen"}, {"sterne": True}):
        with pytest.raises(FotosortFehler):
            bew.setzen(["a.jpg"], **falsch)
    assert bew.lesen(["a.jpg"]) == {}


def test_filter(ziel, tmp_path):
    assert sichten.passt(None, "alle") and not sichten.passt(None, "ab1")
    assert sichten.passt((3, ""), "ab3") and not sichten.passt((2, "auswahl"), "ab3")
    assert sichten.passt((0, "auswahl"), "auswahl") and not sichten.passt((5, ""), "auswahl")
    assert sichten.passt((0, "ausschuss"), "ausschuss") and not sichten.passt((0, "ausschuss"), "auswahl")
    with pytest.raises(FotosortFehler):
        sichten.passt(None, "irgendwas")


def test_bewertungen_sind_eine_eigene_datei_neben_der_datenbank(tmp_path):
    """Die Hauptdatenbank bleibt einstraengig (Arbeitsprozess): Das Sichten geht
    auch, waehrend ein Schritt laeuft, und fasst fotosort.db nie an."""
    bew = sichten.Bewertungen(tmp_path)
    bew.setzen(["x.jpg"], sterne=5)
    assert not (tmp_path / "fotosort.db").exists()
    with sqlite3.connect(tmp_path / sichten.DATEINAME) as v:
        assert v.execute("SELECT sterne, markierung FROM bewertungen WHERE schluessel = 'x.jpg'").fetchone() == (5, "")


def test_vorschau_aus_der_raw_datei(tmp_path):
    """Qt liest kein RAW. Die eingebettete Vorschau kommt ueber ExifTool - samt
    Drehung, die im RAW steht; die Datei selbst bleibt unberuehrt."""
    programm, _wo = exiftool_finden()
    assert programm, "ExifTool fehlt im Container"
    klein = testbaum._schreiben(tmp_path / "klein.jpg", testbaum._JPEG)
    vorlage = testbaum._schreiben(tmp_path / "vorlage.jpg", testbaum._JPEG)
    testbaum._exiftool([["-q", "-overwrite_original", f"-ThumbnailImage<={klein}", "-Orientation#=6", str(vorlage)]])
    raw = testbaum._schreiben(tmp_path / "IMG_0009.NEF", vorlage.read_bytes())   # ExifTool erkennt den Inhalt
    vorher = (hashes.blake3_datei(raw), raw.stat().st_mtime_ns)
    leser = vorschau.Vorschauleser(programm)
    try:
        daten, drehung = leser.lesen(raw)
        assert daten is not None and daten[:2] == b"\xff\xd8" and drehung == 6
        assert leser.lesen(tmp_path / "gibt-es-nicht.nef") == (None, 1)
        leer = testbaum._schreiben(tmp_path / "leer.nef", b"kein bild")
        assert leser.lesen(leer) == (None, 1)
        assert leser.lesen(tmp_path / "zeile\numbruch.nef") == (None, 1)   # geht nie an ExifTool
    finally:
        leser.schliessen()
    assert (hashes.blake3_datei(raw), raw.stat().st_mtime_ns) == vorher


def test_vorschauleser_startet_nach_dem_schliessen_nichts_mehr(tmp_path, monkeypatch):
    """Pruefer-Befund (v0.8): Ein Hintergrundstrang, der erst nach dem
    Schliessen an die Reihe kommt, darf kein neues ExifTool starten - es
    liefe sonst nach dem Ende des Programms weiter."""
    gestartet: list = []

    class Prozess:
        def __init__(self, programm):
            gestartet.append(self)
            self.beendet = False

        def lesen(self, pfade_typ, limit=None, argumente=None):
            return {}

        def beenden(self):
            self.beendet = True

    monkeypatch.setattr(vorschau.metadaten, "_Prozess", Prozess)
    raw = testbaum._schreiben(tmp_path / "a.nef", b"x")
    leser = vorschau.Vorschauleser("exiftool")
    leser.lesen(raw)
    assert len(gestartet) == 1
    leser.schliessen()
    assert gestartet[0].beendet
    assert leser.lesen(raw) == (None, 1) and len(gestartet) == 1


def test_kleine_vorschau_holt_das_grosse_bild_nur_wenn_noetig(tmp_path, monkeypatch):
    """Pruefer-Befund (v0.8): Fuer die Uebersicht erst PreviewImage und
    ThumbnailImage; das oft mehrere MB grosse JpgFromRaw nur, wenn beide fehlen."""
    import base64
    anfragen: list[list[str]] = []
    jpeg = "base64:" + base64.b64encode(testbaum._JPEG).decode()

    class Prozess:
        def __init__(self, programm):
            pass

        def lesen(self, pfade_typ, limit=None, argumente=None):
            anfragen.append(argumente)
            pfad = pfade_typ[0][0]
            if "-JpgFromRaw" in argumente and "ohne" in pfad:
                return {pfad: {"JpgFromRaw": jpeg}}
            if "-PreviewImage" in argumente and "mit" in pfad:
                return {pfad: {"PreviewImage": jpeg, "Orientation": "1"}}
            return {pfad: {}}

        def beenden(self):
            pass

    monkeypatch.setattr(vorschau.metadaten, "_Prozess", Prozess)
    mit = testbaum._schreiben(tmp_path / "mit.nef", b"x")
    ohne = testbaum._schreiben(tmp_path / "ohne.nef", b"x")
    leser = vorschau.Vorschauleser("exiftool")
    assert leser.lesen(mit)[0] == testbaum._JPEG
    assert len(anfragen) == 1 and "-JpgFromRaw" not in anfragen[0]
    anfragen.clear()
    assert leser.lesen(ohne)[0] == testbaum._JPEG
    assert "-JpgFromRaw" not in anfragen[0] and "-JpgFromRaw" in anfragen[1]
    leser.schliessen()


def test_unerreichbarer_pfad_ist_eine_meldung_kein_absturz(ziel, monkeypatch):
    _archiv(ziel)

    def weg(_p):
        raise OSError(1231, "Netzwerkadresse nicht erreichbar")

    monkeypatch.setattr(sichten.pfade, "aufloesen", weg)
    with pytest.raises(FotosortFehler):
        sichten.ordner(ziel)
    with pytest.raises(FotosortFehler):
        sichten.bilder(ziel / "2026", ziel, config.Konfiguration())
