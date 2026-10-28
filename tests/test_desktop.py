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
from test_unterbrechungen import _hart_beenden, _kopierte, _pruefen_gleich, grosse_quelle, referenz  # noqa: E402,F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _ereignisse(app, sekunden: float) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        time.sleep(0.02)


def _fenster(ordner: Path, automatisch: bool = False) -> desktop.Hauptfenster:
    """Ein Fenster wie beim Start. Seit v0.13 ist „Alles automatisch“ der
    Standard; Tests, die Schritt fuer Schritt klicken, stellen das ab."""
    ab = ablauf_modul.Ablauf(ordner=ordner)
    ab.einstellungen_setzen(automatisch=automatisch)
    return desktop.Hauptfenster(ab)


def test_fenster_baut_sich_auf_und_schreibt_marker(app, tmp_path):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    # SPEC §8: 1040x700 - auf einem kleineren Bildschirm (offscreen: 800x800) angepasst.
    flaeche = app.primaryScreen().availableGeometry()
    _b, _h, mb, mh = desktop.fenstermasse(flaeche.width(), flaeche.height())
    assert (f.minimumWidth(), f.minimumHeight()) == (mb, mh)
    assert f.width() <= flaeche.width() and f.height() <= flaeche.height()
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
    assert ab.ziel == str(ziel) and "Neues Archiv" == f.start.karte.kicker.text()
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

    f = _fenster(tmp_path / "ob")
    ab = f.ab
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
    assert f.start.verwerfen.isVisible() and f.start.karte.kicker.text() == "Angefangenes Archiv"
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


def _bis_im_fenster(app, bedingung, sekunden: float = 240.0) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        if bedingung():
            return
        time.sleep(0.02)
    raise AssertionError("im Fenster nicht eingetreten")


def test_fenster_zu_neu_auf_und_absturz_im_fenster(app, tmp_path, grosse_quelle, ziel, referenz, nachschauen, monkeypatch):
    """Teil 3 im Fenster: Fenster waehrend des Scans schliessen (seit v0.9 mit
    Rueckfrage, danach ist alles aus), neu oeffnen, weiter, Analyse und Kopieren
    per Knopf, harter Abschuss mitten im Kopieren (Anzeige: unerwartet beendet,
    Protokoll sichtbar, Knopf zum Weitermachen), noch einmal neu oeffnen,
    "Weitermachen" - am Ende wie der Referenzlauf."""
    monkeypatch.setattr(desktop, "frage", lambda *a, **k: (True, ""))
    ordner = tmp_path / "ob"
    f = _fenster(ordner)
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    f.quelle_hinzufuegen(str(grosse_quelle))
    f.los(False)
    assert f.ansicht == "haupt" and f.poll.isActive()
    f.close()                                                   # Fenster zu: Scan haelt an, alles aus
    assert not f.ab.lauf_lebt()
    _ereignisse(app, 0.2)

    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.show()
    _ereignisse(app, 0.6)
    assert f.ansicht == "start"
    f.los(False)                                                # noch einmal durchsuchen, dann weiter
    _bis_im_fenster(app, f.in_ruhe)
    assert f.primaer().text().startswith("Analyse starten")
    f.primaer().click()
    _bis_im_fenster(app, f.in_ruhe)
    assert f.primaer().text().startswith("Kopieren starten")
    f.primaer().click()
    _bis_im_fenster(app, lambda: f.ab.lauf is not None and f.ab.lauf.schritt == "kopieren", 30)
    pid = f.ab.lauf.pid
    _bis_im_fenster(app, lambda: _kopierte(ziel) >= 200, 120)
    _hart_beenden(pid)
    _bis_im_fenster(app, lambda: f.lauf.get("zustand") == "abgestuerzt", 60)
    _bis_im_fenster(app, f.in_ruhe, 30)
    assert f.haupt.log.isVisible() and "unerwartet" in f.haupt.aktuell.text().lower()
    assert f.primaer().text().startswith("Kopieren starten")     # Weitermachen genau hier
    f.close()

    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.show()
    _ereignisse(app, 0.5)
    assert f.ansicht == "start" and f.start.weitermachen.isEnabled()
    assert f.start.weitermachen.text() == "Weitermachen: Kopieren"
    f.start.weitermachen.click()
    _bis_im_fenster(app, f.in_ruhe, 30)
    assert f.primaer().text().startswith("Kopieren starten")
    f.primaer().click()
    _bis_im_fenster(app, lambda: f.in_ruhe() and f.lauf.get("zustand") == "fertig")
    assert f.primaer().text().startswith("Prüfen starten")
    _pruefen_gleich(f.ab, ziel, referenz, nachschauen)
    f.close()


