"""Phase 13: Testbilder - ein grosser kuenstlicher Testsatz mit beschrifteten Bildern.

Nie echte Fotos: Alles hier entsteht aus Code (testbilder.py). Geprueft wird:
die Erwartung nach der SPEC (unabhaengig vom Programm gerechnet), die
Dateiformate so, wie das Programm sie liest, ein Lauf von Anfang bis Ende,
dass die Pruefung Abweichungen wirklich findet, der Schutz vor einem
fremden Ziel und die Karte im Fenster.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import testbaum  # noqa: E402
from fotosort import FotosortFehler, cli, config, dateitypen, kamera, meldungen, metadaten, testbilder, vorschau  # noqa: E402
from fotosort import testbilder_formate as formate  # noqa: E402

ANZAHL = 300


# ------------------------------------------------------------ Erwartung ----


def test_kameraordner_nach_der_spec():
    k = testbilder.kameraordner
    assert k("SONY", "ILCE-7CM2") == ("A7C2", True)
    assert k("SONY", "ilce-7cm2") == ("A7C2", True)                 # ohne Gross-/Kleinschreibung
    assert k("EPSON", "Perfection V600") == ("Analog", True)        # Hersteller + Modell
    assert k("Noritsu Koki", "QSS-32_33") == ("Analog", True)
    assert k("Canon", "Canon EOS R5") == ("Canon EOS R5", False)
    assert k("Testwerk", 'Cam:Pro/2 "X"?') == ("Cam_Pro_2 _X", False)
    assert k("Testwerk", "Retro Cam.") == ("Retro Cam", False)
    assert k("Testwerk", "CON") == ("CON_", False)
    assert k("Testwerk", "  Mehrfach   Leer  ") == ("Mehrfach Leer", False)
    assert k("Agfa", "") == ("Unbekannte_Kamera", False)


def test_kameraordner_stimmt_mit_dem_programm_ueberein():
    """Die eigene Rechnung und kamera.py kommen fuer jedes Geraet des
    Testsatzes zum selben Ordner - aendert sich eins, faellt es hier auf."""
    konf = config.Konfiguration()
    faelle = [(g.make, g.model) for g in testbilder.GERAETE.values()]
    faelle += [("Testwerk", 'Cam:Pro/2 "X"?'), ("Testwerk", "Retro Cam."), ("Testwerk", "CON"), ("Agfa", ""),
               ("Testwerk", "  Mehrfach   Leer  "), ("Testwerk", "Kamera Ü"), ("SONY", "ilce-7cm2"),
               ("EPSON", "Perfection V850"), ("FUJIFILM", "SP-3000"), ("PLUSTEK", "OpticFilm 8200i")]
    for make, model in faelle:
        felder = {"Make": make, "Model": model.strip()} if model.strip() else {"Make": make}
        assert kamera.ordnername(felder, konf)[0] == testbilder.kameraordner(make, model)[0], (make, model)


def test_zielordner_mit_vorbelegtem_archiv():
    z = testbilder.zielordner
    assert z(date(2024, 3, 11), "A7C2")[0] == "2024/2024-03 März/2024-03-11/A7C2"
    assert z(date(2019, 7, 14), "X")[0] == "2019/2019-07 Juli Sommerurlaub/2019-07-14/X"
    assert z(date(2020, 8, 3), "X")[0] == "2020.08"
    assert z(date(2021, 1, 9), "X")[0] == "2021/01/2021-01-09/X"
    assert z(date(2022, 3, 5), "X")[0] == "2022/März 2022/2022-03-05/X"
    assert z(date(2023, 5, 20), "X")[0] == "2023/2023-05 Mai/2023-05-20 Hochzeit Anna/X"
    assert z(date(2023, 6, 10), "X")[0] == "2023/2023-06 Juni/2023-06-10 Grillfest"


def test_weltzeit_wird_deutsche_zeit():
    assert testbilder.nach_heimat(datetime(2022, 12, 31, 23, 30)) == datetime(2023, 1, 1, 0, 30)    # Winter +1
    assert testbilder.nach_heimat(datetime(2023, 8, 19, 22, 40)) == datetime(2023, 8, 20, 0, 40)    # Sommer +2
    assert testbilder.nach_heimat(datetime(2023, 3, 26, 1, 30)) == datetime(2023, 3, 26, 3, 30)     # Umstellung
    assert testbilder.zone_text(datetime(2023, 7, 1, 12)) == "+02:00"
    assert testbilder.zone_text(datetime(2023, 1, 1, 12)) == "+01:00"


def test_plan_vollstaendig_und_eindeutig():
    plan = testbilder.planen(ANZAHL)
    assert plan.nr == ANZAHL == sum(1 for d in plan.dateien if d.nr)
    assert sorted(d.nr for d in plan.dateien if d.nr) == list(range(1, ANZAHL + 1))
    # Kein Pfad doppelt - auch nicht unter Windows (ohne Gross-/Kleinschreibung).
    quellen = [testbilder._schluessel(d.rel) for d in plan.dateien]
    assert len(quellen) == len(set(quellen))
    ziele = [testbilder._schluessel(d.ziel) for d in plan.dateien if d.erwartung in (testbilder.ARCHIV, testbilder.VORBELEGT)]
    assert len(ziele) == len(set(ziele))
    # Jede Kategorie ist dabei, jede Datei hat eine Begruendung.
    kategorien = {d.kategorie for d in plan.dateien}
    assert set(testbilder._ANTEILE) | {"kamera", "doppelt", "begleit", "sonstiges", "vorbelegt"} <= kategorien
    assert all(d.warum for d in plan.dateien)
    # Schon im Archiv: die Kopie liegt im vorbelegten Archiv; doppelt: das Original kommt hinein.
    for d in plan.dateien:
        if d.erwartung == testbilder.SCHON:
            assert any(k.kopie_von is d and k.erwartung == testbilder.VORBELEGT and k.ziel == d.ziel for k in plan.dateien)
        if d.erwartung == testbilder.DOPPELT:
            assert d.kopie_von.erwartung == testbilder.ARCHIV and d.ziel == d.kopie_von.ziel
    # Jede Endung ist dem Programm bekannt - ausser den absichtlich fremden Dateien.
    konf = config.Konfiguration()
    for d in plan.dateien:
        typ = dateitypen.typ_von(d.name, konf)
        assert (typ == dateitypen.SONSTIGES) == (d.art == "sonstiges"), d.rel


def test_plan_ist_immer_derselbe():
    a, b = testbilder.planen(ANZAHL), testbilder.planen(ANZAHL)
    assert [(d.rel, d.ziel, d.nr) for d in a.dateien] == [(d.rel, d.ziel, d.nr) for d in b.dateien]


def test_zu_wenige_testbilder():
    with pytest.raises(FotosortFehler):
        testbilder.planen(testbilder.MINDESTANZAHL - 1)


def test_schriftprobe_schlaegt_an_wenn_qt_keine_schrift_zeichnet(monkeypatch):
    """Im Windows-Paket der CI waren einige Testbilder gleich: Dann muss das
    Anlegen sofort mit klarer Meldung abbrechen, statt unbeschriftete Bilder
    abzulegen."""
    testbilder.qt_bereit()
    testbilder.schrift_pruefen()                      # hier wird Schrift gezeichnet
    from PySide6.QtGui import QPainter
    monkeypatch.setattr(QPainter, "drawText", lambda *a, **k: None)
    with pytest.raises(FotosortFehler, match="keine lesbare Schrift"):
        testbilder.schrift_pruefen()


def test_schriftprobe_erkennt_kaestchen_statt_buchstaben(monkeypatch):
    """Ohne Schriften malt Qt fuer jeden Buchstaben dasselbe Kaestchen - so im
    Windows-Paket der CI (Qt ohne Bildschirm). Dann sehen gleich lange Texte
    gleich aus, und Testbilder mit gleich langer Beschriftung waren gleich
    (Nr 107, 124, 133, 136). Die Schriftprobe muss auch das erkennen."""
    testbilder.qt_bereit()
    from PySide6.QtGui import QPainter

    def kaestchen(self, rechteck, _ausrichtung, text):
        for i in range(len(text)):
            self.drawRect(rechteck.x() + 12 * i, rechteck.y() + 10, 9, 18)

    monkeypatch.setattr(QPainter, "drawText", kaestchen)
    with pytest.raises(FotosortFehler, match="keine lesbare Schrift"):
        testbilder.schrift_pruefen()


_OHNE_SCHRIFTEN = """
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from fotosort import FotosortFehler, testbilder

