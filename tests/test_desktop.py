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


def test_rueckfragen_und_archiv_verwerfen_im_fenster(app, tmp_path, quelle, ziel, monkeypatch, capsys):
    """Laufwerk/Benutzerordner als Quelle und volles Ziel fragen nach; „Archiv
    verwerfen“ verlangt das Wort, laesst kopierte Dateien in Ruhe und leert die Startseite."""
    fragen: list[tuple[str, str]] = []
    antworten: list[tuple[bool, str]] = []

    def frage_ersatz(_eltern, titel, text, eingabe=False, ja="Ja", nein="Abbrechen"):
        fragen.append((titel, ja))
        return antworten.pop(0)

    monkeypatch.setattr(desktop, "frage", frage_ersatz)
    heim = tmp_path / "Benutzer" / "Ludwig"
    heim.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: heim))

    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    assert not f.start.verwerfen.isVisible()               # noch kein Archiv
    antworten.append((False, ""))
    f.quelle_hinzufuegen(str(heim))                        # Benutzerordner -> Frage -> Nein
    assert fragen[-1] == ("Wirklich diesen Ordner?", "Trotzdem nehmen") and ab.quellen == []
    antworten.append((True, ""))
    f.quelle_hinzufuegen(str(heim))                        # -> Ja
    assert ab.quellen == [str(heim)]
    f.quelle_entfernen(str(heim))
    f.quelle_hinzufuegen(str(quelle))
    assert len(fragen) == 2 and ab.quellen == [str(quelle)]

    (ziel / "alt.txt").write_text("x", encoding="utf-8")
    antworten.append((False, ""))
    f.los(False)                                           # volles Ziel -> Frage -> anderen Ordner
    assert fragen[-1] == ("Zielordner ist nicht leer", "Weiter") and ab.lauf is None
    antworten.append((True, ""))
    f.los(False)                                           # -> Weiter: Scan startet
    assert ab.lauf is not None and ab.lauf.schritt == "scan"
    ende = time.monotonic() + 120
    while time.monotonic() < ende and ab.lauf_lebt():
        _ereignisse(app, 0.2)
    _ereignisse(app, 1.0)
    assert f.ab.lauf_status()["zustand"] == "fertig"

    f.laden("start")
    assert f.start.verwerfen.isVisible() and f.start.karte.kicker.text() == "ANGEFANGENES ARCHIV"
    kopie = ziel / "2026" / "bild.jpg"
    kopie.parent.mkdir()
    kopie.write_bytes(b"bild")
    antworten.append((True, "falsch"))
    f.archiv_verwerfen()                                   # falsches Wort: Meldung, nichts weg
    assert fragen[-1] == ("Archiv verwerfen?", "Verwerfen")
    assert (ziel / ".fotosortierer").is_dir() and f.meldung_label.isVisible() and ab.ziel == str(ziel)
    antworten.append((True, "verwerfen"))
    f.archiv_verwerfen()
    assert not (ziel / ".fotosortierer").exists() and kopie.read_bytes() == b"bild"
    assert ab.ziel == "" and f.start.ziel.text() == "" and f.ansicht == "start"
    assert not f.start.verwerfen.isVisible() and "verworfen" in f.meldung_label.text()
    assert not antworten
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


def test_meldungsfenster_texte(tmp_path, monkeypatch):
    # Unter Windows oeffnet zeigen() ein echtes Meldungsfenster und wartet auf Klick -
    # im Test wird es abgefangen und nur der Text geprueft.
    gezeigt: list[tuple[str, str]] = []
    monkeypatch.setattr(meldungsfenster, "zeigen", lambda titel, text: gezeigt.append((titel, text)))
    protokoll = tmp_path / "ordner_fehlt" / "fenster.log"
    meldungsfenster.startfehler(RuntimeError("Python.Runtime.dll fehlt"), protokoll)
    text = protokoll.read_text(encoding="utf-8")
    assert "Startfehler" in text and "Python.Runtime.dll" in text
    assert gezeigt and gezeigt[0][0] == "fotosort konnte nicht starten"
    aus = gezeigt[0][1]
    assert "konnte nicht starten" in aus and "Protokoll:" in aus and "entpacken" in aus and "Python.Runtime.dll" in aus
    assert "PySide6" in meldungen.ob_qt_fehlt("x")


def test_fensterprotokoll_legt_ordner_an(monkeypatch, tmp_path):
    monkeypatch.setenv("FOTOSORT_DATENBANK", str(tmp_path / "gibt es noch nicht (1)"))
    pfad = cli.fenster_protokoll()
    assert pfad.parent.is_dir() and pfad.name == "fenster.log"
    with open(pfad, "a", encoding="utf-8") as f:
        f.write("ok\n")
