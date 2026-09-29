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


def _bis_im_fenster(app, bedingung, sekunden: float = 240.0) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        if bedingung():
            return
        time.sleep(0.02)
    raise AssertionError("im Fenster nicht eingetreten")


def test_fenster_zu_neu_auf_und_absturz_im_fenster(app, tmp_path, grosse_quelle, ziel, referenz, nachschauen):
    """Teil 3 im Fenster: Fenster waehrend des Scans schliessen, neu oeffnen (zeigt
    den Lauf), Analyse und Kopieren per Knopf, harter Abschuss mitten im Kopieren
    (Anzeige: unerwartet beendet, Protokoll sichtbar, Knopf zum Weitermachen),
    noch einmal neu oeffnen, "Weitermachen" - am Ende wie der Referenzlauf."""
    ordner = tmp_path / "ob"
    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.show()
    _ereignisse(app, 0.3)
    f.start.ziel_setzen(str(ziel))
    f.quelle_hinzufuegen(str(grosse_quelle))
    f.los(False)
    assert f.ansicht == "haupt" and f.poll.isActive()
    f.close()                                                   # Fenster zu, Scan laeuft weiter
    _ereignisse(app, 0.2)

    f = desktop.Hauptfenster(ablauf_modul.Ablauf(ordner=ordner))
    f.show()
    _ereignisse(app, 0.6)
    assert f.ansicht == "haupt" and "Quellen durchsuchen" in f.haupt.aktuell.text() or f.in_ruhe()
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
    assert len(bilder) == 12 and bilder[0] == "01-startseite-leer.png" and bilder[-1] == "12-dialog-ordner-anlegen.png"
    # Die Bildschirmfotos fuer die Anleitung zeigen das Fenster in voller Groesse.
    bild = QImage(str(fotos / "03-uebersicht-nach-scan.png"))
    assert (bild.width(), bild.height()) == (1180, 800)


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
    assert f.start.karte.kicker.text() == "ARCHIV OHNE MERKLISTE"
    assert f.start.rettung.isVisible() and f.start.rettung.text() == "Datenbank zurückholen…"
    assert not f.start.weitermachen.isVisible()
    antworten.append((False, ""))
    f.rettung()                                            # Rueckfrage -> Nicht jetzt
    assert fragen[-1] == ("Datenbank zurückholen?", "Zurückholen") and not (lokal / "fotosort.db").exists()
    antworten.append((True, ""))
    f.rettung()                                            # -> Zurueckholen
    assert (lokal / "fotosort.db").is_file()
    assert "zurückgeholt" in f.meldung_label.text()
    assert not f.start.rettung.isVisible() and f.start.karte.kicker.text() == "ANGEFANGENES ARCHIV"
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


def test_fehlender_gemerkter_zielordner_ist_kein_neues_archiv(app, tmp_path, monkeypatch):
    """Platte nicht angeschlossen oder Ordner umbenannt: frueher "NEUES ARCHIV"
    und eine Anlegen-Frage ohne Warnung vor einem zweiten, leeren Archiv."""
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    weg = tmp_path / "Archiv auf der USB-Platte"
    f.start.ziel_setzen(str(weg))
    assert f.start.karte.kicker.text() == "ZIELORDNER NICHT GEFUNDEN"
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