app = QApplication([])
try:
    testbilder.schrift_pruefen()
    print("probe: nichts gemerkt")
except FotosortFehler:
    print("probe: abgelehnt")
if len(sys.argv) > 1:
    testbilder.schriften_nachladen(Path(sys.argv[1]))
else:
    testbilder.qt_bereit()
print("nachgeladen", len(testbilder._FAMILIEN))
testbilder.schrift_pruefen()
e = {"kopf": "Testbild 0133 von 300", "kategorie": "Ohne Datum", "felder": [], "farbe": "#4f5b66", "fuss": ""}
print("verschieden", testbilder.zeichnen(e, 600, 400) != testbilder.zeichnen(dict(e, kopf="Testbild 0136 von 300"), 600, 400))
"""


def test_ohne_schriften_laedt_qt_sie_nach(tmp_path):
    """Echtes Qt in einem eigenen Prozess, ohne jede Schrift - wie Qt ohne
    Bildschirm unter Windows: Die Schriftprobe lehnt ab. Nach dem Nachladen
    (unter Windows macht qt_bereit das selbst, aus dem Schriftordner von
    Windows) zeichnet Qt echte Buchstaben, und die Bilder sind verschieden."""
    import subprocess
    import sys

    from test_kopieren import SRC
    umgebung = dict(os.environ, PYTHONPATH=str(SRC), QT_QPA_PLATFORM="offscreen")
    if sys.platform.startswith("win"):
        leer = tmp_path / "keine Schriften"   # Qt ohne Bildschirm sucht Schriften nur hier - wie in der CI
        leer.mkdir()
        umgebung["QT_QPA_FONTDIR"], zusatz = str(leer), []
    else:
        dejavu = next((o for o in (Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"),
                                   Path("/usr/share/fonts/TTF")) if (o / "DejaVuSans.ttf").is_file()), None)
        if dejavu is None:
            pytest.skip("Schrift DejaVu Sans ist hier nicht installiert")
        # fontconfig ohne einen einzigen Schriftordner: Qt findet keine Schrift
        leer = tmp_path / "fonts.conf"
        leer.write_text(f"<?xml version='1.0'?><fontconfig><cachedir>{tmp_path / 'cache'}</cachedir></fontconfig>\n",
                        encoding="utf-8")
        umgebung["FONTCONFIG_FILE"], zusatz = str(leer), [str(dejavu)]
    aus = subprocess.run([sys.executable, "-c", _OHNE_SCHRIFTEN, *zusatz], capture_output=True, text=True, timeout=120,
                         env=umgebung)
    zeilen = aus.stdout.splitlines()
    assert "probe: abgelehnt" in zeilen, aus.stdout + aus.stderr
    assert aus.returncode == 0, aus.stdout + aus.stderr
    assert any(z.startswith("nachgeladen ") and int(z.split()[1]) > 0 for z in zeilen), aus.stdout
    assert "verschieden True" in zeilen, aus.stdout + aus.stderr


def test_eindeutigkeit_nur_absichtliche_kopien_duerfen_gleich_sein():
    a = testbilder.Datei("Quelle/a.jpg", "foto", "jpg", "kamera", nr=1, blake3="aa")
    b = testbilder.Datei("Quelle/b.jpg", "foto", "jpg", "kamera", nr=2, blake3="bb")
    kopie = testbilder.Datei("Quelle/zz Doppelt/a.jpg", "foto", "jpg", "doppelt", blake3="aa", kopie_von=a)
    xmp = [testbilder.Datei(f"Quelle/{n}.xmp", "sidecar", "xmp", "begleit", blake3="xx") for n in "cd"]
    testbilder._eindeutig_pruefen([a, b, kopie, *xmp])          # erlaubt
    gleich = testbilder.Datei("Quelle/c.jpg", "foto", "jpg", "kamera", nr=3, blake3="aa")
    with pytest.raises(FotosortFehler, match="Nr 1 .a.jpg. = Nr 3 .c.jpg."):
        testbilder._eindeutig_pruefen([a, b, gleich])


# --------------------------------------------------------------- Formate ----


def test_formate_so_wie_das_programm_sie_liest(tmp_path):
    """JPEG, RAW, HEIC, MP4 mit Sony-Daten und AVI: Datum, Modell und
    Vorschau kommen genau so an, wie Analyse und „Sichten“ sie lesen."""
    testbilder.qt_bereit()
    programm = testbaum.exiftool_pfad()
    e = {"kopf": "Testbild 1", "kategorie": "Test", "felder": [("Datei", "x.jpg", False)], "farbe": "#336699", "fuss": "Test"}
    jpeg = testbilder.kodieren(testbilder.zeichnen(e, 480, 320), "jpg")
    werte = {"make": "SONY", "model": "ILCE-7CM2", "dto": "2023:03:14 18:22:05", "create": "2023:03:14 18:22:05",
             "offset": "+01:00", "titel": "Testbild 1", "kommentar": "Soll nach: März"}
    dateien = {
        "foto.jpg": formate.jpeg_mit_exif(jpeg, werte),
        "bild.ARW": formate.raw_datei(werte, jpeg),
        "bild.DNG": formate.raw_datei(dict(werte, make="LEICA CAMERA AG", model="LEICA Q2"), jpeg, dng=True),
        "bild.HEIC": formate.heic(dict(werte, make="Apple", model="iPhone 15 Pro"), jpeg),
        "film.MP4": formate.film(jpeg, 480, 320, b"XAVC", datetime(2022, 12, 31, 23, 30),
                                 formate.sony_xml("2023-01-01T00:30:00+01:00", "ILCE-7C")),
        "alt.AVI": formate.avi(jpeg, 480, 320, formate.idit_text(datetime(2007, 8, 15, 14, 22, 33))),
    }
    for name, daten in dateien.items():
        (tmp_path / name).write_bytes(daten)
    konf = config.Konfiguration()
    eintraege = [(str(tmp_path / n), dateitypen.typ_von(n, konf)) for n in dateien]
    with metadaten.ExifToolPool(programm, 1) as pool:
        gelesen: dict = {}
        for stapel in metadaten.stapel_bilden(eintraege):
            gelesen.update(pool.einreichen(stapel).result())
    f = {Path(k).name: v for k, v in gelesen.items()}
    for name in ("foto.jpg", "bild.ARW", "bild.HEIC"):
        assert f[name]["DateTimeOriginal"] == "2023:03:14 18:22:05", name
    assert f["bild.ARW"]["Model"] == "ILCE-7CM2" and f["bild.HEIC"]["Model"] == "iPhone 15 Pro"
    assert f["bild.DNG"]["Model"] == "LEICA Q2"
    assert f["film.MP4"]["CreateDate"] == "2022:12:31 23:30:00"
    assert f["film.MP4"]["CreationDateValue"] == "2023:01:01 00:30:00+01:00"
    assert f["film.MP4"]["DeviceModelName"] == "ILCE-7C"
    assert f["alt.AVI"]["DateTimeOriginal"] == "2007:08:15 14:22:33"
    # Die Beschriftung von RAW und HEIC ist ein echtes Vorschaubild (Reiter „Sichten“).
    leser = vorschau.Vorschauleser(programm)
    try:
        for name in ("bild.ARW", "bild.DNG", "bild.HEIC"):
            daten, _drehung = leser.lesen(tmp_path / name)
            assert daten == jpeg, name
    finally:
        leser.schliessen()


# --------------------------------------------------------- Ende zu Ende ----


@pytest.fixture(scope="module")
def sortiert(tmp_path_factory):
    """300 Testbilder anlegen und mit dem Programm sortieren (Befehle wie im
    Handbuch: testbilder, scan, analyse, kopieren, pruefen)."""
    wurzel = tmp_path_factory.mktemp("testbilder")
    test = wurzel / "Testbilder"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FOTOSORT_DATENBANK", str(wurzel / "archive"))
        mp.delenv("FOTOSORT_ZIEL", raising=False)
        mp.delenv("FOTOSORT_EXIFTOOL", raising=False)
        assert cli.main(["testbilder", str(test), "--anzahl", str(ANZAHL)]) == cli.OK
        z, q = str(test / testbilder.ZIEL), str(test / testbilder.QUELLE)
        assert cli.main(["scan", "--ziel", z, "--quelle", q]) == cli.OK
        for schritt in ("analyse", "kopieren", "pruefen"):
            assert cli.main([schritt, "--ziel", z]) == cli.OK
    return test


def _kopie(sortiert: Path, tmp_path: Path) -> Path:
    ziel = tmp_path / "Kopie"
    shutil.copytree(sortiert, ziel)
    for alt in ziel.glob("Prüfbericht*.html"):
        alt.unlink()
    return ziel


def _eintrag(test: Path, erwartung: str, art: str = "foto") -> dict:
    import json
    daten = json.loads((test / testbilder.MARKE).read_text(encoding="utf-8"))
    return next(e for e in daten["dateien"] if e["erwartung"] == erwartung and e["art"] == art and e["nr"])


def test_alles_am_erwarteten_platz(sortiert):
    p = testbilder.pruefen(sortiert)
    assert p.ok, testbilder.pruef_text(p)
    assert p.richtig == p.erwartet > ANZAHL and p.verloren == 0
    assert p.bericht is not None and p.bericht.is_file()
    bericht = p.bericht.read_text(encoding="utf-8")
    assert "Alles richtig" in bericht
    # Je Kategorie: wie viele Dateien, wie viele richtig - im Bericht als Tabelle.
    assert set(p.je_kategorie) >= set(testbilder._ANTEILE) | {"kamera"}
    assert all(richtig == gesamt for gesamt, richtig in p.je_kategorie.values())
    assert sum(gesamt for gesamt, _ in p.je_kategorie.values()) == p.erwartet
    titel, _was = meldungen.TB_KATEGORIEN["video"]
    assert titel in bericht


def test_uebersicht_und_erwartung_zum_lesen(sortiert):
    """Übersicht.html nennt die Anleitung ohne doppelte Nummern und jede
    Kategorie; Erwartung.csv hat je Datei eine Zeile (Excel: BOM, Semikolon)."""
    html = (sortiert / "Übersicht.html").read_text(encoding="utf-8")
    assert "1. 1." not in html and "<ol>" not in html
    for k, (titel, _was) in meldungen.TB_KATEGORIEN.items():
        if k != "begleit":
            assert titel in html, titel
    roh = (sortiert / "Erwartung.csv").read_bytes()
    assert roh.startswith(b"\xef\xbb\xbf")
    zeilen = roh.decode("utf-8-sig").splitlines()
    assert zeilen[0].startswith("Nr;Datei in der Quelle;")
    assert len(zeilen) == 1 + len(testbilder.planen(ANZAHL).dateien)


def test_befehl_pruefen_meldet_das_ergebnis(sortiert, tmp_path, capsys):
    test = _kopie(sortiert, tmp_path)
    assert cli.main(["testbilder", str(test), "--pruefen"]) == cli.OK
    assert "Alles richtig" in capsys.readouterr().out


def test_pruefung_findet_eine_verschobene_datei(sortiert, tmp_path):
    test = _kopie(sortiert, tmp_path)
    e = _eintrag(test, testbilder.ARCHIV)
    alt = test / testbilder.ZIEL / e["ziel"]
    neu = test / testbilder.ZIEL / "Falscher Ordner" / alt.name
    neu.parent.mkdir()
    alt.rename(neu)
    p = testbilder.pruefen(test)
    assert not p.ok and p.verloren == 0
    assert any(b.datei == e["datei"] and "stattdessen" in b.text and "Falscher Ordner" in b.text for b in p.befunde)


def test_pruefung_findet_fehlende_und_veraenderte_dateien(sortiert, tmp_path):
    test = _kopie(sortiert, tmp_path)
    import json
    daten = json.loads((test / testbilder.MARKE).read_text(encoding="utf-8"))
    archiv = [e for e in daten["dateien"] if e["erwartung"] == testbilder.ARCHIV and e["art"] == "foto"]
    weg, anders = archiv[0], archiv[1]
    (test / testbilder.ZIEL / weg["ziel"]).unlink()
    with open(test / testbilder.ZIEL / anders["ziel"], "ab") as f:
        f.write(b"x")
    p = testbilder.pruefen(test)
    texte = {b.datei: b.text for b in p.befunde}
    assert texte[weg["datei"]] == meldungen.TB_P_NOCH_NICHT       # die Quelle hat sie noch
    assert texte[anders["datei"]] == meldungen.TB_P_ANDERS
    assert p.verloren == 0


def test_pruefung_findet_unerwartete_datei_und_duldet_xmp_aus_sichten(sortiert, tmp_path):
    test = _kopie(sortiert, tmp_path)
    e = _eintrag(test, testbilder.ARCHIV)
    bild = test / testbilder.ZIEL / e["ziel"]
    (bild.parent / (bild.stem + ".xmp")).write_text("<x/>", encoding="utf-8")       # „XMP-Dateien anlegen“
    (test / testbilder.ZIEL / "2024" / "fremd.jpg").write_bytes(b"\xff\xd8fremd")
    p = testbilder.pruefen(test)
    assert [b.datei for b in p.befunde] == [f"{testbilder.ZIEL}/2024/fremd.jpg"]
    assert p.befunde[0].text == meldungen.TB_P_UNERWARTET
    assert len(p.hinweise) == 1


def test_alle_testbilder_sind_verschieden(sortiert):
    import json
    daten = json.loads((sortiert / testbilder.MARKE).read_text(encoding="utf-8"))
    nummern = [e["blake3"] for e in daten["dateien"] if e["nr"]]
    assert len(nummern) == ANZAHL == len(set(nummern))


def test_pruefung_nennt_ein_gleiches_testbild(sortiert, tmp_path):
    """Wie im Windows-Paket der CI: Zwei Testbilder sind gleich, das Programm
    legt den Inhalt zu Recht nur einmal ab - die Pruefung sagt, mit welchem."""
    import json
    test = _kopie(sortiert, tmp_path)
    marke = test / testbilder.MARKE
    daten = json.loads(marke.read_text(encoding="utf-8"))
    a, b = [e for e in daten["dateien"] if e["erwartung"] == testbilder.ARCHIV and e["art"] == "foto" and e["nr"]][:2]
    (test / testbilder.ZIEL / b["ziel"]).unlink()
    b["blake3"] = a["blake3"]
    marke.unlink()
    marke.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    p = testbilder.pruefen(test)
    text = next(x.text for x in p.befunde if x.datei == b["datei"])
    assert f"Testbild {a['nr']}" in text and "gleich" in text


def test_pruefung_findet_verlorenen_inhalt(sortiert, tmp_path):
    test = _kopie(sortiert, tmp_path)
    e = _eintrag(test, testbilder.ARCHIV)
    (test / testbilder.ZIEL / e["ziel"]).unlink()
    (test / e["datei"]).unlink()
    p = testbilder.pruefen(test)
    assert p.verloren == 1 and not p.ok
    assert any(b.schwer and b.datei == e["datei"] for b in p.befunde)
    assert "VERLOREN" in testbilder.pruef_text(p)


def test_pruefung_findet_angefasste_schon_importierte(sortiert, tmp_path):
    test = _kopie(sortiert, tmp_path)
    e = _eintrag(test, testbilder.SCHON)
    with open(test / e["datei"], "ab") as f:
        f.write(b"x")
    p = testbilder.pruefen(test)
    assert any(b.datei == e["datei"] and b.text == meldungen.TB_P_QUELLE_ANDERS for b in p.befunde)


def test_pruefbericht_wird_nie_ueberschrieben(sortiert, tmp_path):
    test = _kopie(sortiert, tmp_path)
    erster = testbilder.pruefen(test).bericht
    inhalt = erster.read_bytes()
    zweiter = testbilder.pruefen(test).bericht
    assert zweiter != erster and zweiter.name == "Prüfbericht (2).html"
    assert erster.read_bytes() == inhalt


# ---------------------------------------------------------------- Schutz ----


def test_testbilder_nie_in_ein_fremdes_ziel(sortiert, tmp_path, capsys):
    fremd = tmp_path / "Echtes Archiv"
    fremd.mkdir()
    quelle = sortiert / testbilder.QUELLE
    for q in (quelle, quelle / "WhatsApp"):
        assert cli.main(["scan", "--ziel", str(fremd), "--quelle", str(q)]) == cli.FEHLER
        assert "nie in ein echtes Archiv" in capsys.readouterr().out
    assert list(fremd.iterdir()) == []                      # nichts angelegt
    # Dieselbe Pruefung gilt fuer das Fenster und den gefuehrten Modus.
    assert cli._start_quelle_pruefen(str(quelle), fremd, set(), [], fenster=True) is not None
    assert testbilder.fremdes_ziel(quelle, sortiert / testbilder.ZIEL) is None
    assert testbilder.fremdes_ziel(tmp_path, fremd) is None   # gewoehnliche Quelle


# -------------------------------------------------------------- Erzeugen ----


def test_erzeugen_nur_in_einen_leeren_ordner(tmp_path):
    ordner = tmp_path / "voll"
    ordner.mkdir()
    (ordner / "wichtig.txt").write_text("bleibt", encoding="utf-8")
    with pytest.raises(FotosortFehler, match="nicht leer"):
        testbilder.erzeugen(ordner, ANZAHL, exiftool=testbaum.exiftool_pfad())
    assert [p.name for p in ordner.iterdir()] == ["wichtig.txt"]
    assert (ordner / "wichtig.txt").read_text(encoding="utf-8") == "bleibt"


def test_abbruch_hinterlaesst_keinen_fertigen_testordner(tmp_path):
    stop = threading.Event()
    stop.set()
    with pytest.raises(testbilder.Abgebrochen):
        testbilder.erzeugen(tmp_path / "T", ANZAHL, exiftool=testbaum.exiftool_pfad(), stop=stop)
    assert not testbilder.ist_testordner(tmp_path / "T")      # die Marke kommt zuletzt


def test_neuer_testordner_nimmt_nie_einen_vorhandenen(tmp_path):
    assert testbilder.neuer_testordner(tmp_path) == tmp_path / meldungen.TB_ORDNERNAME
    (tmp_path / meldungen.TB_ORDNERNAME).mkdir()
    assert testbilder.neuer_testordner(tmp_path) == tmp_path / f"{meldungen.TB_ORDNERNAME} (2)"


# ---------------------------------------------------------------- Fenster ----


def test_fenster_legt_testbilder_an_und_prueft(tmp_path, monkeypatch):
    PySide6 = pytest.importorskip("PySide6")  # noqa: F841
    from PySide6.QtWidgets import QApplication, QFileDialog

    from fotosort.oberflaeche import ablauf as ablauf_modul
    from fotosort.oberflaeche import desktop

    app = QApplication.instance() or QApplication([])
    fragen: list[str] = []
    monkeypatch.setattr(desktop, "frage", lambda _e, titel, _t, *a, **k: (fragen.append(titel) or (titel == meldungen.OB_TB_TITEL), ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    monkeypatch.setattr(desktop.Hauptfenster, "testbilder_anzahl", ANZAHL)
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    f.show()
    assert f.start.tb_anlegen.isEnabled() and not f.start.tb_pruefen.isEnabled()
    andere = tmp_path / "Echte Fotos"
    andere.mkdir()
    f.quelle_hinzufuegen(str(andere))            # schon gewaehlt, aber noch nicht begonnen
    assert f.ab.quellen == [str(andere)]

    def warten(bis, sekunden=120.0):
        ende = time.monotonic() + sekunden
        while not bis() and time.monotonic() < ende:
            app.processEvents()
            time.sleep(0.02)
        assert bis()

    f.start.tb_anlegen.click()
    warten(lambda: f._hintergrund is None and fragen)
    test = tmp_path / meldungen.TB_ORDNERNAME
    assert testbilder.ist_testordner(test)
    assert f.start.ziel.text() == str(test / testbilder.ZIEL)
    assert f.ab.quellen == [str(test / testbilder.QUELLE)]    # nie mit anderen Quellen gemischt
    assert andere.is_dir()                                    # nur aus der Liste, nichts angefasst
    assert f.start.tb_pruefen.isEnabled()
    # Pruefen vor dem Sortieren: Abweichungen, im Fenster gemeldet, Bericht geschrieben.
    f.start.tb_pruefen.click()
    warten(lambda: f._hintergrund is None and meldungen.OB_TB_PRUEF_TITEL in fragen)
    assert f.meldung_label.isVisible() and "Abweichungen" in f.meldung_label.text()
    assert (test / "Prüfbericht.html").is_file()
    f.close()
