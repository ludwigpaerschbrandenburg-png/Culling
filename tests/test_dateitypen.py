"""Tests fuer dateitypen.py (SPEC Abschnitt 3)."""

from __future__ import annotations

import pytest

from fotosort import dateitypen


def test_typen_konstanten():
    assert dateitypen.ECHTE_TYPEN == frozenset({"foto", "raw", "video", "sidecar"})
    assert dateitypen.SONSTIGES == "sonstiges"
    assert dateitypen.ist_echter_typ("sonstiges") is False
    for typ in dateitypen.ECHTE_TYPEN:
        assert dateitypen.ist_echter_typ(typ) is True


@pytest.mark.parametrize(
    "name,erwartet",
    [
        ("DSC01234.JPG", "foto"),
        ("DSC01234.jpg", "foto"),
        ("DSC01234.Jpg", "foto"),
        ("bild.heic", "foto"),
        ("DSC01234.ARW", "raw"),
        ("bild.cr3", "raw"),
        ("C0001.MP4", "video"),
        ("film.mkv", "video"),
        ("DSC01234.xmp", "sidecar"),
        ("C0001M01.XML", "sidecar"),
        ("notizen.txt", "sonstiges"),
        ("Thumbs.db", "sonstiges"),
        (".DS_Store", "sonstiges"),
        ("ohne_endung", "sonstiges"),
    ],
)
def test_typ_von(name, erwartet, konf):
    assert dateitypen.typ_von(name, konf) == erwartet


def test_sidecar_form1_stammname(konf):
    assert dateitypen.sidecar_gehoert_zu("DSC01234.xmp", "DSC01234.ARW", konf)


def test_sidecar_form2_vollstaendiger_name(konf):
    assert dateitypen.sidecar_gehoert_zu("DSC01234.ARW.xmp", "DSC01234.ARW", konf)


def test_sidecar_form3_sony(konf):
    # C0001M01.XML gehoert zu C0001.MP4 (SPEC Abschnitt 3, dritte Form).
    assert dateitypen.sidecar_gehoert_zu("C0001M01.XML", "C0001.MP4", konf)
    assert dateitypen.sidecar_gehoert_zu("C0001M99.XML", "C0001.MP4", konf)


def test_sidecar_form3_nur_mit_passendem_zusatz(konf):
    assert not dateitypen.sidecar_gehoert_zu("C0001XY.XML", "C0001.MP4", konf)
    assert not dateitypen.sidecar_gehoert_zu("C0001M1.XML", "C0001.MP4", konf)


def test_sidecar_gehoert_nicht_zu_fremder_datei(konf):
    assert not dateitypen.sidecar_gehoert_zu("DSC09999.xmp", "DSC01234.ARW", konf)


def test_sidecar_gehoert_nie_zu_einem_sidecar(konf):
    assert not dateitypen.sidecar_gehoert_zu("DSC01234.xmp", "DSC01234.dop", konf)


def test_nur_sidecars_koennen_sidecars_sein(konf):
    assert not dateitypen.sidecar_gehoert_zu("DSC01234.JPG", "DSC01234.ARW", konf)


def test_endungsvergleich_ohne_gross_kleinschreibung(konf):
    assert dateitypen.sidecar_gehoert_zu("dsc01234.XMP", "DSC01234.arw", konf)
