"""Tests fuer config.py (SPEC Abschnitt 6 und 9)."""

from __future__ import annotations

import tomllib

import pytest

from fotosort import FotosortFehler, config


def test_standard_hat_genau_die_gruppen_aus_der_spec():
    assert set(config.STANDARD) == {
        "ordner",
        "datum",
        "kamera",
        "dateitypen",
        "quelle",
        "sicherheit",
        "datenbank",
        "aufraeumen",
        "leistung",
    }


def test_standardwerte_wortwoertlich():
    k = config.Konfiguration()
    assert k.wert("ordner.vorlage") == (
        "{jahr}/{jahr}-{monat} {monatsname}/{jahr}-{monat}-{tag}/{kamera}"
    )
    assert k.wert("ordner.vorlage_ohne_datum") == "_Ohne_Datum/{kamera}"
    assert k.wert("datum.heimat_zeitzone") == "Europe/Berlin"
    assert k.wert("datum.tagesgrenze") == "00:00"
    assert k.wert("datum.unsicheres_datum") == "ohne_datum"
    assert k.wert("kamera.unbekannt") == "Unbekannte_Kamera"
    assert k.wert("dateitypen.foto") == [
        "jpg", "jpeg", "heic", "hif", "png", "tif", "tiff", "webp"
    ]
    assert k.wert("dateitypen.raw") == [
        "arw", "cr2", "cr3", "nef", "dng", "raf", "orf", "rw2", "srw"
    ]
    assert k.wert("dateitypen.video") == ["mp4", "mov", "mts", "m2ts", "avi", "mkv"]
    assert k.wert("dateitypen.sidecar") == ["xmp", "dop", "pp3", "thm", "aae", "xml"]
    assert k.wert("dateitypen.sidecar_zusatzmuster") == ["M[0-9][0-9]"]
    assert k.wert("quelle.ausschlussmuster") == []
    assert k.wert("quelle.verknuepfungen_folgen") is False
    assert k.wert("sicherheit.byte_vergleich_vor_loeschen") is False
    assert k.wert("datenbank.datenbank_ort") == ""
    assert k.wert("aufraeumen.reste_dateien") == ["Thumbs.db", ".DS_Store", "desktop.ini"]
    assert k.wert("leistung.profil") == "hdd"
    assert k.wert("leistung.metadaten_prozesse") == 0
    assert k.wert("leistung.kopier_worker") == 0
    assert k.wert("leistung.hash_worker") == 0
    assert k.wert("leistung.exiftool_pfad") == ""


def test_aliase_genau_die_zeilen_aus_der_spec():
    aliase = config.Konfiguration().wert("kamera.aliase")
    assert aliase["ILCE-7CM2"] == "A7C2"
    assert aliase["ILCE-7C"] == "A7C"
    assert aliase["EPSON Perfection V850"] == "Analog"
    assert len(aliase) == 12
    assert set(aliase.values()) == {"A7C2", "A7C", "Analog"}


def test_erzeugte_datei_ist_gueltiges_toml_und_hat_kommentare(tmp_path):
    pfad = tmp_path / "config.toml"
    config.erzeugen(pfad)
    text = pfad.read_text(encoding="utf-8")
    assert text.lstrip().startswith("#")
    gelesen = tomllib.loads(text)
    assert gelesen["ordner"]["vorlage_ohne_datum"] == "_Ohne_Datum/{kamera}"
    assert gelesen["kamera"]["aliase"]["ILCE-7CM2"] == "A7C2"


def test_datei_und_standardwerte_laufen_nicht_auseinander(tmp_path):
    # Beide kommen aus derselben Vorlage.
    pfad = tmp_path / "config.toml"
    config.erzeugen(pfad)
    aus_datei = tomllib.loads(pfad.read_text(encoding="utf-8"))
    for gruppe, werte in config.STANDARD.items():
        for name, wert in werte.items():
            assert aus_datei[gruppe][name] == wert, f"{gruppe}.{name}"