def test_durchlauf_ueber_das_fenster(quelle, ziel, tmp_path, capsys, monkeypatch):
    """Mit relativen Pfaden: Der Arbeitsprozess laeuft in einem anderen Ordner
    als das Fenster - frueher fand er dann seine Statusdatei nicht und der
    erste Schritt galt als abgestuerzt."""
    from PySide6.QtGui import QImage

    monkeypatch.chdir(tmp_path)
    fotos = tmp_path / "fotos"
    rc = cli.main(["fenster", "--durchlauf", os.path.relpath(ziel), os.path.relpath(quelle), "--fotos", "fotos"])
    aus = capsys.readouterr().out
    assert rc == cli.OK, aus
    assert "Durchlauf bestanden" in aus
    bilder = sorted(p.name for p in fotos.glob("*.png"))
    assert len(bilder) == 14 and bilder[0] == "01-startseite-leer.png" and bilder[-1] == "14-frage-alles-automatisch.png"
    # Die Bildschirmfotos fuer die Anleitung zeigen das Fenster in voller Groesse.
    bild = QImage(str(fotos / "03-uebersicht-nach-scan.png"))
    assert (bild.width(), bild.height()) == (1180, 800)


def test_selbsttest_des_fensters(capsys):
    assert cli.main(["fenster", "--selbsttest"]) == cli.OK
    assert "Selbsttest bestanden: Fenster" in capsys.readouterr().out


def test_stil_schrift_und_symbol(app):
    assert stil.symbol(32).width() == 32 and not stil.programm_symbol().isNull()


def test_aussehen_wie_ein_windows_programm(app, tmp_path, quelle, ziel):
    """Entscheidung des Nutzers vom 27.10.2026: Das Fenster soll nicht nach KI
    aussehen, sondern wie ein Windows-11-Programm. Also: Grundstil des Systems
    (unter Windows "windows11", sonst Fusion), Farben aus der Palette des
    Systems (hell oder dunkel wie Windows), keine Schreibmaschinenschrift,
    keine Ueberschriften in Grossbuchstaben, keine Punkt-Trenner "·"."""
    from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit
    stil.einrichten(app)
    erwartet = "windows11" if sys.platform.startswith("win") else "fusion"
    assert app.property("fotosort_grundstil") == erwartet == stil.grundstil()
    blatt = app.styleSheet()
    import re
    assert not re.search(r"#[0-9a-fA-F]{6}\b|rgba\(", blatt.replace(stil.gedaempft_farbe(app.palette()), "")), blatt
    for verboten in ("monospace", "letter-spacing", "Inter", "Consolas"):
        assert verboten not in blatt, verboten
    assert cli.main(["scan", "--ziel", str(ziel), "--quelle", str(quelle)]) == cli.OK
    assert cli.main(["analyse", "--ziel", str(ziel)]) == cli.OK
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    _ereignisse(app, 0.2)

    def texte():
        for w in f.findChildren(QLabel) + f.findChildren(QAbstractButton) + f.findChildren(QLineEdit):
            t = w.text() if not isinstance(w, QLineEdit) else w.placeholderText()
            if t:
                yield w, t
            assert "monospace" not in (w.styleSheet() or "")
            assert w.font().family() not in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Inter")
        from PySide6.QtWidgets import QTableWidget
        for tabelle in f.findChildren(QTableWidget):     # auch Tabellenkoepfe (Kamera-Tabelle, Listen)
            for i in range(tabelle.columnCount()):
                kopf = tabelle.horizontalHeaderItem(i)
                if kopf is not None and kopf.text():
                    yield tabelle, kopf.text()

    def pruefen():
        for w, t in texte():
            assert "·" not in t, (type(w).__name__, t)
            buchstaben = [c for c in t if c.isalpha()]
            assert not (len(buchstaben) > 3 and all(c.isupper() for c in buchstaben)), (type(w).__name__, t)

    pruefen()
    f.start.weitermachen.click()
    _bis_im_fenster(app, f.in_ruhe, 30)
    pruefen()
    f.close()


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


