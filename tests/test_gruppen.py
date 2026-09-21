"""Zusammengehoerige Dateien (SPEC Abschnitt 3)."""

from __future__ import annotations

from fotosort import gruppen


def _bild(gruppen_liste):
    return {g.haupt: (sorted(g.mitglieder), sorted(g.sidecars)) for g in gruppen_liste}


def test_raw_plus_jpg_bilden_eine_gruppe_mit_raw_als_hauptdatei(konf):
    g, ohne = gruppen.bilden(["DSC01234.JPG", "DSC01234.ARW"], konf)
    assert _bild(g) == {"DSC01234.ARW": (["DSC01234.JPG"], [])}
    assert ohne == []


def test_alle_drei_sidecar_formen(konf):
    namen = ["DSC01234.ARW", "DSC01234.JPG", "DSC01234.xmp", "DSC01234.ARW.xmp", "C0001.MP4", "C0001M01.XML"]
    g, ohne = gruppen.bilden(namen, konf)
    assert _bild(g) == {
        "C0001.MP4": ([], ["C0001M01.XML"]),
        "DSC01234.ARW": (["DSC01234.JPG"], ["DSC01234.ARW.xmp", "DSC01234.xmp"]),
    }
    assert ohne == []


def test_sidecar_ohne_hauptdatei(konf):
    g, ohne = gruppen.bilden(["fremd.xmp", "DSC01234.JPG"], konf)
    assert ohne == ["fremd.xmp"]
    assert _bild(g) == {"DSC01234.JPG": ([], [])}


def test_prioritaet_raw_vor_foto_vor_video(konf):
    g, _ = gruppen.bilden(["a.mp4", "a.jpg", "a.arw"], konf)
    assert g[0].haupt == "a.arw" and sorted(g[0].mitglieder) == ["a.jpg", "a.mp4"]
    g, _ = gruppen.bilden(["b.mov", "b.heic"], konf)
    assert g[0].haupt == "b.heic" and g[0].mitglieder == ["b.mov"]


def test_stammname_ohne_ruecksicht_auf_gross_kleinschreibung(konf):
    g, _ = gruppen.bilden(["dsc01234.arw", "DSC01234.JPG"], konf)
    assert len(g) == 1 and g[0].haupt == "dsc01234.arw"


def test_verschiedene_stammnamen_bleiben_getrennt(konf):
    g, _ = gruppen.bilden(["DSC01234.JPG", "DSC01235.JPG", "DSC01234_1.JPG"], konf)
    assert sorted(x.haupt for x in g) == ["DSC01234.JPG", "DSC01234_1.JPG", "DSC01235.JPG"]


def test_sonstiges_wird_ignoriert(konf):
    g, ohne = gruppen.bilden(["notizen.txt", "Thumbs.db", "DSC01234.JPG"], konf)
    assert _bild(g) == {"DSC01234.JPG": ([], [])} and ohne == []


def test_sidecar_zur_besten_hauptdatei(konf):
    """DSC01234.xmp passt zu ARW und JPG - es gehoert zur Gruppe der RAW."""
    g, _ = gruppen.bilden(["DSC01234.JPG", "DSC01234.ARW", "DSC01234.xmp"], konf)
    assert g[0].haupt == "DSC01234.ARW" and g[0].sidecars == ["DSC01234.xmp"]


def test_form2_sidecar_der_jpg_gehoert_zur_raw_gruppe(konf):
    g, _ = gruppen.bilden(["DSC01234.JPG", "DSC01234.ARW", "DSC01234.JPG.xmp"], konf)
    assert len(g) == 1 and g[0].sidecars == ["DSC01234.JPG.xmp"]


def test_leere_liste(konf):
    assert gruppen.bilden([], konf) == ([], [])


def test_alle_liefert_hauptdatei_zuerst(konf):
    g, _ = gruppen.bilden(["a.xmp", "a.jpg", "a.arw"], konf)
    assert g[0].alle == ["a.arw", "a.jpg", "a.xmp"]
