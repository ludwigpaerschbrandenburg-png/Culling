"""Kamera-Ordner aus dem Modellnamen (SPEC Abschnitt 3)."""

from __future__ import annotations

import pytest

from fotosort import config, kamera


@pytest.mark.parametrize(
    "felder, ordner, roh",
    [
        ({"Make": "SONY", "Model": "ILCE-7CM2"}, "A7C2", "ILCE-7CM2"),
        ({"Model": "ILCE-7C"}, "A7C", "ILCE-7C"),
        ({"Model": "ilce-7c"}, "A7C", "ilce-7c"),  # Gross-/Kleinschreibung egal
        ({"Model": "Noritsu Koki QSS-32_33"}, "Analog", "Noritsu Koki QSS-32_33"),
        ({"Model": "EPSON Perfection V600"}, "Analog", "EPSON Perfection V600"),
        ({"Make": "Canon", "Model": "Canon EOS R5"}, "Canon EOS R5", "Canon EOS R5"),
        ({"Make": "NIKON CORPORATION", "Model": "NIKON Z 6"}, "NIKON Z 6", "NIKON Z 6"),
        ({"Model": 'Was/ist:das*?"'}, "Was_ist_das", 'Was/ist:das*?"'),
        ({"Model": "  Leer   zeichen  "}, "Leer zeichen", "Leer   zeichen"),
        ({"Model": "Punkt am Ende."}, "Punkt am Ende", "Punkt am Ende."),
        ({}, "Unbekannte_Kamera", ""),
        ({"Model": ""}, "Unbekannte_Kamera", ""),
        ({"Make": "SONY"}, "Unbekannte_Kamera", ""),  # nur Hersteller ist kein Modell (SPEC §3)
        ({"DeviceModelName": "ILCE-7CM2"}, "A7C2", "ILCE-7CM2"),  # Sony-Video-XML
        ({"Model": "///"}, "Unbekannte_Kamera", "///"),  # nach Bereinigung leer
    ],
)
def test_ordnername(konf, felder, ordner, roh):
    assert kamera.ordnername(felder, konf) == (ordner, roh)


def test_alias_ueber_make_plus_model():
    k = config.Konfiguration()
    k.alle()["kamera"]["aliase"]["Canon Canon EOS R5"] = "R5"
    assert kamera.ordnername({"Make": "Canon", "Model": "Canon EOS R5"}, k)[0] == "Canon EOS R5"
    k.alle()["kamera"]["aliase"]["Panasonic DC-GH6"] = "GH6"
    assert kamera.ordnername({"Make": "Panasonic", "Model": "DC-GH6"}, k)[0] == "GH6"


def test_unbekannt_ist_konfigurierbar():
    k = config.Konfiguration()
    k.alle()["kamera"]["unbekannt"] = "Ohne_Kamera"
    assert kamera.ordnername({}, k) == ("Ohne_Kamera", "")


def test_alias_wird_selbst_bereinigt():
    k = config.Konfiguration()
    k.alle()["kamera"]["aliase"]["X"] = "A/B"
    assert kamera.ordnername({"Model": "X"}, k)[0] == "A_B"