def test_startseite_bietet_das_zurueckholen_der_datenbank_an(app, tmp_path, quelle, ziel, monkeypatch, archiv_basis):
    """Datenbank weg, Sicherung da: Knopf „Datenbank zurückholen…“, Rueckfrage, dann ist alles wieder da."""
    fragen: list[tuple[str, str]] = []
    antworten: list[tuple[bool, str]] = []

    def frage_ersatz(_eltern, titel, text, eingabe=False, ja="Ja", nein="Abbrechen"):
        fragen.append((titel, ja))
        return antworten.pop(0)

    monkeypatch.setattr(desktop, "frage", frage_ersatz)
    assert cli.main(["scan", "--ziel", str(ziel), "--quelle", str(quelle)]) == cli.OK
    kennung = (ziel / ".fotosortierer" / "archiv-id.txt").read_text(encoding="utf-8").strip()
    lokal = archiv_basis / kennung
    for name in ("fotosort.db", "fotosort.db-wal", "fotosort.db-shm"):
        if (lokal / name).exists():
            (lokal / name).unlink()

    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    assert f.start.karte.kicker.text() == "Archiv ohne Merkliste"
    assert f.start.rettung.isVisible() and f.start.rettung.text() == "Datenbank zurückholen…"
    assert not f.start.weitermachen.isVisible()
    antworten.append((False, ""))
    f.rettung()                                            # Rueckfrage -> Nicht jetzt
    assert fragen[-1] == ("Datenbank zurückholen?", "Zurückholen") and not (lokal / "fotosort.db").exists()
    antworten.append((True, ""))
    f.rettung()                                            # -> Zurueckholen
    assert (lokal / "fotosort.db").is_file()
    assert "zurückgeholt" in f.meldung_label.text()
    assert not f.start.rettung.isVisible() and f.start.karte.kicker.text() == "Angefangenes Archiv"
    assert f.start.weitermachen.isVisible() and f.start.weitermachen.text().startswith("Weitermachen")
    assert not antworten
    f.close()


def test_durchlauf_laeuft_nur_am_testbaum(app, tmp_path, quelle, ziel, capsys):
    """Der Durchlauf raeumt am Ende die Quelle auf - deshalb nur mit der Marke des Testbaums."""
    fremd = tmp_path / "Echte Fotos"
    fremd.mkdir()
    (fremd / "IMG_0001.JPG").write_bytes(b"\xff\xd8\xff")
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    d = desktop.Durchlauf(f, str(ziel), str(fremd), None, None)
    d.starten()
    _ereignisse(app, 0.5)
    assert "Testbaum" in d.fehler and not d.timer.isActive()
    assert (fremd / "IMG_0001.JPG").exists() and ab.lauf is None
    # Der Testbaum selbst traegt die Marke.
    assert (Path(quelle).parent / desktop.TESTBAUM_MARKE).is_file()
    f.close()


# --------------------------------------- Befunde "Fehlersuche Bedienung" --


def _kennzahl_texte(f) -> list[str]:
    texte = []
    for i in range(f.haupt.kennzahlen.count()):
        w = f.haupt.kennzahlen.itemAt(i).widget()
        if w is not None:
            texte.append(w.text())
    return texte


def _aktion_texte(f) -> list[str]:
    return [f.aktionen.itemAt(i).widget().text() for i in range(f.aktionen.count())
            if f.aktionen.itemAt(i).widget() is not None]


def test_restzeit_steht_nach_dem_ende_nicht_mehr_da(app, tmp_path):
    """Frueher stand "Rest wird berechnet" neben "Fertig" und "Rest 7 min" neben
    "Abgebrochen" - bis zum naechsten Lauf."""
    from fotosort import steuerung
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    for zustand in (steuerung.ZUSTAND_FERTIG, steuerung.ZUSTAND_ABGEBROCHEN):
        st = steuerung.Steuerung(ab.status_datei, ab.steuer_datei, "kopieren")
        st.melden(21, 21, 7900, 7900)
        st.beenden(zustand, 0)
        l = ab.lauf_status()
        assert l["restzeit_s"] is None and l["text"]["restzeit"] == ""
        f.haupt.kennzahlen_setzen(l)
        assert not [t for t in _kennzahl_texte(f) if t.startswith("Rest")]
        # Auch ein alter Stand mit Restzeit zeigt sie nach dem Ende nicht.
        l["text"]["restzeit"] = "7 min"
        f.haupt.kennzahlen_setzen(l)
        assert not [t for t in _kennzahl_texte(f) if t.startswith("Rest")]
    f.close()


def test_nicht_ausgefuehrter_schritt_nennt_den_grund(app, tmp_path):
    """Scheitert ein Schritt vor dem Anfangen (zu wenig Platz), hiess es "Beendet,
    aber mit Fehlern" - der Grund stand nur im grauen Protokollkasten."""
    from fotosort import steuerung
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    st = steuerung.Steuerung(ab.status_datei, ab.steuer_datei, "kopieren")
    st.beenden(steuerung.ZUSTAND_FEHLER, 1, meldungen.zu_wenig_platz(tmp_path, 10 ** 9, 10 ** 6))
    l = ab.lauf_status()
    assert "Beendet" not in l["zustand_text"] and "nicht" in l["zustand_text"].lower()
    f.lauf_fuellen(l)
    assert "Beendet" not in f.haupt.aktuell.text()
    assert "wenig Platz" in f.meldung_label.text()
    f.close()