def test_vorhandene_datei_wird_nie_ueberschrieben(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[ordner]\nvorlage = "eigen"\n', encoding="utf-8")
    config.erzeugen(pfad)
    assert pfad.read_text(encoding="utf-8") == '[ordner]\nvorlage = "eigen"\n'


def test_fehlende_werte_werden_im_speicher_ergaenzt(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[ordner]\nvorlage = "eigen"\n', encoding="utf-8")
    vorher = pfad.read_bytes()
    k = config.laden(pfad)
    assert k.wert("ordner.vorlage") == "eigen"
    assert k.wert("ordner.vorlage_ohne_datum") == "_Ohne_Datum/{kamera}"
    assert k.wert("leistung.profil") == "hdd"
    # Die Datei bleibt dabei unangetastet.
    assert pfad.read_bytes() == vorher


def test_unbekannte_werte_bleiben_stehen_und_werden_gemeldet(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text(
        '[ordner]\nvorlage = "eigen"\nvorlaage = "Tippfehler"\n\n[quatsch]\nx = 1\n',
        encoding="utf-8",
    )
    vorher = pfad.read_bytes()
    k = config.laden(pfad)
    assert "ordner.vorlaage" in k.unbekannte
    assert "quatsch" in k.unbekannte
    assert pfad.read_bytes() == vorher


def test_eigene_aliase_gelten_nicht_als_unbekannt(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text(
        '[kamera.aliase]\n"X-T5" = "Fuji"\n',
        encoding="utf-8",
    )
    k = config.laden(pfad)
    assert k.unbekannte == []
    assert k.wert("kamera.aliase") == {"X-T5": "Fuji"}


def test_laden_ohne_datei_gibt_standardwerte(tmp_path):
    k = config.laden(tmp_path / "gibt-es-nicht.toml")
    assert k.aus_datei is False
    assert k.wert("leistung.profil") == "hdd"


def test_aus_ziel_uebernehmen(tmp_path):
    ziel = tmp_path / "Ziel"
    (ziel / ".fotosortierer").mkdir(parents=True)
    (ziel / ".fotosortierer" / "config.toml").write_text(
        '[kamera.aliase]\n"X-T5" = "Fuji"\n', encoding="utf-8"
    )
    nach = tmp_path / "archiv" / "config.toml"
    assert config.aus_ziel_uebernehmen(ziel, nach) is True
    assert config.laden(nach).wert("kamera.aliase") == {"X-T5": "Fuji"}
    # Ein zweites Mal geschieht nichts: die lokale Datei bleibt die Arbeitsdatei.
    assert config.aus_ziel_uebernehmen(ziel, nach) is False


def test_aus_ziel_uebernehmen_ohne_vorlage_im_ziel(tmp_path):
    assert config.aus_ziel_uebernehmen(tmp_path / "Ziel", tmp_path / "a" / "c.toml") is False


# ------------------------------------------------------ Typ-Pruefung ----
#
# Zwei falsche Typen kehren die Bedeutung um: Eine Zeichenkette statt einer
# Liste wird Zeichen fuer Zeichen gelesen (das Muster "*" darin trifft dann
# alles), und aus dem Wahrheitswert "nein" wird ein Ja.


def test_zeichenkette_statt_liste_bricht_ab(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[quelle]\nausschlussmuster = "*/Papierkorb/*"\n', encoding="utf-8")
    vorher = pfad.read_bytes()
    with pytest.raises(FotosortFehler) as fehler:
        config.laden(pfad)
    text = str(fehler.value)
    assert "quelle.ausschlussmuster" in text
    assert "Liste" in text
    assert "Zeichenkette" in text
    assert pfad.read_bytes() == vorher


def test_zeichenkette_statt_wahrheitswert_bricht_ab(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[quelle]\nverknuepfungen_folgen = "nein"\n', encoding="utf-8")
    with pytest.raises(FotosortFehler) as fehler:
        config.laden(pfad)
    assert "verknuepfungen_folgen" in str(fehler.value)
    assert "Wahrheitswert" in str(fehler.value)


def test_zeichenkette_statt_zahl_bricht_ab(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[leistung]\nkopier_worker = "acht"\n', encoding="utf-8")
    with pytest.raises(FotosortFehler) as fehler:
        config.laden(pfad)
    assert "leistung.kopier_worker" in str(fehler.value)


def test_wahrheitswert_statt_zahl_bricht_ab(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text("[leistung]\nhash_worker = true\n", encoding="utf-8")
    with pytest.raises(FotosortFehler):
        config.laden(pfad)


def test_aliase_muessen_eine_tabelle_sein(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[kamera]\naliase = "X-T5"\n', encoding="utf-8")
    with pytest.raises(FotosortFehler) as fehler:
        config.laden(pfad)
    assert "kamera.aliase" in str(fehler.value)


@pytest.mark.parametrize(
    "inhalt",
    [
        '[quelle]\nausschlussmuster = ["*/Papierkorb/*"]\n',
        "[quelle]\nverknuepfungen_folgen = true\n",
        "[leistung]\nkopier_worker = 8\n",
        '[ordner]\nvorlage = "{jahr}"\n',
        '[kamera.aliase]\n"X-T5" = "Fuji"\n',
    ],
)
def test_richtige_typen_gehen_durch(tmp_path, inhalt):
    pfad = tmp_path / "config.toml"
    pfad.write_text(inhalt, encoding="utf-8")
    assert config.laden(pfad).aus_datei is True


def test_kaputtes_toml_bricht_mit_deutscher_meldung_ab(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[ordner]\nvorlage = "ohne Ende\n', encoding="utf-8")
    vorher = pfad.read_bytes()
    with pytest.raises(FotosortFehler) as fehler:
        config.laden(pfad)
    text = str(fehler.value)
    assert "Konfigurationsdatei" in text
    assert "Zeile 2" in text
    assert str(pfad) in text
    assert pfad.read_bytes() == vorher


def test_die_erzeugte_datei_besteht_die_typ_pruefung(tmp_path):
    pfad = tmp_path / "config.toml"
    config.erzeugen(pfad)
    k = config.laden(pfad)
    assert k.unbekannte == []
