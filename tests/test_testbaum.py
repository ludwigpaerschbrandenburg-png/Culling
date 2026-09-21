"""Tests fuer den Erzeuger des kuenstlichen Testbaums (SPEC Abschnitt 11)."""

from __future__ import annotations

import json
import subprocess

import pytest

import testbaum


def _exif(pfad, *felder) -> dict:
    programm = testbaum.exiftool_pfad()
    fertig = subprocess.run(
        [programm, "-j", "-api", "QuickTimeUTC=1", *felder, str(pfad)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(fertig.stdout)[0]


def test_ohne_exiftool_bricht_der_erzeuger_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(testbaum.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as fehler:
        testbaum.erzeugen(tmp_path / "baum")
    assert "ExifTool" in str(fehler.value)


def test_erwartete_anzahl_dateien(baum):
    gefunden = [p for p in baum["quelle"].rglob("*") if p.is_file()]
    assert len(gefunden) == testbaum.ERWARTET_GESAMT


def test_raw_jpg_paar_mit_datum_und_modell(baum):
    for schluessel in ("raw", "jpg"):
        werte = _exif(baum[schluessel], "-DateTimeOriginal", "-Model")
        assert werte["DateTimeOriginal"] == "2026:01:01 12:30:00"
        assert werte["Model"] == "ILCE-7CM2"


def test_beide_einfachen_sidecar_formen_liegen_da(baum):
    assert baum["sidecar_form1"].name == "DSC01234.xmp"
    assert baum["sidecar_form2"].name == "DSC01234.ARW.xmp"
    assert baum["sidecar_form1"].is_file()
    assert baum["sidecar_form2"].is_file()


def test_sony_paar_video_und_xml(baum):
    assert baum["video_ohne_offset"].name == "C0001.MP4"
    assert baum["sidecar_form3"].name == "C0001M01.XML"
    assert baum["sidecar_form3"].parent == baum["video_ohne_offset"].parent


def test_video_ohne_offset_wechselt_bei_der_umrechnung_den_tag(baum):
    # 2026:03:15 23:30:00 UTC wird in Europe/Berlin zum 16.03.
    werte = _exif(baum["video_ohne_offset"], "-QuickTime:CreateDate")
    assert werte["CreateDate"].startswith("2026:03:15 23:30:00")


def test_video_mit_offset_hat_creationdate(baum):
    werte = _exif(baum["video_mit_offset"], "-QuickTime:CreationDate")
    assert werte["CreationDate"].startswith("2026:02:10 10:00:00")
    assert "+01:00" in werte["CreationDate"]


def test_ordner_verknuepfung_zeigt_nach_draussen(baum):
    link = baum["ordner_verknuepfung"]
    assert link.is_symlink()
    assert link.resolve() == baum["ausserhalb"].resolve()
    assert baum["nur_ueber_verknuepfung"].is_file()


def test_ausschlussmuster_trifft_den_papierkorb(baum):
    from fotosort import scan

    relativ = baum["im_papierkorb"].relative_to(baum["quelle"]).as_posix()
    assert scan.ist_ausgeschlossen(relativ, [testbaum.AUSSCHLUSSMUSTER_BEISPIEL])


def test_umlaute_leerzeichen_tiefer_pfad(baum):
    assert "Ümläute" in str(baum["name_ohne_uhrzeit"])
    assert " " in baum["name_ohne_uhrzeit"].name
    assert len(baum["tiefer_pfad"].relative_to(baum["quelle"]).parts) >= 11
    assert len(baum["tiefer_pfad"].name) > 150


def test_duplikate_sind_inhaltsgleich(baum):
    assert baum["duplikat_a"].read_bytes() == baum["duplikat_b"].read_bytes()


def test_namenskonflikt_gleicher_name_anderer_inhalt(baum):
    assert baum["namenskonflikt"].name == baum["jpg"].name
    assert baum["namenskonflikt"].read_bytes() != baum["jpg"].read_bytes()


def test_versteckter_ordner_und_reste_dateien(baum):
    assert baum["versteckt"].parent.name == ".versteckt"
    assert baum["reste_thumbs"].name == "Thumbs.db"
    assert baum["reste_ds_store"].name == ".DS_Store"


def test_erwartete_aufteilung_nach_typ(baum, konf):
    from fotosort import dateitypen

    gezaehlt: dict[str, int] = {}
    for pfad in baum["quelle"].rglob("*"):
        if pfad.is_file() and not pfad.is_symlink():
            typ = dateitypen.typ_von(pfad.name, konf)
            gezaehlt[typ] = gezaehlt.get(typ, 0) + 1
    assert gezaehlt == testbaum.ERWARTET_JE_TYP