def test_durchgelaufen_mit_fehlern_heisst_nicht_nicht_fertig(app, tmp_path, quelle, ziel, monkeypatch):
    """Pruefer-Befund (v0.11): Eine Analyse, die durchlief, aber bei einer
    Datei einen Fehler meldete, hiess im Fenster "Nicht fertig geworden – der
    Grund steht oben", und oben stand der interne Name 'analyse'."""
    from fotosort import steuerung
    assert cli.main(["scan", "--ziel", str(ziel), "--quelle", str(quelle)]) == cli.OK
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    auftrag = tmp_path / "auftrag.json"
    import json
    auftrag.write_text(json.dumps({"schritt": "analyse", "ziel": str(ziel), "status_datei": str(ab.status_datei),
                                   "steuer_datei": str(ab.steuer_datei)}), encoding="utf-8")
    monkeypatch.setattr(cli, "befehl_analyse", lambda args, konsole: cli.FEHLER)   # mit Fehlern durchgelaufen
    cli.main(["arbeit", "--auftrag", str(auftrag)])
    l = ab.lauf_status()
    assert l["zustand"] == steuerung.ZUSTAND_FEHLER
    assert l["zustand_text"] == meldungen.OB_ZUSTAND["fehler"], l["zustand_text"]
    assert "'analyse'" not in l["hinweis"]


def test_fehlender_gemerkter_zielordner_ist_kein_neues_archiv(app, tmp_path, monkeypatch):
    """Platte nicht angeschlossen oder Ordner umbenannt: frueher "NEUES ARCHIV"
    und eine Anlegen-Frage ohne Warnung vor einem zweiten, leeren Archiv."""
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    weg = tmp_path / "Archiv auf der USB-Platte"
    f.start.ziel_setzen(str(weg))
    assert f.start.karte.kicker.text() == "Zielordner nicht gefunden"
    assert "angeschlossen" in f.start.archiv_text.text()
    assert "angeschlossen" in meldungen.ob_frage_ziel_anlegen(weg)
    f.close()


def test_verwerfen_mit_leerem_wort_ist_keine_erfolgsmeldung(app, tmp_path, quelle, ziel, monkeypatch):
    antworten = [(True, "")]
    monkeypatch.setattr(desktop, "frage", lambda *a, **k: antworten.pop(0))
    assert cli.main(["scan", "--ziel", str(ziel), "--quelle", str(quelle)]) == cli.OK
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.start.ziel_setzen(str(ziel))
    f.archiv_verwerfen()
    assert f.meldung_label.text() == meldungen.ob_wort_falsch(meldungen.BESTAETIGUNGSWORT["verwerfen"])
    assert f.meldung_label.property("klasse") != "hell"
    assert (ziel / ".fotosortierer" / "archiv-id.txt").is_file()
    f.close()


def test_zahlen_im_fenster_mit_tausenderpunkt(app, tmp_path):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.zustand = {"verschieben": False}
    f.ruhe_aktionen({"schritt": "fertig"}, {"fehler": 12345, "duplikate": 2000})
    texte = _aktion_texte(f)
    assert "Fehler 12.345" in texte and "Duplikate 2.000" in texte
    assert meldungen.dezimal(1234.5) == "1.234,5"
    assert meldungen.groesse(1023.5 * 1024 * 1024) == "1.023,5 MB"
    f.close()


def test_startgroesse_passt_auf_kleine_bildschirme():
    """1920x1080 mit 150 % Skalierung laesst etwa 1280x672 - "Los geht's" lag
    frueher unter der Bildschirmkante."""
    b, h, mb, mh = desktop.fenstermasse(1280, 672)
    assert b <= 1280 and h <= 672 and mb <= b and mh <= h
    assert desktop.fenstermasse(2560, 1400) == (1180, 800, 1040, 700)   # grosse Bildschirme wie bisher


def test_lange_arbeit_zeigt_den_wartezeiger(app, tmp_path, monkeypatch):
    """Probestart von ExifTool (bis 20 s) lief ohne jede Rueckmeldung; Windows
    meldet dann "Keine Rueckmeldung". Jetzt: Wartezeiger und gesperrte Knoepfe."""
    gesehen = []

    def langsam(*a, **k):
        gesehen.append((QApplication.overrideCursor() is not None, f.aktionen_gesperrt()))
        return {"frage": None}

    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    monkeypatch.setattr(ab, "los", langsam)
    f.los(False)
    assert gesehen == [(True, True)]
    assert QApplication.overrideCursor() is None and not f.aktionen_gesperrt()
    f.close()


def test_verschieben_bestaetigung_nennt_die_anweisung_nur_einmal(app, tmp_path, monkeypatch):
    texte = []
    monkeypatch.setattr(desktop, "frage", lambda _e, _t, text, **k: texte.append(text) or (False, ""))
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    n = {"schritt": "kopieren", "wort": "verschieben", "text": meldungen.ob_kopieren_text(3, 3000, True)}
    f.kopieren_starten(n)
    assert texte and texte[0].count("verschieben“") <= 1 and "Zum Bestätigen „verschieben“ tippen" not in texte[0]
    f.close()


