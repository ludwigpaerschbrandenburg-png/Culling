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


# --------------------------------------- Aufteilen nach Aufnahmezeit (v0.8) -----

from datetime import datetime  # noqa: E402

from fotosort.dateitypen import FOTO, RAW, VIDEO  # noqa: E402


def _m(name, typ, zeit=None, kaputt=False):
    return gruppen.Mitglied(name, typ, zeit, kaputt)


def _namen(teile):
    return [[m.name for m in t] for t in teile]


def test_raw_und_jpg_derselben_aufnahme_bleiben_zusammen():
    teile, kaputt = gruppen.aufteilen([
        _m("DSC1.JPG", FOTO, datetime(2016, 5, 5, 10, 0, 1)),
        _m("DSC1.ARW", RAW, datetime(2016, 5, 5, 10, 0, 0)),
    ], 5)
    assert _namen(teile) == [["DSC1.ARW", "DSC1.JPG"]] and kaputt == []


def test_neu_begonnener_zaehler_wird_getrennt():
    """Entscheidung 2: IMG_0001.JPG von 2016 und IMG_0001.MOV von 2021."""
    teile, _ = gruppen.aufteilen([
        _m("IMG_0001.MOV", VIDEO, datetime(2021, 6, 6, 10)),
        _m("IMG_0001.JPG", FOTO, datetime(2016, 5, 5, 10)),
    ], 5)
    assert _namen(teile) == [["IMG_0001.JPG"], ["IMG_0001.MOV"]]


def test_ohne_datum_bleibt_bei_der_ersten_teilgruppe():
    teile, _ = gruppen.aufteilen([
        _m("A.ARW", RAW, None),
        _m("A.JPG", FOTO, datetime(2016, 1, 1)),
        _m("A.MOV", VIDEO, datetime(2021, 1, 1)),
    ], 5)
    assert _namen(teile) == [["A.ARW", "A.JPG"], ["A.MOV"]]


def test_grenze_der_toleranz_und_live_photo():
    t = datetime(2024, 7, 1, 12, 0, 0)
    from datetime import timedelta
    teile, _ = gruppen.aufteilen([_m("L.HEIC", FOTO, t), _m("L.MOV", VIDEO, t - timedelta(seconds=5))], 5)
    assert len(teile) == 1
    teile, _ = gruppen.aufteilen([_m("L.HEIC", FOTO, t), _m("L.MOV", VIDEO, t - timedelta(seconds=6))], 5)
    assert len(teile) == 2


def test_kaputte_mitglieder_fallen_heraus():
    """Entscheidung 3: Eine 0-Byte-ARW zieht das gesunde JPG nicht mehr mit."""
    teile, kaputt = gruppen.aufteilen([
        _m("D.ARW", RAW, None, kaputt=True),
        _m("D.JPG", FOTO, datetime(2016, 1, 1)),
    ], 5)
    assert _namen(teile) == [["D.JPG"]] and [m.name for m in kaputt] == ["D.ARW"]
    teile, kaputt = gruppen.aufteilen([_m("E.ARW", RAW, None, kaputt=True)], 5)
    assert teile == [] and len(kaputt) == 1
