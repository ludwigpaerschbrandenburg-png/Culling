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
    assert s.stand[erstes.schluessel] == (3, "auswahl")
    assert "★★★☆☆" in s.raster.item(0).text() and "Auswahl" in s.raster.item(0).text()
    s.raster.selectAll()
    QTest.keyClick(s.raster, Qt.Key.Key_X)
    assert all(m == "ausschuss" for _st, m in s.stand.values()) and len(s.stand) == s.raster.count()
    assert f"{s.raster.count()} Ausschuss" in s.zahlen.text() or f"{meldungen.anzahl(s.raster.count())} Ausschuss" in s.zahlen.text()

    # Filter
    s.filter.setCurrentIndex(s.filter.findData("auswahl"))
    assert s.raster.count() == 0
    s.filter.setCurrentIndex(s.filter.findData("ab3"))
    assert s.raster.count() == 1
    s.filter.setCurrentIndex(s.filter.findData("alle"))
    s.raster.selectAll()
    QTest.keyClick(s.raster, Qt.Key.Key_U)
    assert {m for _st, m in s.stand.values()} == {""} and s.stand == {erstes.schluessel: (3, "")}

    # Grosse Ansicht: Eingabe oeffnet, Pfeil blaettert, Esc zurueck.
    s.raster.setCurrentRow(jpg)
    QTest.keyClick(s.raster, Qt.Key.Key_Return)
    assert s.stapel.currentWidget() is s.gross
    _fertig_laden(app, s)
    assert s.gross.bild is not None and not s.gross.pixmap().isNull()
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
    erwartet = {erstes.schluessel: (3, ""), gross_schluessel: (5, "")}
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