def test_knopf_archiv_nachpruefen(app, tmp_path, quelle, ziel, monkeypatch):
    fragen = []
    monkeypatch.setattr(desktop, "frage", lambda _e, titel, text, **k: fragen.append((titel, text)) or (False, ""))
    for befehl in ("scan", "analyse", "kopieren", "pruefen"):
        args = [befehl, "--ziel", str(ziel)] + (["--quelle", str(quelle)] if befehl == "scan" else [])
        assert cli.main(args) == cli.OK
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.start.ziel_setzen(str(ziel))
    f.weitermachen()
    assert "Archiv nachprüfen…" in _aktion_texte(f)
    f.nachpruefen()
    assert fragen and fragen[0][0] == "Archiv nachprüfen?" and "Prüfsumme" in fragen[0][1]
    assert ab.lauf is None                     # "Nicht jetzt": nichts gestartet
    f.close()


def test_hilfe_zeigt_die_anleitung_im_fenster(app, tmp_path):
    """F1 oder der Knopf "Hilfe" zeigt die LIESMICH lesbar im Programm - ohne
    Browser und ohne die Frage, womit man eine .md-Datei oeffnet."""
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    assert ablauf_modul.anleitung_pfad() is not None and ablauf_modul.anleitung_pfad().name == "LIESMICH.md"
    fenster = f.hilfe_zeigen(modal=False)
    try:
        text = fenster.findChild(desktop.QTextBrowser).toPlainText()
        assert "fotosort" in text and "#" not in text.splitlines()[0]   # als Text dargestellt, nicht roh
        assert any(k.key().toString() == "F1" for k in f.findChildren(desktop.QShortcut))
    finally:
        fenster.close()
        f.close()


def test_fertiger_schritt_meldet_sich_in_der_taskleiste(app, tmp_path, monkeypatch):
    """Ein langer Schritt endet, waehrend der Nutzer etwas anderes tut: das
    Fenster blinkt in der Taskleiste (wie bei Kopierprogrammen ueblich)."""
    from fotosort import steuerung
    gemeldet = []
    monkeypatch.setattr(desktop.QApplication, "alert", lambda fenster, ms=0: gemeldet.append(fenster))
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    st = steuerung.Steuerung(ab.status_datei, ab.steuer_datei, "pruefen")
    st.beenden(steuerung.ZUSTAND_FERTIG, 0)
    f.poll.start()
    f.lauf_abfragen()
    assert gemeldet == [f]
    f.close()


def test_wartezeiger_laesst_keine_zeitgeber_dazwischen(app, tmp_path, monkeypatch):
    """Der Wartezeiger darf die Ereignisschleife nicht laufen lassen: Sonst springt
    ein Zeitgeber (Statusabfrage, Durchlauf) mitten in einen Klick hinein und
    loest denselben Schritt ein zweites Mal aus."""
    from PySide6.QtCore import QTimer
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    gefeuert = []
    t = QTimer()
    t.setInterval(0)
    t.timeout.connect(lambda: gefeuert.append(1))
    t.start()
    with f.beschaeftigt():
        assert not gefeuert
    t.stop()
    f.close()


def test_knopf_zuruecklegen_nur_mit_inhalt_im_ordner(app, tmp_path, quelle, ziel, monkeypatch):
    """Die Aufraeumen-Karte bietet "Zuruecklegen..." nur an, wenn das Programm
    etwas in einen Ordner _geloescht_ gelegt hat; die Rueckfrage nennt die Zahl."""
    fragen = []
    monkeypatch.setattr(desktop, "frage", lambda _e, titel, text, **k: fragen.append((titel, text)) or (False, ""))
    for befehl in ("scan", "analyse", "kopieren", "pruefen"):
        args = [befehl, "--ziel", str(ziel)] + (["--quelle", str(quelle)] if befehl == "scan" else [])
        assert cli.main(args) == cli.OK
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.start.ziel_setzen(str(ziel))
    f.weitermachen()
    assert f.haupt.zurueck_los.isHidden()
    monkeypatch.setenv("FOTOSORT_EINGABE_ERZWINGEN", "1")
    monkeypatch.setattr("builtins.input", lambda: "verschieben")
    assert cli.main(["aufraeumen", "--ziel", str(ziel)]) == cli.OK
    f.weitermachen()
    assert not f.haupt.zurueck_los.isHidden() and f.haupt.zurueck_los.isEnabled()
    text = f.haupt.zurueck_los.text()
    assert "zurücklegen" in text and text.endswith(")") and text[text.rindex("(") + 1] != "0"
    f.zuruecklegen()
    assert fragen and fragen[-1][0] == "Zurücklegen?" and "überschrieben" in fragen[-1][1]
    assert ab.lauf is None                     # "Nicht jetzt": nichts gestartet
    f.close()


