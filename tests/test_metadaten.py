"""ExifTool-Pool: dauerhaft laufende Prozesse, Stapel, JSON (SPEC Abschnitt 7)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import testbaum
from fotosort import metadaten
from fotosort.dateitypen import FOTO, RAW, SIDECAR, VIDEO


@pytest.fixture
def pool():
    with metadaten.ExifToolPool(testbaum.exiftool_pfad(), 2) as p:
        yield p


def test_jpeg_und_raw_liefern_datum_und_modell(pool, baum):
    ergebnis = pool.lesen([(str(baum["jpg"]), FOTO), (str(baum["raw"]), RAW)])
    for pfad in (baum["jpg"], baum["raw"]):
        felder = ergebnis[metadaten.schluessel(pfad)]
        assert felder["DateTimeOriginal"] == "2026:01:01 12:30:00"
        assert felder["Model"] == "ILCE-7CM2"
        assert felder["Make"] == "SONY"


def test_video_mit_offset_liefert_creationdate(pool, baum):
    felder = pool.lesen([(str(baum["video_mit_offset"]), VIDEO)])[metadaten.schluessel(baum["video_mit_offset"])]
    assert felder["CreationDate"] == "2026:02:10 10:00:00+01:00"
    assert felder["CreateDate"] == "2026:02:10 09:00:00"


def test_video_nur_utc_liefert_createdate_ohne_offset(pool, baum):
    felder = pool.lesen([(str(baum["video_nur_utc"]), VIDEO)])[metadaten.schluessel(baum["video_nur_utc"])]
    assert felder["CreateDate"] == "2026:01:01 23:30:00"
    assert "CreationDate" not in felder and "CreationDateValue" not in felder


def test_sony_eingebettetes_xml_wird_gelesen(pool, baum):
    """Nur ohne -fast2 - deshalb lesen Videos ohne (SPEC Abschnitt 3)."""
    pfad = str(baum["video_sony_eingebettet"])
    felder = pool.lesen([(pfad, VIDEO)])[metadaten.schluessel(pfad)]
    assert felder["CreationDateValue"] == "2026:01:01 23:30:00+01:00"
    assert felder["DeviceModelName"] == "ILCE-7CM2"
    assert felder["CreateDate"] == "2026:01:01 22:30:00"


def test_fast2_wuerde_das_eingebettete_xml_verlieren(pool, baum, monkeypatch):
    """Der Beleg dafuer, warum Videos ohne -fast2 gelesen werden."""
    pfad = str(baum["video_sony_eingebettet"])
    original = metadaten._argumente

    def mit_fast2(typ):
        args = original(typ)
        return args if "-fast2" in args else [*args, "-fast2"]

    monkeypatch.setattr(metadaten, "_argumente", mit_fast2)
    felder = pool.lesen([(pfad, VIDEO)])[metadaten.schluessel(pfad)]
    assert "CreationDateValue" not in felder


def test_sony_sidecar_xml(pool, baum):
    pfad = str(baum["sidecar_form3"])
    felder = pool.lesen([(pfad, SIDECAR)])[metadaten.schluessel(pfad)]
    assert felder["NonRealTimeMetaCreationDateValue"] == "2026:03:16 00:30:00+01:00"


def test_nicht_lesbare_datei_fehlt_im_ergebnis_statt_abzustuerzen(pool, tmp_path, baum):
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"das ist kein bild")
    fehlt = tmp_path / "gibtsnicht.jpg"
    ergebnis = pool.lesen([(str(kaputt), FOTO), (str(fehlt), FOTO), (str(baum["jpg"]), FOTO)])
    assert metadaten.schluessel(baum["jpg"]) in ergebnis
    assert metadaten.schluessel(fehlt) not in ergebnis
    # eine Datei ohne Metadaten liefert einen Eintrag ohne Datumsfelder oder gar keinen
    assert "DateTimeOriginal" not in ergebnis.get(metadaten.schluessel(kaputt), {})


def test_umlaute_im_pfad(pool, baum):
    pfad = str(baum["name_mit_uhrzeit"])  # liegt unter "Urlaub 2026 Ümläute"
    ergebnis = pool.lesen([(pfad, FOTO)])
    assert metadaten.schluessel(pfad) in ergebnis


def test_mehrere_stapel_nacheinander_im_selben_prozess(pool, baum):
    for _ in range(3):
        ergebnis = pool.lesen([(str(baum["jpg"]), FOTO)])
        assert ergebnis[metadaten.schluessel(baum["jpg"])]["Model"] == "ILCE-7CM2"


def test_stapel_bilden_trennt_nach_typ_und_groesse():
    eintraege = [(f"a{i}.jpg", FOTO) for i in range(5)] + [("v.mp4", VIDEO), ("w.mp4", VIDEO), ("b.arw", RAW)]
    stapel = metadaten.stapel_bilden(eintraege, groesse=2)
    # erst alle Fotos/RAW (stabil in Ordnerreihenfolge), dann die Videos
    assert [len(s) for s in stapel] == [2, 2, 2, 2]
    assert stapel[2] == [("a4.jpg", FOTO), ("b.arw", RAW)]
    assert stapel[3] == [("v.mp4", VIDEO), ("w.mp4", VIDEO)]


def test_schluessel_normiert_windows_pfade():
    assert metadaten.schluessel("C:\\Fotos\\DSC01234.JPG") == "C:/Fotos/DSC01234.JPG"
    assert metadaten.schluessel("/a/b.jpg") == "/a/b.jpg"


@testbaum.NUR_POSIX_NAMEN
def test_zeilenumbruch_im_namen_geht_nie_an_exiftool(pool, tmp_path, baum):
    boese = tmp_path / "harmlos\n-Model=GEAENDERT\n-overwrite_original\nrest.jpg"
    boese.write_bytes(testbaum._JPEG)
    opfer = baum["jpg"]
    vorher = opfer.read_bytes()
    ergebnis = pool.lesen([(str(boese), FOTO), (str(opfer), FOTO)])
    assert opfer.read_bytes() == vorher
    assert metadaten.schluessel(boese) not in ergebnis
    assert ergebnis[metadaten.schluessel(opfer)]["Model"] == "ILCE-7CM2"
    assert not list(tmp_path.glob("*_original")) and not list(opfer.parent.glob("*_original"))


def test_leere_datei_liefert_error_feld(pool, tmp_path):
    leer = tmp_path / "leer.jpg"
    leer.write_bytes(b"")
    ergebnis = pool.lesen([(str(leer), FOTO)])
    assert "Error" in ergebnis.get(metadaten.schluessel(leer), {})


def test_prozesse_bestimmen(konf, monkeypatch):
    """Nach dem ersten echten Testlauf (32 Prozesse auf einer Festplatte):
    0 heisst nach Profil, ein fester Konfigurationswert gilt immer."""
    monkeypatch.setattr(metadaten.os, "cpu_count", lambda: 32)
    assert metadaten.prozesse_bestimmen(konf) == 4                    # Standardprofil hdd
    assert metadaten.prozesse_bestimmen(konf, "hdd") == 4
    assert metadaten.prozesse_bestimmen(konf, "netzwerk") == 4
    assert metadaten.prozesse_bestimmen(konf, "ssd") == 16            # Kerne, hoechstens 16
    monkeypatch.setattr(metadaten.os, "cpu_count", lambda: 6)
    assert metadaten.prozesse_bestimmen(konf, "ssd") == 6
    konf.alle()["leistung"]["profil"] = "ssd"
    assert metadaten.prozesse_bestimmen(konf) == 6                    # Profil aus der Konfiguration
    assert metadaten.prozesse_bestimmen(konf, "HDD ") == 4            # Befehlszeile geht vor
    konf.alle()["leistung"]["metadaten_prozesse"] = 3
    assert metadaten.prozesse_bestimmen(konf) == 3
    assert metadaten.prozesse_bestimmen(konf, "ssd") == 3             # fester Wert gewinnt immer


def test_prozesse_starten_gestaffelt(monkeypatch, baum):
    """Nicht alle ExifTool-Prozesse im selben Augenblick, sondern mit Abstand."""
    monkeypatch.setattr(metadaten, "STARTABSTAND", 0.15)
    starts: list[float] = []
    echt = metadaten._Prozess.__init__

    def mitschreiben(self, programm):
        starts.append(time.monotonic())
        echt(self, programm)

    monkeypatch.setattr(metadaten._Prozess, "__init__", mitschreiben)
    with metadaten.ExifToolPool(testbaum.exiftool_pfad(), 3) as pool:
        zukuenfte = [pool.einreichen([(str(baum["jpg"]), FOTO)]) for _ in range(3)]
        for z in zukuenfte:
            assert z.result()
    assert len(starts) == 3
    abstaende = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:])]
    assert all(a >= 0.14 for a in abstaende), abstaende
    # Ein einzelner Prozess wartet auf niemanden.
    starts.clear()
    beginn = time.monotonic()
    with metadaten.ExifToolPool(testbaum.exiftool_pfad(), 1) as pool:
        pool.lesen([(str(baum["jpg"]), FOTO)])
    assert starts and starts[0] - beginn < 0.1


def test_argumente_fast2_nur_fuer_fotos():
    assert "-fast2" in metadaten._argumente(FOTO)
    assert "-fast2" in metadaten._argumente(RAW)
    assert "-fast2" not in metadaten._argumente(VIDEO)
    assert "-fast2" not in metadaten._argumente(SIDECAR)


def test_pool_ohne_with_block_meldet_das():
    p = metadaten.ExifToolPool(testbaum.exiftool_pfad(), 1)
    with pytest.raises(AssertionError):
        p.einreichen([("x.jpg", FOTO)])


def nachgebautes_exiftool(tmp_path: Path) -> str:
    """Startbarer Ersatz fuer ExifTool (tests/exiftool_haengt.py) als Skript
    bzw. .cmd, damit der Pool ihn wie das echte Programm startet."""
    import sys
    skript = Path(__file__).with_name("exiftool_haengt.py")
    if sys.platform.startswith("win"):
        huelle = tmp_path / "exiftool_haengt.cmd"
        huelle.write_text(f'@"{sys.executable}" "{skript}" %*\r\n', encoding="utf-8")
    else:
        huelle = tmp_path / "exiftool_haengt.sh"
        huelle.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{skript}" "$@"\n', encoding="utf-8")
        huelle.chmod(0o755)
    return str(huelle)


def test_haengender_stapel_kostet_nur_die_eine_datei(tmp_path, monkeypatch):
    """Zeitlimit je Stapel (todo Phase 2): Der Prozess wird beendet und neu
    gestartet, der Stapel Datei fuer Datei nachgelesen; nur die haengende Datei
    bekommt einen Fehler, der Pool arbeitet danach weiter."""
    monkeypatch.setattr(metadaten, "ZEITLIMIT_GRUND", 0.6)
    monkeypatch.setattr(metadaten, "ZEITLIMIT_JE_DATEI", 0.0)
    monkeypatch.setattr(metadaten, "STARTABSTAND", 0.0)
    programm = nachgebautes_exiftool(tmp_path)
    a, haengt, b = (str(tmp_path / n) for n in ("a.jpg", "haengt.jpg", "b.jpg"))
    beginn = time.monotonic()
    with metadaten.ExifToolPool(programm, 1) as pool:
        ergebnis = pool.lesen([(a, FOTO), (haengt, FOTO), (b, FOTO)])
        assert ergebnis[metadaten.schluessel(a)]["Model"] == "Nachbau"
        assert ergebnis[metadaten.schluessel(b)]["Model"] == "Nachbau"
        assert "Zeitlimit" in ergebnis[metadaten.schluessel(haengt)]["Error"]
        assert pool.zeitlimits == 2                     # Stapel und die eine Datei
        # Der Pool ist danach voll brauchbar: neuer Prozess, normale Antwort.
        assert pool.lesen([(a, FOTO)])[metadaten.schluessel(a)]["Model"] == "Nachbau"
        assert len(pool._alle) == 1
    assert time.monotonic() - beginn < 8.0


def test_ohne_zeitlimit_kein_waechter(baum):
    """Das echte ExifTool antwortet innerhalb des Limits; ein normaler Stapel
    laesst keinen Prozess zurueck und zaehlt kein Zeitlimit."""
    with metadaten.ExifToolPool(testbaum.exiftool_pfad(), 1) as pool:
        felder = pool.lesen([(str(baum["jpg"]), FOTO)])[metadaten.schluessel(baum["jpg"])]
        assert felder["Model"] == "ILCE-7CM2" and pool.zeitlimits == 0
