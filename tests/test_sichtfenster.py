"""Reiter „Sichten“ im Desktop-Fenster (Entscheidung 15, v0.8) - offscreen,
an einem Archiv aus dem kuenstlichen Testbaum.

Der Reiter bewertet nur. Jeder Test prueft am Ende, dass im Archiv keine
Datei veraendert, verschoben, geloescht oder hinzugekommen ist und dass
die Hauptdatenbank (fotosort.db) nicht angefasst wurde.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import testbaum  # noqa: E402
from fotosort import cli, db, hashes, meldungen, sichten  # noqa: E402
from fotosort.oberflaeche import ablauf as ablauf_modul  # noqa: E402
from fotosort.oberflaeche import desktop, sichtfenster  # noqa: E402
from test_kopieren import _cli, _vorbereiten  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _ereignisse(app, sekunden: float) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        time.sleep(0.02)


def _stand(ziel: Path) -> dict[str, tuple[str, int]]:
    return {str(p.relative_to(ziel)): (hashes.blake3_datei(p), p.stat().st_mtime_ns)
            for p in sorted(ziel.rglob("*")) if p.is_file() and db.ARCHIV_UNTERORDNER not in p.parts}


def _lokal(ziel: Path, archiv_basis: Path) -> Path:
    return archiv_basis / db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()


def _fertig_laden(app, seite) -> None:
    seite.pool.waitForDone(30000)
    _ereignisse(app, 0.3)


def test_sichten_zeigt_das_archiv_und_bewertet_ohne_etwas_zu_veraendern(app, tmp_path, quelle, ziel, archiv_basis):
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    vorher = _stand(ziel)
    lokal = _lokal(ziel, archiv_basis)
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob", ziel=str(ziel))
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.5)
    def hauptdb() -> dict:
        return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in lokal.glob("fotosort.db*")}

    db_vorher = hauptdb()

    f.reiter.knoepfe["sichten"].click()
    s = f.sichten
    assert f.reiter_stapel.currentWidget() is s
    assert s.ordner_jetzt is not None and s.ordner_jetzt.is_relative_to(ziel)
    assert s.raster.count() > 0
    _fertig_laden(app, s)
    # JPEGs haben eine Vorschau bekommen (kein Platzhalter mehr).
    jpg = next(i for i in range(s.raster.count())
               if s.alle[s.raster.item(i).data(sichtfenster.ROLLE_NR)].anzeige.suffix.lower() in (".jpg", ".jpeg"))
    assert s.raster.item(jpg).icon().cacheKey() not in (s._icon_leer.cacheKey(), s._icon_keins.cacheKey())

    # Sterne und Markierungen ueber die Tasten.
    s.raster.setCurrentRow(0)
    erstes = s.alle[s.raster.item(0).data(sichtfenster.ROLLE_NR)]
    QTest.keyClick(s.raster, Qt.Key.Key_3)
    QTest.keyClick(s.raster, Qt.Key.Key_P)
    assert s.stand[erstes.schluessel] == (3, "auswahl", "")
    assert "★★★☆☆" in s.raster.item(0).text() and "Auswahl" in s.raster.item(0).text()
    s.raster.selectAll()
    QTest.keyClick(s.raster, Qt.Key.Key_X)
    assert all(b.markierung == "ausschuss" for b in s.stand.values()) and len(s.stand) == s.raster.count()
    assert f"{s.raster.count()} Ausschuss" in s.zahlen.text() or f"{meldungen.anzahl(s.raster.count())} Ausschuss" in s.zahlen.text()

    # Filter
    s.filter.setCurrentIndex(s.filter.findData("auswahl"))
    assert s.raster.count() == 0
    s.filter.setCurrentIndex(s.filter.findData("ab3"))
    assert s.raster.count() == 1
    s.filter.setCurrentIndex(s.filter.findData("alle"))
    s.raster.selectAll()
    QTest.keyClick(s.raster, Qt.Key.Key_U)
    assert {b.markierung for b in s.stand.values()} == {""} and s.stand == {erstes.schluessel: (3, "", "")}

    # Grosse Ansicht: Eingabe oeffnet, Pfeil blaettert, Esc zurueck.
    s.raster.setCurrentRow(jpg)
    QTest.keyClick(s.raster, Qt.Key.Key_Return)
    assert s.stapel.currentWidget() is s.gross
    _fertig_laden(app, s)
    assert s.gross.bild is not None and not s.gross.bild.isNull()
    QTest.keyClick(s.gross, Qt.Key.Key_5)
    gross_schluessel = s.alle[s.gross_nr].schluessel
    assert s.stand[gross_schluessel][0] == 5 and "★★★★★" in s.titel.text()
    QTest.keyClick(s.gross, Qt.Key.Key_Escape)
    assert s.stapel.currentWidget() is s.raster

    # Zurueck zum Archiv: der bisherige Ablauf ist unveraendert da.
    f.reiter.knoepfe["archiv"].click()
    assert f.reiter_stapel.currentWidget() is f.archiv_reiter
    f.close()

    # Bewertungen bleiben (neues Fenster, neue Seite) - in bewertungen.db.
    erwartet = {erstes.schluessel: (3, "", ""), gross_schluessel: (5, "", "")}
    assert sichten.Bewertungen(lokal).lesen(list(erwartet)) == erwartet
    # Im Archiv hat sich nichts geaendert, und fotosort.db ist unberuehrt.
    assert _stand(ziel) == vorher
    assert hauptdb() == db_vorher


def test_sichten_ohne_archiv_sagt_was_zu_tun_ist(app, tmp_path):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.reiter_wechseln("sichten")
    assert f.sichten.stapel.currentWidget() is f.sichten.hinweis
    assert f.sichten.hinweis.text() == meldungen.SICHTEN_KEIN_ARCHIV
    QTest.keyClick(f.sichten.raster, Qt.Key.Key_3)          # nichts gewaehlt: keine Wirkung, kein Fehler
    f.close()


def test_drehung_wie_in_der_datei(tmp_path):
    """Die Vorschau aus einem RAW traegt keine Drehung - sie kommt aus dem RAW
    und wird von Hand angewandt. Das Ergebnis muss dem gleichen, was Qt bei
    einem JPEG mit derselben Drehung selbst macht (alle acht Werte)."""
    QApplication.instance() or QApplication([])
    bild = QImage(30, 20, QImage.Format.Format_RGB32)
    bild.fill(QColor("blue"))
    for x in range(10):
        for y in range(5):
            bild.setPixelColor(x, y, QColor("red"))
    vorlage = tmp_path / "vorlage.jpg"
    assert bild.save(str(vorlage), "JPG", 100)
    for drehung in range(1, 9):
        datei = testbaum._schreiben(tmp_path / f"d{drehung}.jpg", vorlage.read_bytes())
        testbaum._exiftool([["-q", "-overwrite_original", f"-Orientation#={drehung}", str(datei)]])
        daten = datei.read_bytes()
        von_qt = sichtfenster.aus_daten(daten, 0)
        von_hand = sichtfenster.aus_daten(daten, 0, drehung)
        assert von_qt is not None and von_hand is not None
        assert von_hand == von_qt, drehung


def test_reiter_verlassen_haelt_das_laden_an_und_zurueck_geht_es_weiter(app, tmp_path, quelle, ziel, monkeypatch):
    """Pruefer-Befund (v0.8): Wer zum Reiter „Archiv“ wechselt, soll die Platte
    nicht weiter mit Vorschaubildern belasten; zurueck im Reiter „Sichten“
    werden die fehlenden nachgeladen."""
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    probe = ziel / "2027" / "2027-01-01"                      # der neueste Tag: beim Oeffnen gewaehlt
    for i in range(6):
        testbaum._schreiben(probe / f"P_{i:04d}.jpg", testbaum._JPEG)
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob", ziel=str(ziel))
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    geladen: list = []
    echt = sichtfenster.bild_laden

    def langsam(*a, **k):
        geladen.append(1)
        time.sleep(0.2)                    # eine langsame Platte
        return echt(*a, **k)

    monkeypatch.setattr(sichtfenster, "bild_laden", langsam)
    f.sichten.pool.setMaxThreadCount(1)
    f.reiter_wechseln("sichten")
    s = f.sichten
    assert s.ordner_jetzt == probe and len(s.alle) == 6
    f.reiter_wechseln("archiv")
    _fertig_laden(app, s)
    assert len(geladen) < len(s.alle)                          # angehalten, nicht alles gelesen
    f.reiter_wechseln("sichten")
    _fertig_laden(app, s)
    assert all(nr in s.vorschau for nr in s.gezeigt if s.alle[nr].art != "video")   # fehlende nachgeladen
    f.close()


def test_vorschau_auf_ssd_mit_allen_kernen(monkeypatch):
    """Seit v0.9: Auf einer SSD rechnet jeder Kern ein Vorschaubild, auf einer
    Festplatte bleiben es drei Leser."""
    monkeypatch.setattr(sichtfenster.os, "cpu_count", lambda: 24)
    assert sichtfenster.leser_fuer("ssd") == 24
    assert sichtfenster.leser_fuer("hdd") == sichtfenster.LESER == sichtfenster.leser_fuer("")
    monkeypatch.setattr(sichtfenster.os, "cpu_count", lambda: 2)
    assert sichtfenster.leser_fuer("ssd") == sichtfenster.LESER


# --- Runde 3b (v0.11): Sichten wie ein Profi -----------------------------------------


@pytest.fixture
def sicht(app, tmp_path, quelle, ziel):
    """Ein Archiv aus dem Testbaum plus ein Tagesordner mit sechs Bildern
    (der neueste, also beim Oeffnen gewaehlt); das Fenster im Reiter Sichten."""
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    probe = ziel / "2027" / "2027-01-01"
    for i in range(6):
        testbaum._schreiben(probe / f"P_{i:04d}.jpg", testbaum._JPEG)
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob", ziel=str(ziel))
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.reiter_wechseln("sichten")
    s = f.sichten
    _fertig_laden(app, s)
    yield f, s, probe
    f.close()


def test_farben_per_taste_und_knopf(app, sicht):
    f, s, _probe = sicht
    s.raster.setCurrentRow(0)
    erstes = s.alle[s.raster.item(0).data(sichtfenster.ROLLE_NR)]
    QTest.keyClick(s.raster, Qt.Key.Key_6)
    assert s.stand[erstes.schluessel].farbe == "rot" and "Rot" in s.raster.item(0).text()
    QTest.keyClick(s.raster, Qt.Key.Key_6)                       # noch einmal: weg
    assert erstes.schluessel not in s.stand
    s.farb_knoepfe["lila"].click()
    assert s.stand[erstes.schluessel].farbe == "lila"
    s.sterne_knoepfe[4].click()
    assert s.stand[erstes.schluessel] == (4, "", "lila")
    s.filter.setCurrentIndex(s.filter.findData("farbe_lila"))
    assert s.raster.count() == 1
    s.filter.setCurrentIndex(s.filter.findData("unbewertet"))
    assert s.raster.count() == len(s.alle) - 1


def test_nach_dem_bewerten_weiter(app, sicht):
    f, s, _probe = sicht
    s.weiter.setChecked(True)
    s.raster.setCurrentRow(0)
    QTest.keyClick(s.raster, Qt.Key.Key_3)
    assert s.raster.currentRow() == 1
    s.gross_zeigen(s.gezeigt[1])
    QTest.keyClick(s.gross, Qt.Key.Key_2)
    assert s.gross_nr == s.gezeigt[2]
    assert s.stand[s.alle[s.gezeigt[1]].schluessel].sterne == 2


def test_bewertung_aus_vorhandener_xmp_wird_gezeigt_und_beim_aendern_uebernommen(app, sicht, archiv_basis):
    f, s, probe = sicht
    (probe / "P_0000.xmp").write_text('<x:xmpmeta><rdf:Description xmp:Rating="4" xmp:Label="Blue"/></x:xmpmeta>', encoding="utf-8")
    s.neu_einlesen()
    erstes = next(b for b in s.alle if b.name == "P_0000.jpg")
    assert s.stand[erstes.schluessel] == (4, "", "blau") and erstes.schluessel in s.aus_xmp
    assert "Blau" in s.eintraege[s.alle.index(erstes)].text()
    s.raster.setCurrentRow(s.gezeigt.index(s.alle.index(erstes)))
    QTest.keyClick(s.raster, Qt.Key.Key_5)
    # Gespeichert mit der Farbe aus der XMP-Datei - die XMP-Datei selbst bleibt.
    assert s.bew.lesen([erstes.schluessel])[erstes.schluessel] == (5, "", "blau")
    assert "Blue" in (probe / "P_0000.xmp").read_text(encoding="utf-8")


def test_xmp_knopf_legt_nur_neue_dateien_an(app, sicht, monkeypatch):
    f, s, probe = sicht
    vorhanden = probe / "P_0001.xmp"
    vorhanden.write_bytes(b"<x:xmpmeta>von Lightroom</x:xmpmeta>")
    s.neu_einlesen()
    vorher = _stand(s.ziel)
    for name, sterne in (("P_0001.jpg", 3), ("P_0002.jpg", 5)):
        nr = next(i for i, b in enumerate(s.alle) if b.name == name)
        s.raster.clearSelection()
        s.raster.setCurrentRow(s.gezeigt.index(nr))
        s.bewerten(sterne=sterne)
    monkeypatch.setattr(sichtfenster.QMessageBox, "question", lambda *a, **k: sichtfenster.QMessageBox.StandardButton.Yes)
    s.xmp_knopf.click()
    s.xmp_pool.waitForDone(30000)
    _ereignisse(app, 0.2)
    nachher = _stand(s.ziel)
    neu = set(nachher) - set(vorher)
    assert {Path(n).name for n in neu} == {"P_0002.xmp"}, neu
    assert all(nachher[n] == vorher[n] for n in vorher)                 # nichts Vorhandenes geaendert
    assert "1 XMP-Datei neu angelegt" in s.zahlen.text() and "schon eine" in s.zahlen.text()
    # Nein auf die Frage: nichts geschieht.
    monkeypatch.setattr(sichtfenster.QMessageBox, "question", lambda *a, **k: sichtfenster.QMessageBox.StandardButton.No)
    s.xmp_knopf.click()
    assert _stand(s.ziel) == nachher


def test_vergleich_von_drei_bildern(app, sicht):
    f, s, _probe = sicht
    s.raster.setCurrentRow(0)
    QTest.keyClick(s.raster, Qt.Key.Key_C)                       # nur eines gewaehlt
    assert s.stapel.currentWidget() is s.raster and "zwei bis vier" in s.zahlen.text()
    for i in range(3):
        s.raster.item(i).setSelected(True)
    QTest.keyClick(s.raster, Qt.Key.Key_C)
    assert s.stapel.currentWidget() is s.vergleich
    sichtbar = [feld for feld in s.vergleich.felder if feld.isVisible()]
    assert len(sichtbar) == 3
    _fertig_laden(app, s)
    assert all(feld.bild is not None for feld in sichtbar)
    QTest.keyClick(s.vergleich.felder[0], Qt.Key.Key_Right)
    QTest.keyClick(s.vergleich.felder[0], Qt.Key.Key_2)
    zweites = s.alle[s.vergleich.nummern[1]]
    assert s.stand[zweites.schluessel].sterne == 2
    assert s.vergleich.felder[1].aktiv and "★★☆☆☆" in s.vergleich.unter[1].text()
    QTest.keyClick(s.vergleich.felder[0], Qt.Key.Key_Escape)
    assert s.stapel.currentWidget() is s.raster


def test_lupe_und_vorab_laden(app, sicht):
    f, s, _probe = sicht
    s.gross_zeigen(s.gezeigt[0])
    _fertig_laden(app, s)
    assert s.gross.bild is not None
    # Die Nachbarn liegen schon bereit.
    assert s.gezeigt[1] in s.gross_bilder
    QTest.keyClick(s.gross, Qt.Key.Key_Z)
    assert s.gross.lupe
    _fertig_laden(app, s)
    assert s.gross.voll is not None
    QTest.keyClick(s.gross, Qt.Key.Key_Z)
    assert not s.gross.lupe
    # Blaettern zum vorab geladenen Bild zeigt es sofort.
    QTest.keyClick(s.gross, Qt.Key.Key_Right)
    assert s.gross.bild is not None and s.gross_nr == s.gezeigt[1]


def test_kameradaten_in_der_grossen_ansicht(app, sicht):
    f, s, _probe = sicht
    # Ein Tag des Testbaums mit EXIF-Daten (Sony ILCE-7CM2).
    ordner = next(p.parent for p in s.ziel.rglob("DSC01234*.JPG"))
    s._ordner_gewaehlt(s._finden(ordner))
    nr = next(i for i, b in enumerate(s.alle) if b.name.startswith("DSC01234"))
    s.gross_zeigen(nr)
    _fertig_laden(app, s)
    assert s.kameradaten.isVisible() and "ILCE-7CM2" in s.kameradaten.text(), s.kameradaten.text()


def test_vorschaubilder_werden_lokal_zwischengespeichert(app, tmp_path, sicht, monkeypatch, archiv_basis):
    f, s, probe = sicht
    zwischen = s.zwischen
    assert zwischen is not None and zwischen.is_dir() and zwischen.is_relative_to(_lokal(s.ziel, archiv_basis))
    dateien = list(zwischen.rglob("*.vorschau"))
    assert len(dateien) >= 6
    assert not list(s.ziel.rglob("*.vorschau"))                 # nie im Archiv
    gelesen: list = []
    echt = sichtfenster.bild_laden
    monkeypatch.setattr(sichtfenster, "bild_laden", lambda *a, **k: gelesen.append(1) or echt(*a, **k))
    s.neu_einlesen()
    _fertig_laden(app, s)
    assert not gelesen and all(not s.vorschau[i].isNull() for i in s.gezeigt)



def test_geloeschte_bewertung_bleibt_geloescht_trotz_xmp(app, sicht):
    """Pruefer-Befund (v0.11): Sterne auf 0 bei einem Bild mit XMP-Datei - nach
    "Neu einlesen" duerfen die Sterne aus der XMP nicht zurueckkommen."""
    f, s, probe = sicht
    (probe / "P_0003.xmp").write_text('<x xmp:Rating="4"/>', encoding="utf-8")
    s.neu_einlesen()
    nr = next(i for i, b in enumerate(s.alle) if b.name == "P_0003.jpg")
    s.raster.clearSelection()
    s.raster.setCurrentRow(s.gezeigt.index(nr))
    QTest.keyClick(s.raster, Qt.Key.Key_0)
    s.neu_einlesen()
    assert s.bewertung(s.alle[nr]).sterne == 0