def test_profil_vorschlag_im_fenster(app, tmp_path, quelle, ziel, monkeypatch):
    """Entscheidung 1 (v0.8): Das Fenster zeigt, was erkannt wurde; ein
    Moduswechsel macht den Vorschlag nicht zur eigenen Wahl, ein Klick schon."""
    art = {"wert": "ssd"}
    monkeypatch.setattr(ablauf_modul.kopieren.pfade, "laufwerksart", lambda p: art["wert"])
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    assert f.start.profil.wert() == "ssd" and "SSD" in f.start.profil_text.text()
    f.start.modus.setzen("verschieben")
    f.einstellungen_senden()
    assert ab.profil_von_hand is False
    art["wert"] = "hdd"
    f.quelle_hinzufuegen(str(quelle))
    assert f.start.profil.wert() == "hdd" and "Festplatte" in f.start.profil_text.text()
    f.start.profil.knoepfe["netzwerk"].click()
    assert ab.profil == "netzwerk" and ab.profil_von_hand is True
    assert "Erkannt" not in f.start.profil_text.text()
    f.close()


def test_schliessen_fragt_und_haelt_den_schritt_an(app, tmp_path, grosse_quelle, ziel, monkeypatch):
    """Entscheidung vom 26.10.2026: Fenster zu = Programm aus. Laeuft ein
    Schritt, fragt das Fenster kurz; „Weiterarbeiten“ laesst alles offen,
    „Beenden“ haelt den Schritt sauber an und wartet, bis er aus ist."""
    from test_unterbrechungen import _bis, _vorbereitet
    antworten = [(False, ""), (True, "")]
    gefragt: list = []

    def frage_ersatz(_eltern, titel, text, **k):
        gefragt.append((titel, text, k))
        return antworten.pop(0)

    monkeypatch.setattr(desktop, "frage", frage_ersatz)
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    f = desktop.Hauptfenster(ab)
    assert ab.fenster_pid == os.getpid()                       # der Schritt gehoert zu diesem Fenster
    f.show()
    _ereignisse(app, 0.3)
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    assert ab.lauf.auftrag["fenster_pid"] == os.getpid()
    _bis(lambda: _kopierte(ziel) >= 30)
    f.close()
    assert f.isVisible() and ab.lauf_lebt()                     # „Weiterarbeiten“
    f.close()
    assert not f.isVisible() and not ab.lauf_lebt()             # „Beenden“
    assert ab.lauf_status()["zustand"] == "abgebrochen"
    assert len(gefragt) == 2 and "Kopieren" in gefragt[0][1]


def test_schliessen_ohne_lauf_fragt_nicht(app, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "frage", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gefragt")))
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    f.show()
    _ereignisse(app, 0.3)
    f.close()
    assert not f.isVisible()



def test_nur_eine_instanz(app, tmp_path):
    """Ein zweiter Doppelklick oeffnet kein zweites Fenster, sondern holt das
    offene nach vorn (seit v0.9)."""
    ordner = tmp_path / "ob"
    erste = desktop.Instanz(ordner)
    assert erste.erste and not erste.geweckt()
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.instanz = erste
    f.show()
    _ereignisse(app, 0.2)
    f.showMinimized()
    _ereignisse(app, 0.2)
    zweite = desktop.Instanz(ordner)
    assert not zweite.erste                                    # bekommt die Sperre nicht
    _ereignisse(app, 1.5)                                      # Waechter: jede Sekunde
    assert not f.isMinimized() and not (ordner / desktop.WECKEN).exists()
    f.close()                                                  # gibt die Sperre frei
    dritte = desktop.Instanz(ordner)
    assert dritte.erste
    dritte.freigeben()


def test_fremden_schritt_haelt_das_fenster_nicht_an(app, tmp_path, grosse_quelle, ziel, monkeypatch):
    """Pruefer-Befund (v0.9): Ein Schritt, den nicht dieses Fenster gestartet
    hat (Browser-Fassung auf dem Server), laeuft beim Schliessen weiter -
    ohne Rueckfrage."""
    from test_unterbrechungen import _bis, _vorbereitet
    monkeypatch.setattr(desktop, "frage", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gefragt")))
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    ab.fenster_pid = None                                      # wie ein Schritt aus der Browser-Fassung
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    _bis(lambda: _kopierte(ziel) >= 10)
    f.close()
    assert not f.isVisible() and ab.lauf_lebt()
    assert ab.beenden(warten=60)


def test_beenden_frage_verspricht_nichts_falsches():
    text = desktop.meldungen.ob_beenden_frage("Kopieren")
    assert "Nichts geht verloren" in text and "in der Regel" in text


# ------------------------------------------ Alles automatisch (seit v0.13) --


def _antworten_fuer(fragen: list, wort: str = "verschieben", beenden: bool = True):
    """Beantwortet jede Frage wie ein Nutzer, der alles automatisch will."""
    def frage_ersatz(_eltern, titel, text, eingabe=False, ja="Ja", nein="Abbrechen"):
        fragen.append((titel, text))
        if titel == meldungen.OB_KETTE_TITEL:
            return True, wort
        if titel == meldungen.OB_BEENDEN_TITEL:
            return beenden, ""
        return True, ""
    return frage_ersatz


def _inhalte(wurzel: Path) -> list[str]:
    import hashlib
    return sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in wurzel.rglob("*") if p.is_file())


def test_schalter_alles_automatisch_auf_der_startseite(app, tmp_path):
    """Entscheidung des Nutzers vom 28.10.2026: als Schalter, Standard an."""
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app, 0.3)
    assert f.start.ablauf.wert() == "automatisch" and ab.automatisch is True
    assert "_geloescht_" in f.start.ablauf_text.text()
    f.start.ablauf.knoepfe["einzeln"].click()
    assert ab.automatisch is False and f.start.ablauf_text.text() == meldungen.OB_ABLAUF_TEXT_EINZELN
    f.close()
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    f.show()
    _ereignisse(app, 0.3)
    assert f.start.ablauf.wert() == "einzeln"                   # gemerkt
    f.start.ablauf.knoepfe["automatisch"].click()
    f.start.modus.knoepfe["verschieben"].click()
    assert f.ab.automatisch is True and f.ab.verschieben is True
    assert meldungen.OB_KETTE_VERSCHIEBEN_HINWEIS in f.start.ablauf_text.text()
    f.close()


