"""Datumsermittlung nach SPEC Abschnitt 3 - jede Quelle, jeder Sonderfall."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from fotosort import datum
from fotosort.dateitypen import FOTO, RAW, VIDEO

JETZT = datetime(2026, 9, 21, 12, 0)


def bestimmen(felder, typ=FOTO, name="x.jpg", sidecar=None, mtime=0.0, konf=None, **_):
    return datum.bestimmen(felder, sidecar, name, typ, mtime, konf, jetzt=JETZT)


# ------------------------------------------------------------ Parsen ----


@pytest.mark.parametrize(
    "text, zeit, offset_min",
    [
        ("2026:01:01 12:30:00", datetime(2026, 1, 1, 12, 30), None),
        ("2026-01-01T12:30:00+01:00", datetime(2026, 1, 1, 12, 30), 60),
        ("2026:01:01 12:30:00-05:00", datetime(2026, 1, 1, 12, 30), -300),
        ("2026:01:01 12:30:00Z", datetime(2026, 1, 1, 12, 30), 0),
        ("2026:01:01 12:30:00.123+02:00", datetime(2026, 1, 1, 12, 30), 120),
        ("2026:01:01", datetime(2026, 1, 1), None),
        ("0000:00:00 00:00:00", None, None),
        ("2026:13:01 00:00:00", None, None),
        ("", None, None),
        (None, None, None),
        ("kein datum", None, None),
    ],
)
def test_zeit_parsen(text, zeit, offset_min):
    z, o = datum.zeit_parsen(text)
    assert z == zeit
    assert o == (None if offset_min is None else timedelta(minutes=offset_min))


@pytest.mark.parametrize(
    "zeit, kaputt",
    [
        (datetime(1989, 12, 31), True),
        (datetime(1990, 1, 1), False),
        (JETZT + timedelta(days=2), True),
        (JETZT + timedelta(hours=20), False),
        (None, True),
    ],
)
def test_ist_kaputt(zeit, kaputt):
    assert datum.ist_kaputt(zeit, JETZT) is kaputt


# ------------------------------------------------------- Quellen 1-6 ----


def test_quelle_1_datetimeoriginal_gewinnt_immer(konf):
    d = bestimmen(
        {"DateTimeOriginal": "2026:01:01 12:30:00", "CreateDate": "2025:05:05 05:05:05"},
        typ=VIDEO, konf=konf,
    )
    assert (d.zeit, d.quelle, d.sicher, d.hinweis) == (datetime(2026, 1, 1, 12, 30), 1, True, "")


def test_quelle_2_quicktime_creationdate_mit_offset(konf):
    d = bestimmen(
        {"CreateDate": "2026:02:10 09:00:00", "CreationDate": "2026:02:10 10:00:00+01:00"},
        typ=VIDEO, konf=konf,
    )
    assert d.zeit == datetime(2026, 2, 10, 10, 0)
    assert d.quelle == 2 and d.hinweis == ""


def test_quelle_2_sony_eingebettet_vor_utc(konf):
    d = bestimmen(
        {"CreateDate": "2026:01:01 22:30:00", "CreationDateValue": "2026:01:01 23:30:00+01:00"},
        typ=VIDEO, konf=konf,
    )
    assert d.zeit == datetime(2026, 1, 1, 23, 30)
    assert d.quelle == 2 and d.hinweis == ""


def test_quelle_2_sony_sidecar_vor_utc(konf):
    d = bestimmen(
        {"CreateDate": "2026:03:15 23:30:00"},
        typ=VIDEO, konf=konf,
        sidecar={"NonRealTimeMetaCreationDateValue": "2026:03:16 00:30:00+01:00"},
    )
    assert d.zeit == datetime(2026, 3, 16, 0, 30)
    assert d.quelle == 2 and d.hinweis == ""


def test_quelle_2_reihenfolge_datei_vor_sidecar(konf):
    d = bestimmen(
        {"CreationDate": "2026:02:10 10:00:00+01:00"},
        typ=VIDEO, konf=konf,
        sidecar={"NonRealTimeMetaCreationDateValue": "2026:03:16 00:30:00+01:00"},
    )
    assert d.zeit == datetime(2026, 2, 10, 10, 0)


def test_pflichtfall_mp4_2330_utc_landet_am_folgetag(konf):
    """PROMPTS.md Phase 2: CreateDate 2026-01-01 23:30 UTC -> Tagesordner 2026-01-02."""
    d = bestimmen({"CreateDate": "2026:01:01 23:30:00"}, typ=VIDEO, name="GOPR0001.MP4", konf=konf)
    assert d.zeit == datetime(2026, 1, 2, 0, 30)
    assert d.quelle == 3
    assert d.sicher is True, "Zeitzone angenommen macht das Datum NICHT unsicher"
    assert d.hinweis == datum.HINWEIS_ZEITZONE
    assert datum.tagesdatum(d.zeit, "00:00", True) == date(2026, 1, 2)


def test_quelle_3_sommerzeit(konf):
    d = bestimmen({"CreateDate": "2026:07:01 22:30:00"}, typ=VIDEO, konf=konf)
    assert d.zeit == datetime(2026, 7, 2, 0, 30)  # UTC+2 im Sommer


def test_quelle_3_mediacreatedate_als_ersatz(konf):
    d = bestimmen({"MediaCreateDate": "2026:01:01 23:30:00"}, typ=VIDEO, konf=konf)
    assert d.zeit == datetime(2026, 1, 2, 0, 30) and d.quelle == 3


def test_quelle_3_createdate_mit_offset_gilt_als_quelle_2(konf):
    d = bestimmen({"CreateDate": "2026:01:01 23:30:00+01:00"}, typ=VIDEO, konf=konf)
    assert d.zeit == datetime(2026, 1, 1, 23, 30) and d.quelle == 2 and d.hinweis == ""


def test_quelle_4_foto_createdate_bleibt_ortszeit(konf):
    """Die UTC-Annahme gilt nur fuer Videos (SPEC Abschnitt 3)."""
    d = bestimmen({"CreateDate": "2026:01:01 23:30:00"}, typ=FOTO, konf=konf)
    assert d.zeit == datetime(2026, 1, 1, 23, 30)
    assert d.quelle == 4 and d.hinweis == "" and d.sicher


def test_quelle_4_raw_datetimedigitized(konf):
    d = bestimmen({"DateTimeDigitized": "2026:01:01 08:00:00"}, typ=RAW, konf=konf)
    assert d.quelle == 4 and d.zeit == datetime(2026, 1, 1, 8, 0)


def test_video_faellt_nicht_auf_quelle_4(konf):
    d = bestimmen({"DateTimeDigitized": "2026:01:01 08:00:00"}, typ=VIDEO, name="a.mp4", konf=konf)
    assert d.quelle != 4


@pytest.mark.parametrize(
    "name, zeit, mit_uhrzeit",
    [
        ("IMG_20260101_013000.jpg", datetime(2026, 1, 1, 1, 30), True),
        ("PXL_20260101_120000123.jpg", datetime(2026, 1, 1, 12, 0), True),
        ("2026-01-01 13.45.10 Urlaub.jpg", datetime(2026, 1, 1, 13, 45, 10), True),
        ("2026-01-01_13-45.jpg", datetime(2026, 1, 1, 13, 45), True),
        ("2026-01-01 Urlaub.jpg", datetime(2026, 1, 1), False),
        ("DSC_20260101.jpg", datetime(2026, 1, 1), False),
        ("DSC01234.jpg", None, False),
        ("19850101_120000.jpg", None, False),  # vor 1990: kaputt
        ("20261301.jpg", None, False),  # Monat 13
        ("123456789012.jpg", None, False),  # zu viele Ziffern am Stueck
    ],
)
def test_aus_dateiname(name, zeit, mit_uhrzeit):
    assert datum.aus_dateiname(name, JETZT) == (zeit, mit_uhrzeit)


def test_quelle_5_dateiname_mit_uhrzeit(konf):
    d = bestimmen({}, name="IMG_20260101_013000.jpg", konf=konf)
    assert (d.zeit, d.quelle, d.sicher, d.hinweis) == (datetime(2026, 1, 1, 1, 30), 5, True, "")


def test_quelle_5_dateiname_ohne_uhrzeit(konf):
    d = bestimmen({}, name="2026-01-01 Urlaub.jpg", konf=konf)
    assert (d.quelle, d.sicher, d.hinweis) == (5, True, datum.HINWEIS_OHNE_UHRZEIT)
    assert d.uhrzeit_bekannt is False


def test_quelle_6_mtime_ist_unsicher(konf):
    stempel = datetime(2026, 6, 1, 10, 0).timestamp()
    d = bestimmen({}, name="DSC01234.jpg", mtime=stempel, konf=konf)
    assert d.quelle == 6 and d.sicher is False
    assert d.zeit == datetime(2026, 6, 1, 10, 0)


def test_gar_nichts(konf):
    d = bestimmen({}, name="DSC01234.jpg", mtime=0, konf=konf)
    assert d.zeit is None and d.quelle == 0 and d.sicher is False


@pytest.mark.parametrize(
    "kaputt", ["0000:00:00 00:00:00", "1970:01:01 00:00:00", "2099:01:01 00:00:00", "2026:02:30 00:00:00"]
)
def test_kaputte_daten_gelten_als_nicht_vorhanden(konf, kaputt):
    d = bestimmen({"DateTimeOriginal": kaputt}, name="IMG_20260101_013000.jpg", konf=konf)
    assert d.quelle == 5  # weiter zur naechsten Quelle


def test_kaputtes_original_aber_gueltiges_createdate(konf):
    d = bestimmen({"DateTimeOriginal": "0000:00:00 00:00:00", "CreateDate": "2026:01:01 08:00:00"}, konf=konf)
    assert d.quelle == 4


# --------------------------------------------------------- Tagesgrenze --


@pytest.mark.parametrize(
    "zeit, grenze, uhrzeit_bekannt, erwartet",
    [
        (datetime(2026, 1, 2, 1, 30), "04:00", True, date(2026, 1, 1)),
        (datetime(2026, 1, 2, 4, 0), "04:00", True, date(2026, 1, 2)),
        (datetime(2026, 1, 2, 3, 59), "04:00", True, date(2026, 1, 1)),
        (datetime(2026, 1, 2, 1, 30), "00:00", True, date(2026, 1, 2)),
        (datetime(2026, 1, 2, 0, 0), "04:00", False, date(2026, 1, 2)),  # ohne Uhrzeit: bleibt
        (datetime(2026, 1, 1, 0, 30), "04:00", True, date(2025, 12, 31)),  # ueber den Jahreswechsel
        (datetime(2026, 1, 2, 1, 30), "kaputt", True, date(2026, 1, 2)),  # ungueltig -> 00:00
    ],
)
def test_tagesdatum(zeit, grenze, uhrzeit_bekannt, erwartet):
    assert datum.tagesdatum(zeit, grenze, uhrzeit_bekannt) == erwartet


def test_tagesgrenze_gilt_auch_fuer_umgerechnete_videos(konf):
    d = bestimmen({"CreateDate": "2026:01:01 23:30:00"}, typ=VIDEO, konf=konf)  # -> 02.01. 00:30
    assert datum.tagesdatum(d.zeit, "04:00", d.uhrzeit_bekannt) == date(2026, 1, 1)


# --------------------------------------------- Befunde der Abnahme -----


def test_z_bedeutet_utc_und_wird_umgerechnet(konf):
    d = bestimmen({"CreationDate": "2026:01:01 23:30:00Z"}, typ=VIDEO, konf=konf)
    assert d.zeit == datetime(2026, 1, 2, 0, 30)
    assert d.quelle == 3 and d.hinweis == datum.HINWEIS_ZEITZONE
    d = bestimmen({"CreateDate": "2026:01:01 23:30:00Z"}, typ=VIDEO, konf=konf)
    assert d.zeit == datetime(2026, 1, 2, 0, 30) and d.quelle == 3


def test_plus_null_offset_ist_ortszeit_nicht_utc(konf):
    d = bestimmen({"CreationDate": "2026:01:01 23:30:00+00:00"}, typ=VIDEO, konf=konf)
    assert d.zeit == datetime(2026, 1, 1, 23, 30) and d.quelle == 2


def test_metadaten_datum_ohne_uhrzeit_ohne_tagesgrenze(konf):
    d = bestimmen({"DateTimeOriginal": "2026:01:01"}, konf=konf)
    assert d.zeit == datetime(2026, 1, 1) and d.quelle == 1
    assert d.uhrzeit_bekannt is False
    assert datum.tagesdatum(d.zeit, "04:00", d.uhrzeit_bekannt) == date(2026, 1, 1)


def test_uhrzeit_bekannt_folgt_dem_dateinamen_hinweis():
    assert datum.Datum(datetime(2026, 1, 1), 5, True, datum.HINWEIS_OHNE_UHRZEIT).uhrzeit_bekannt is False
    assert datum.Datum(datetime(2026, 1, 1, 8), 5, True, "").uhrzeit_bekannt is True


def test_ungueltige_zeitzone_wirft(konf):
    konf.alle()["datum"]["heimat_zeitzone"] = "Europa/Berlin"
    with pytest.raises(datum.ZeitzoneUngueltig):
        bestimmen({"CreateDate": "2026:01:01 23:30:00"}, typ=VIDEO, konf=konf)


@pytest.mark.parametrize("name, erwartet", [
    ("signal-2026-01-01-23-45-10-123.jpg", datetime(2026, 1, 1, 23, 45, 10)),
    ("Screenshot 2026-01-01 at 00.30.12.png", datetime(2026, 1, 1, 0, 30, 12)),
    ("Bildschirmfoto 2026-01-01 um 00.30.12.png", datetime(2026, 1, 1, 0, 30, 12)),
    ("IMG_20260101_013000.jpg", datetime(2026, 1, 1, 1, 30, 0)),
])
def test_dateiname_mit_uhrzeit_aus_signal_und_macos(name, erwartet):
    """Signal ("signal-2026-01-01-23-45-10") und macOS-Bildschirmfotos ("... at
    00.30.12", deutsch "... um 00.30.12") verloren frueher die Uhrzeit - dann
    griff die Tagesgrenze nicht (Screenshot 00:30 gehoert zum Vortag)."""
    zeit, mit_uhrzeit = datum.aus_dateiname(name)
    assert zeit == erwartet and mit_uhrzeit


def test_kein_falsches_uhrzeit_muster_aus_bildgroessen():
    zeit, mit_uhrzeit = datum.aus_dateiname("2026-01-01-1200x800.jpg")
    assert zeit == datetime(2026, 1, 1) and not mit_uhrzeit


# ------------------------------------------- Runde 2 (v0.8), Entscheidungen -----


@pytest.mark.parametrize("typ", [FOTO, RAW, VIDEO])
def test_z_in_datetimeoriginal_ist_weltzeit(konf, typ):
    """Entscheidung 6: "Z" heisst immer UTC, nie Ortszeit - umrechnen und kennzeichnen."""
    d = bestimmen({"DateTimeOriginal": "2026:07:01 22:30:00Z"}, typ=typ, konf=konf)
    assert d.zeit == datetime(2026, 7, 2, 0, 30)          # Berlin, Sommerzeit
    assert d.quelle == 1 and d.sicher and d.hinweis == datum.HINWEIS_ZEITZONE


def test_datetimeoriginal_mit_offset_bleibt_ortszeit(konf):
    d = bestimmen({"DateTimeOriginal": "2026:07:01 22:30:00+02:00"}, konf=konf)
    assert d.zeit == datetime(2026, 7, 1, 22, 30) and d.hinweis == ""


@pytest.mark.parametrize("feld", ["DateCreated", "CreationTime"])
def test_quelle_4_xmp_datecreated_und_png_creationtime(konf, feld):
    """Entscheidung 5: Scan-TIFF mit Lightroom-Datum, PNG mit Erstellzeit."""
    d = bestimmen({feld: "2019:05:04 10:11:12"}, konf=konf)
    assert d.zeit == datetime(2019, 5, 4, 10, 11, 12) and d.quelle == 4 and d.sicher and d.hinweis == ""


def test_quelle_4_createdate_vor_datecreated(konf):
    d = bestimmen({"CreateDate": "2019:05:04 10:00:00", "DateCreated": "2001:01:01 00:00:00"}, konf=konf)
    assert d.zeit == datetime(2019, 5, 4, 10)


def test_datecreated_mit_z_wird_umgerechnet(konf):
    d = bestimmen({"DateCreated": "2019:01:04 10:00:00Z"}, konf=konf)
    assert d.zeit == datetime(2019, 1, 4, 11) and d.hinweis == datum.HINWEIS_ZEITZONE


@pytest.mark.parametrize("typ", [FOTO, RAW, VIDEO])
def test_xmp_sidecar_nur_wenn_die_datei_nichts_liefert(konf, typ):
    xmp = {"DateTimeOriginal": "2018:08:08 08:08:08"}
    d = datum.bestimmen({}, None, "scan.tif", typ, 0.0, konf, jetzt=JETZT, xmp_felder=xmp)
    assert d.zeit == datetime(2018, 8, 8, 8, 8, 8) and d.quelle == 4 and d.sicher
    # Liefert die Datei selbst etwas, bleibt es dabei.
    d = datum.bestimmen({"DateTimeOriginal": "2020:02:02 02:02:02"}, None, "scan.tif", typ, 0.0, konf,
                        jetzt=JETZT, xmp_felder=xmp)
    assert d.zeit == datetime(2020, 2, 2, 2, 2, 2) and d.quelle == 1
    # Das xmp kommt vor dem Dateinamen.
    d = datum.bestimmen({}, None, "IMG_20200101_120000.tif", typ, 0.0, konf, jetzt=JETZT, xmp_felder=xmp)
    assert d.quelle == 4


def test_xmp_sidecar_felder_der_reihe_nach(konf):
    d = datum.bestimmen({}, None, "a.tif", FOTO, 0.0, konf, jetzt=JETZT,
                        xmp_felder={"CreateDate": "2017:01:01 10:00:00", "DateCreated": "2016:01:01 10:00:00"})
    assert d.zeit == datetime(2016, 1, 1, 10)


def _auffaellig(d_zeit, name="x.jpg", mtime=None, quelle=1):
    d = datum.Datum(d_zeit, quelle, True)
    return datum.auffaellig(d, name, mtime.timestamp() if mtime else 0.0, jetzt=JETZT)


def test_datum_auffaellig_gegen_dateiname():
    """Entscheidung 9: Hinweis im Bericht, einsortiert wird trotzdem."""
    assert _auffaellig(datetime(2000, 1, 1, 0, 1), name="IMG_20230405_101010.jpg")
    assert not _auffaellig(datetime(2023, 4, 5, 10, 10), name="IMG_20230405_101010.jpg")
    assert not _auffaellig(datetime(2023, 4, 6, 1, 0), name="2023-04-05 Urlaub.jpg")   # ein Tag Spielraum


def test_datum_auffaellig_gegen_aenderungsdatum():
    # Aufnahme NACH der letzten Aenderung: die Uhr ging falsch.
    assert _auffaellig(datetime(2025, 6, 1), mtime=datetime(2024, 6, 1))
    # Mehr als zehn Jahre vor der Aenderung: typisch zurueckgesetzte Kamerauhr.
    assert _auffaellig(datetime(2000, 1, 1), mtime=datetime(2023, 6, 1))
    # Normal: kurz vor der Aenderung, oder ein altes Foto, spaeter bearbeitet (< 10 Jahre).
    assert not _auffaellig(datetime(2023, 5, 31, 18), mtime=datetime(2023, 6, 1))
    assert not _auffaellig(datetime(2018, 1, 1), mtime=datetime(2023, 6, 1))
    # Kaputtes Aenderungsdatum (FAT-Anfang 1980) zaehlt nicht.
    assert not _auffaellig(datetime(2023, 1, 1), mtime=datetime(1980, 1, 1))


def test_datum_auffaellig_nur_fuer_metadaten():
    assert not _auffaellig(datetime(2000, 1, 1), name="IMG_20230405.jpg", quelle=5)
    assert not _auffaellig(datetime(2000, 1, 1), mtime=datetime(2023, 6, 1), quelle=6)
