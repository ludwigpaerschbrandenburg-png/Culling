"""Phase 7: das Desktop-Fenster (PySide6) - offscreen, am kuenstlichen Testbaum."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from fotosort import cli, meldungen  # noqa: E402
from fotosort.oberflaeche import ablauf as ablauf_modul  # noqa: E402
from fotosort.oberflaeche import desktop, meldungsfenster, stil  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _ereignisse(app, sekunden: float) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        time.sleep(0.02)


def test_fenster_baut_sich_auf_und_schreibt_marker(app, tmp_path):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    assert f.minimumWidth() == 1040 and f.minimumHeight() == 700
    assert f.windowTitle() == "fotosort" and not f.windowIcon().isNull()
    assert f.ansicht == "start" and f.primaer() is not None and f.primaer().text() == "Los geht's"
    marker = tmp_path / "ob" / desktop.MARKER
    assert marker.is_file() and '"sichtbar": true' in marker.read_text(encoding="utf-8")
    # Die Datei "schliessen" beendet das Fenster (so schliesst es die CI).
    (tmp_path / "ob" / desktop.SCHLIESSEN).write_text("", encoding="utf-8")
    _ereignisse(app, 1.6)
    assert not f.isVisible()
    assert '"sichtbar": false' in marker.read_text(encoding="utf-8")


def test_startseite_kennt_archiv_und_quellen(app, tmp_path, quelle, ziel):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    assert ab.ziel == str(ziel) and "NEUES ARCHIV" == f.start.karte.kicker.text()
    f.quelle_hinzufuegen(str(quelle))
    assert ab.quellen == [str(quelle)]
    f.quelle_hinzufuegen(str(ziel))          # Quelle = Ziel: abgelehnt, als Meldung
    assert ab.quellen == [str(quelle)] and f.meldung_label.isVisible()
    f.quelle_entfernen(str(quelle))
    assert ab.quellen == []
    f.start.modus.setzen("verschieben")
    f.einstellungen_senden()
    assert ab.verschieben is True and "gelöscht" in f.start.modus_text.text()
    f.close()


def test_durchlauf_ueber_das_fenster(quelle, ziel, tmp_path, capsys):
    fotos = tmp_path / "fotos"
    rc = cli.main(["fenster", "--durchlauf", str(ziel), str(quelle), "--fotos", str(fotos)])
    aus = capsys.readouterr().out
    assert rc == cli.OK, aus
    assert "Durchlauf bestanden" in aus
    bilder = sorted(p.name for p in fotos.glob("*.png"))
    assert len(bilder) == 12 and bilder[0] == "01-startseite-leer.png" and bilder[-1] == "12-dialog-ordner-anlegen.png"


def test_selbsttest_des_fensters(capsys):
    assert cli.main(["fenster", "--selbsttest"]) == cli.OK
    assert "Selbsttest bestanden: Fenster" in capsys.readouterr().out


def test_stil_schrift_und_symbol(app):
    assert stil.schriften_laden() is True
    from PySide6.QtGui import QFontDatabase
    assert "Inter" in QFontDatabase.families()
    assert stil.symbol(32).width() == 32 and not stil.programm_symbol().isNull()
    assert "#161826" in stil.STYLESHEET and "Segoe UI" in stil.STYLESHEET


def test_meldungsfenster_texte(tmp_path, capsys):
    protokoll = tmp_path / "ordner_fehlt" / "fenster.log"
    meldungsfenster.startfehler(RuntimeError("Python.Runtime.dll fehlt"), protokoll)
    text = protokoll.read_text(encoding="utf-8")
    assert "Startfehler" in text and "Python.Runtime.dll" in text
    aus = capsys.readouterr().err
    assert "konnte nicht starten" in aus and "Protokoll:" in aus and "entpacken" in aus
    assert "PySide6" in meldungen.ob_qt_fehlt("x")


def test_fensterprotokoll_legt_ordner_an(monkeypatch, tmp_path):
    monkeypatch.setenv("FOTOSORT_DATENBANK", str(tmp_path / "gibt es noch nicht (1)"))
    pfad = cli.fenster_protokoll()
    assert pfad.parent.is_dir() and pfad.name == "fenster.log"
    with open(pfad, "a", encoding="utf-8") as f:
        f.write("ok\n")