def test_hauptknopf_bei_automatik(app, tmp_path):
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    for verschieben, automatisch, erwartet in (
            (False, True, "Automatisch weiter ab Kopieren"),
            (False, False, "Kopieren starten (3 Dateien)"),
            (True, True, "Verschieben starten (3 Dateien)")):          # Verschieben bestaetigt der Nutzer selbst
        f.zustand = {"verschieben": verschieben, "automatisch": automatisch}
        f.ruhe_aktionen({"schritt": "kopieren", "n": 3}, {})
        assert f.primaer().text() == erwartet
    f.zustand = {"verschieben": False, "automatisch": True}
    for schritt, name in (("analyse", "Analyse"), ("pruefen", "Prüfen"), ("aufraeumen", "Aufräumen")):
        f.ruhe_aktionen({"schritt": schritt}, {})
        assert f.primaer().text() == f"Automatisch weiter ab {name}"
    f.close()


def test_alles_automatisch_im_fenster(app, tmp_path, quelle, ziel, monkeypatch):
    """Ein Klick auf „Los geht's“ und einmal das Wort - dann kein Klick mehr bis
    „Alles erledigt“. Zwischen den Schritten weder Ruheansicht noch Blinken in
    der Taskleiste; der PC bleibt waehrend des ganzen Ablaufs wach und wird
    danach losgelassen."""
    fragen: list = []
    monkeypatch.setattr(desktop, "frage", _antworten_fuer(fragen, " Verschieben "))
    gemeldet: list = []
    monkeypatch.setattr(desktop.QApplication, "alert", lambda fenster, ms=0: gemeldet.append(fenster))
    wach: list[bool] = []
    monkeypatch.setattr(desktop.prozesse, "wach_halten", lambda an: wach.append(an) or True)
    vorher = _inhalte(quelle)
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    f.quelle_hinzufuegen(str(quelle))
    f.los(False)
    assert [t for t, _ in fragen] == [meldungen.OB_KETTE_TITEL]
    assert "_geloescht_" in fragen[0][1] and str(quelle) in fragen[0][1]
    assert f.ansicht == "haupt" and f.poll.isActive() and wach == [True]
    _bis_im_fenster(app, lambda: f.in_ruhe() and not f.ab.lauf_lebt(), 300)
    assert f.ab.naechster()["schritt"] == "fertig"
    assert "erledigt" in f.meldung_label.text() and f.meldung_label.property("klasse") == "hell"
    assert gemeldet == [f]                      # einmal blinken - am Ende, nicht nach jedem Schritt
    assert wach == [True, False]                # waehrend des ganzen Ablaufs wach, danach losgelassen
    assert len(fragen) == 1                     # nach dem Wort keine Frage mehr
    assert any(p.name.startswith("_geloescht_") for p in quelle.iterdir())
    assert _inhalte(quelle) == vorher           # kein Inhalt verloren
    assert f.primaer().text() == "Bericht öffnen"
    f.close()


