"""ExifTool-Pool: dauerhaft laufende Prozesse, Stapel, JSON (SPEC Abschnitt 7)."""

from __future__ import annotations

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
    for schluessel in (str(baum["jpg"]), str(baum["raw"])):
        felder = ergebnis[schluessel]
        assert felder["DateTimeOriginal"] == "2026:01:01 12:30:00"
        assert felder["Model"] == "ILCE-7CM2"
        assert felder["Make"] == "SONY"


def test_video_mit_offset_liefert_creationdate(pool, baum):
    felder = pool.lesen([(str(baum["video_mit_offset"]), VIDEO)])[str(baum["video_mit_offset"])]
    assert felder["CreationDate"] == "2026:02:10 10:00:00+01:00"
    assert felder["CreateDate"] == "2026:02:10 09:00:00"


def test_video_nur_utc_liefert_createdate_ohne_offset(pool, baum):
    felder = pool.lesen([(str(baum["video_nur_utc"]), VIDEO)])[str(baum["video_nur_utc"])]
    assert felder["CreateDate"] == "2026:01:01 23:30:00"
    assert "CreationDate" not in felder and "CreationDateValue" not in felder


def test_sony_eingebettetes_xml_wird_gelesen(pool, baum):
    """Nur ohne -fast2 - deshalb lesen Videos ohne (SPEC Abschnitt 3)."""
    pfad = str(baum["video_sony_eingebettet"])
    felder = pool.lesen([(pfad, VIDEO)])[pfad]
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
    felder = pool.lesen([(pfad, VIDEO)])[pfad]
    assert "CreationDateValue" not in felder


def test_sony_sidecar_xml(pool, baum):
    pfad = str(baum["sidecar_form3"])
    felder = pool.lesen([(pfad, SIDECAR)])[pfad]
    assert felder["NonRealTimeMetaCreationDateValue"] == "2026:03:16 00:30:00+01:00"


def test_nicht_lesbare_datei_fehlt_im_ergebnis_statt_abzustuerzen(pool, tmp_path, baum):
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"das ist kein bild")
    fehlt = tmp_path / "gibtsnicht.jpg"
    ergebnis = pool.lesen([(str(kaputt), FOTO), (str(fehlt), FOTO), (str(baum["jpg"]), FOTO)])
    assert str(baum["jpg"]) in ergebnis
    assert str(fehlt) not in ergebnis
    # eine Datei ohne Metadaten liefert einen Eintrag ohne Datumsfelder oder gar keinen
    assert "DateTimeOriginal" not in ergebnis.get(str(kaputt), {})


def test_umlaute_im_pfad(pool, baum):
    pfad = str(baum["name_mit_uhrzeit"])  # liegt unter "Urlaub 2026 Ümläute"
    ergebnis = pool.lesen([(pfad, FOTO)])
    assert pfad in ergebnis


def test_mehrere_stapel_nacheinander_im_selben_prozess(pool, baum):
    for _ in range(3):
        ergebnis = pool.lesen([(str(baum["jpg"]), FOTO)])
        assert ergebnis[str(baum["jpg"])]["Model"] == "ILCE-7CM2"


def test_stapel_bilden_trennt_nach_typ_und_groesse():
    eintraege = [(f"a{i}.jpg", FOTO) for i in range(5)] + [("v.mp4", VIDEO), ("w.mp4", VIDEO), ("b.arw", RAW)]
    stapel = metadaten.stapel_bilden(eintraege, groesse=2)
    assert [len(s) for s in stapel] == [2, 2, 1, 2, 1]
    assert stapel[3] == [("v.mp4", VIDEO), ("w.mp4", VIDEO)]
    assert stapel[4] == [("b.arw", RAW)]


def test_prozesse_bestimmen(konf, monkeypatch):
    assert metadaten.prozesse_bestimmen(konf) >= 1
    konf.alle()["leistung"]["metadaten_prozesse"] = 3
    assert metadaten.prozesse_bestimmen(konf) == 3


def test_argumente_fast2_nur_fuer_fotos():
    assert "-fast2" in metadaten._argumente(FOTO)
    assert "-fast2" in metadaten._argumente(RAW)
    assert "-fast2" not in metadaten._argumente(VIDEO)
    assert "-fast2" not in metadaten._argumente(SIDECAR)


def test_pool_ohne_with_block_meldet_das():
    p = metadaten.ExifToolPool(testbaum.exiftool_pfad(), 1)
    with pytest.raises(AssertionError):
        p.einreichen([("x.jpg", FOTO)])
