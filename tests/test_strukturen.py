"""Datum aus Ordnernamen in jeder Schreibweise (Runde 3a, Entscheidung vom
26.10.2026: „bereits erstandene Strukturen kennen“).

Reine Logik, ohne Dateien: Ein Ordner "2021.01" ist der Januar 2021, auch
wenn die Vorlage des Programms "2021-01 Januar" schreiben wuerde.
"""

from __future__ import annotations

from datetime import date

import pytest

from fotosort import strukturen
from fotosort.strukturen import Zeitraum

JAN_2021 = Zeitraum("monat", 2021, 1)
TAG = Zeitraum("tag", 2021, 1, 15)


@pytest.mark.parametrize("name, erwartet", [
    ("2021", Zeitraum("jahr", 2021)),
    ("2021 Urlaube", Zeitraum("jahr", 2021)),
    ("2021.01", JAN_2021),
    ("2021-01", JAN_2021),
    ("2021_01", JAN_2021),
    ("2021 01", JAN_2021),
    ("2021-01 Januar", JAN_2021),
    ("01.2021", JAN_2021),
    ("1.2021", JAN_2021),
    ("01-2021", JAN_2021),
    ("Januar 2021", JAN_2021),
    ("januar 2021", JAN_2021),
    ("Jan 2021", JAN_2021),
    ("2021 Januar", JAN_2021),
    ("Maerz 2021", Zeitraum("monat", 2021, 3)),
    ("März 2021", Zeitraum("monat", 2021, 3)),
    ("2021-01-15", TAG),
    ("2021.01.15", TAG),
    ("2021_01_15 Hochzeit", TAG),
    ("20210115", TAG),
    ("20210115 Hochzeit Anna", TAG),
    ("15.01.2021", TAG),
    ("15.1.2021 Geburtstag", TAG),
    ("2021-01-15 bis 18 Italien", TAG),
])
def test_schreibweisen(name, erwartet):
    assert strukturen.zeitraum(name) == erwartet


@pytest.mark.parametrize("name", [
    "Urlaub", "D750", "100CANON", "DCIM", "1234 Kunden", "2021-13", "2021-02-30", "32.01.2021",
    "Hochzeit 2021", "IMG_2021", "_Ohne_Datum", "A7C2", "2021abc", "0000",
])
def test_kein_datum(name):
    assert strukturen.zeitraum(name) is None


def test_mit_zusammenhang_des_elternordners():
    """Unter "2021" ist "01" der Januar; unter "2021.01" ist "15" der 15. Januar."""
    jahr = Zeitraum("jahr", 2021)
    for name in ("01", "1", "01 Januar", "Januar", "Jan", "01_Januar"):
        assert strukturen.zeitraum(name, jahr) == JAN_2021, name
    assert strukturen.zeitraum("15", JAN_2021) == TAG
    assert strukturen.zeitraum("15 Hochzeit", JAN_2021) == TAG
    assert strukturen.zeitraum("15", jahr) is None            # kein Monat 15
    assert strukturen.zeitraum("01") is None                   # ohne Zusammenhang nichts
    assert strukturen.zeitraum("2021.01", jahr) == JAN_2021    # voll ausgeschrieben gilt auch so
    assert strukturen.zeitraum("2022.01", jahr) is None        # widerspricht dem Elternordner


def test_umfasst():
    assert Zeitraum("jahr", 2021).umfasst(date(2021, 1, 15))
    assert JAN_2021.umfasst(date(2021, 1, 15)) and not JAN_2021.umfasst(date(2021, 2, 1))
    assert TAG.umfasst(date(2021, 1, 15)) and not TAG.umfasst(date(2021, 1, 16))
    assert TAG.feiner_als(JAN_2021) and JAN_2021.feiner_als(Zeitraum("jahr", 2021))
    assert not JAN_2021.feiner_als(TAG)


def test_zeitraum_eines_pfads():
    """Das Datum, das der Ordnerpfad einer Datei nennt - von oben nach unten,
    mit Zusammenhang; der feinste passende Ordner gilt."""
    assert strukturen.zeitraum_im_pfad(["Fotos", "2021", "01", "Hochzeit"]) == JAN_2021
    assert strukturen.zeitraum_im_pfad(["Archiv", "2021.01.15 Hochzeit"]) == TAG
    assert strukturen.zeitraum_im_pfad(["Fotos", "Urlaub"]) is None