def test_ohne_richtiges_wort_startet_im_fenster_nichts(app, tmp_path, quelle, ziel, monkeypatch):
    antworten = [(False, ""), (True, ""), (True, "ja")]
    monkeypatch.setattr(desktop, "frage", lambda *a, **k: antworten.pop(0))
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    f.quelle_hinzufuegen(str(quelle))
    f.los(False)                                         # „Abbrechen“
    assert f.ab.lauf is None and f.ansicht == "start"
    f.los(False)                                         # leeres Wort
    assert f.ab.lauf is None and f.meldung_label.text() == meldungen.ob_wort_falsch("verschieben")
    f.meldung("")
    f.los(False)                                         # falsches Wort: der Kern weigert sich
    assert f.ab.lauf is None and f.meldung_label.text() == meldungen.ob_wort_falsch("verschieben")
    assert not antworten and not f.ab.status_datei.exists()
    f.close()


def test_offene_abbrechen_frage_haelt_den_ablauf_an(app, tmp_path, quelle, ziel, monkeypatch):
    """Endet ein Schritt, waehrend „Schritt abbrechen?“ noch offen ist, beginnt
    kein neuer - und „Abbrechen“ haelt dann den ganzen Ablauf an. Danach nimmt
    „Automatisch weiter ab …“ ihn nach dem Wort wieder auf."""
    waehrend_der_frage: list = []
    fragen: list = []

    def frage_ersatz(_eltern, titel, text, eingabe=False, ja="Ja", nein="Abbrechen"):
        fragen.append(titel)
        if titel == meldungen.OB_KETTE_TITEL:
            return True, "verschieben"
        for _ in range(3):                    # der Zeitgeber laeuft weiter, solange die Frage offen ist
            f.lauf_abfragen()
        waehrend_der_frage.append(f.ab.lauf_lebt())
        return True, ""                       # „Abbrechen“

    monkeypatch.setattr(desktop, "frage", frage_ersatz)
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=tmp_path / "ob"))
    f.start.ziel_setzen(str(ziel))
    f.quelle_hinzufuegen(str(quelle))
    f.los(False)
    f.poll.stop()                             # der Scan endet, bevor das Fenster nachsieht
    ende = time.monotonic() + 120
    while f.ab.lauf_lebt() and time.monotonic() < ende:
        time.sleep(0.05)
    l = f.ab.lauf_status()
    assert l["zustand"] == "fertig" and l["kette"] is True
    f.poll.start()
    f.abbrechen_fragen()
    assert waehrend_der_frage == [False]
    assert not f.ab.lauf_lebt() and f.ab.lauf_status()["kette"] is False
    assert f.ab.naechster()["schritt"] == "analyse" and not f.poll.isActive()
    assert f.primaer().text() == "Automatisch weiter ab Analyse"
    f.primaer().click()                       # fragt das Wort und macht weiter
    assert fragen.count(meldungen.OB_KETTE_TITEL) == 2
    _bis_im_fenster(app, lambda: f.in_ruhe() and not f.ab.lauf_lebt(), 300)
    assert f.ab.naechster()["schritt"] == "fertig" and "erledigt" in f.meldung_label.text()
    f.close()


def test_fenster_zu_im_ablauf_verlangt_das_wort_neu(app, tmp_path, quelle, ziel, monkeypatch):
    """Die Bestaetigung lebt nur im Fenster: Nach „Fenster zu“ und neuem Start
    fragt „Los geht's“ wieder nach dem Wort."""
    fragen: list = []
    monkeypatch.setattr(desktop, "frage", _antworten_fuer(fragen))
    ordner = tmp_path / "ob"
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    f.quelle_hinzufuegen(str(quelle))
    f.los(False)
    assert f.ab.lauf_lebt()
    f.close()                                  # mitten im Scan
    titel = [t for t, _ in fragen]
    assert titel == [meldungen.OB_KETTE_TITEL, meldungen.OB_BEENDEN_TITEL]
    assert "automatische Ablauf" in fragen[-1][1]
    assert not f.isVisible() and not f.ab.lauf_lebt()
    _ereignisse(app, 0.2)

    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.show()
    _ereignisse(app, 0.5)
    assert f.ab.lauf_status()["kette"] is False
    f.los(False)                               # noch einmal: das Wort wird wieder verlangt
    titel = [t for t, _ in fragen]
    assert titel[-1] == meldungen.OB_KETTE_TITEL and titel.count(meldungen.OB_KETTE_TITEL) == 2
    _bis_im_fenster(app, lambda: f.in_ruhe() and not f.ab.lauf_lebt(), 300)
    assert f.ab.naechster()["schritt"] == "fertig" and "erledigt" in f.meldung_label.text()
    f.close()
