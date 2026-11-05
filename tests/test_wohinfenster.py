"""Reiter „Wohin?“ im Fenster (v0.14): Grafik, Bedienung, Balken in der
Uebersicht - offscreen, am kuenstlichen Testbaum (SPEC §11)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fotosort import cli, db, meldungen, wohin  # noqa: E402
from fotosort.oberflaeche import ablauf as ablauf_modul  # noqa: E402
from fotosort.oberflaeche import desktop, wohinfenster  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _ereignisse(app, sekunden: float = 0.2) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        time.sleep(0.02)


def _bis(app, bedingung, sekunden: float = 120.0) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        app.processEvents()
        if bedingung():
            return
        time.sleep(0.02)
    raise AssertionError("im Fenster nicht eingetreten")


def _schritte(quelle: Path, ziel: Path, *befehle: str) -> None:
    for befehl in befehle:
        args = [befehl, "--ziel", str(ziel)] + (["--quelle", str(quelle)] if befehl == "scan" else [])
        assert cli.main(args) == cli.OK, befehl


def _fenster(app, tmp_path: Path, ziel: Path) -> desktop.Hauptfenster:
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    ab.einstellungen_setzen(automatisch=False)
    f = desktop.Hauptfenster(ab)
    f.resize(1280, 900)
    f.show()
    _ereignisse(app)
    f.start.ziel_setzen(str(ziel))
    f.weitermachen()
    _ereignisse(app)
    return f


def _zeilen_der_datenbank(f: desktop.Hauptfenster) -> int:
    return sum((f.ab.zustand().get("archiv") or {}).get("zaehler", {}).values())


def _knoten_punkt(g: wohinfenster.FlussGrafik, seite: str, i: int) -> QPoint:
    lage = g.lage_holen()
    k = (lage.links if seite == "links" else lage.rechts)[i]
    return QPoint(round(k.x + k.b / 2), round(g.RAND + k.mitte))


def _zeiger(g: wohinfenster.FlussGrafik, punkt: QPoint) -> None:
    """Den Zeiger ueber die Grafik bewegen - als Ereignis direkt an das Widget.
    (QTest.mouseMove liefert nichts, wenn der Zeiger aus einem frueheren Test
    schon genau dort steht.)"""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    ort = QPointF(punkt)
    ereignis = QMouseEvent(QEvent.Type.MouseMove, ort, QPointF(g.mapToGlobal(punkt)), Qt.MouseButton.NoButton,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(g, ereignis)


def _band_punkt(g: wohinfenster.FlussGrafik, i: int) -> QPoint:
    b = g.lage_holen().baender[i]
    x = (b.x0 + b.x1) / 2
    oben, unten = wohin.band_kanten(b, x)
    return QPoint(round(x), round(g.RAND + (oben + unten) / 2))


# ------------------------------------------------------- Stand und Zahlen ----


def test_reiter_zeigt_den_plan_und_danach_das_ergebnis(app, tmp_path, quelle, ziel):
    _schritte(quelle, ziel, "scan", "analyse")
    f = _fenster(app, tmp_path, ziel)
    assert [k.text() for k in f.reiter.knoepfe.values()] == ["Archiv", "Wohin?", "Sichten"]
    f.reiter_wechseln("wohin")
    w = f.wohin
    assert f.reiter_stapel.currentWidget() is w and f.reiter_jetzt() == "wohin"
    assert w.stand.text() == meldungen.WOHIN_STAND["plan"]
    a = w.ansicht
    ins_archiv = {b.schicksal for b in a.baender if b.schicksal in wohin.INS_ARCHIV}
    assert ins_archiv == {wohin.GEPLANT}                       # noch nichts kopiert
    # Summen: Grafik, Tabelle und Kennzahlen zaehlen jede Zeile der Datenbank genau einmal.
    gesamt = _zeilen_der_datenbank(f)
    assert sum(b.n for b in a.baender) == sum(k.n for k in a.links) == sum(k.n for k in a.rechts) == gesamt
    assert w.kachel["gesamt"].text() == meldungen.anzahl(gesamt)
    assert w.kachel["geplant"].text() == meldungen.anzahl(w.daten.je_schicksal[wohin.GEPLANT])
    assert w.kachel_rahmen["geplant"].isVisibleTo(w)
    assert w.tabelle.rowCount() == len(a.baender)
    assert sum(w.tabelle.item(z, 3).wert for z in range(w.tabelle.rowCount())) == gesamt
    # Die Quelle heisst nach ihrem Ordner; der ganze Pfad steht im Hinweis.
    assert a.links[0].name == quelle.name
    assert str(quelle) in w.grafik.tipp_text(("links", 0))

    _schritte(quelle, ziel, "kopieren")
    f.weitermachen()                                          # wie nach einem Schritt im Fenster
    _ereignisse(app)
    assert f.reiter_jetzt() == "wohin"
    assert w.stand.text() == meldungen.WOHIN_STAND["sortiert"]
    je = w.daten.je_schicksal
    assert je.get(wohin.GEPLANT, 0) == 0 and je[wohin.KOPIERT] > 0 and je[wohin.DOPPELT] > 0
    assert w.kachel["kopiert"].text() == meldungen.anzahl(je[wohin.KOPIERT])
    assert w.kachel["doppelt"].text() == meldungen.anzahl(je[wohin.DOPPELT])
    assert not w.kachel_rahmen["geplant"].isVisibleTo(w)
    assert sum(b.n for b in w.ansicht.baender) == _zeilen_der_datenbank(f)
    f.close()


def test_ohne_archiv_sagt_der_reiter_was_zu_tun_ist(app, tmp_path):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    f = desktop.Hauptfenster(ab)
    f.show()
    _ereignisse(app)
    f.reiter_wechseln("wohin")
    assert f.wohin.daten is None and f.wohin.ansicht is None
    assert f.wohin.grafik.leer_text == meldungen.WOHIN_KEIN_ARCHIV
    assert f.wohin.tabelle.rowCount() == 0 and not f.haupt.wohin.isVisibleTo(f)
    f.close()


# ------------------------------------------------------------- Bedienen ----


def test_hineinklicken_und_pfadleiste(app, tmp_path, quelle, ziel):
    _schritte(quelle, ziel, "scan", "analyse", "kopieren")
    f = _fenster(app, tmp_path, ziel)
    f.reiter_wechseln("wohin")
    w, g = f.wohin, f.wohin.grafik
    rechts = [k.name for k in w.ansicht.rechts]
    i = rechts.index("2026")
    assert w.ansicht.rechts[i].tiefer
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _knoten_punkt(g, "rechts", i))
    assert w.rechts == ("2026",)
    # Rechts nur noch, was in 2026 liegt: Monatsordner, keine Kaesten.
    assert w.ansicht.rechts and all(k.name.startswith("2026") for k in w.ansicht.rechts)
    assert not any(k.art in wohin.KAESTEN for k in w.ansicht.rechts)
    assert "2026" in w.pfad_rechts.text() and meldungen.WOHIN_ARCHIV in w.pfad_rechts.text()
    # Links hinein: die Unterordner der Quelle.
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _knoten_punkt(g, "links", 0))
    assert w.links == (db.pfad_text(quelle),)
    assert {"2026", "Urlaub 2026 Ümläute"} <= {k.name for k in w.ansicht.links}
    assert quelle.name in w.pfad_links.text()
    # Ein Kasten laesst sich nicht oeffnen.
    w.pfad_klick("rechts", 0)
    kasten = next(j for j, k in enumerate(w.ansicht.rechts) if k.art == wohin.BLEIBT)
    vorher = (w.links, w.rechts)
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _knoten_punkt(g, "rechts", kasten))
    assert (w.links, w.rechts) == vorher
    # Die Pfadleiste fuehrt zurueck (Klick auf den Verweis).
    w.pfad_links.linkActivated.emit("0")
    assert w.links == () and w.ansicht.links[0].name == quelle.name
    f.close()


def test_band_waehlen_zeigt_seine_dateien(app, tmp_path, quelle, ziel, monkeypatch):
    _schritte(quelle, ziel, "scan", "analyse", "kopieren")
    f = _fenster(app, tmp_path, ziel)
    f.reiter_wechseln("wohin")
    w, g = f.wohin, f.wohin.grafik
    w.knoten_klick("rechts", next(i for i, k in enumerate(w.ansicht.rechts) if k.name == "2026"))
    a = w.ansicht
    i = max((j for j, b in enumerate(a.baender) if b.schicksal == wohin.KOPIERT), key=lambda j: a.baender[j].n)
    band = a.baender[i]
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _band_punkt(g, i))
    assert w.band == i and g.gewaehlt == i and w.band_karte.isVisibleTo(w)
    t = w.band_tabelle
    assert t.rowCount() == band.n
    assert {t.item(z, 3).text() for z in range(t.rowCount())} == {meldungen.WOHIN_SCHICKSAL[wohin.KOPIERT]}
    # Jede gezeigte Datei liegt wirklich dort im Archiv.
    for x in w.band_liste:
        assert Path(x.ziel).is_file() and Path(x.ziel).is_relative_to(ziel / a.rechts[band.rechts].schluessel[0])
    # Die Tabelle darunter zeigt dasselbe Band.
    gewaehlt = w.tabelle.selectionModel().selectedRows()
    assert len(gewaehlt) == 1 and w.tabelle.item(gewaehlt[0].row(), 0).data(Qt.ItemDataRole.UserRole) == i
    # Ordner oeffnen: der Archivordner hinter dem Band.
    geoeffnet: list[Path] = []
    monkeypatch.setattr(wohinfenster, "ordner_oeffnen", geoeffnet.append)
    w.k_archiv.click()
    assert geoeffnet == [ziel.joinpath(*a.rechts[band.rechts].schluessel)] and geoeffnet[0].is_dir()
    w.k_quelle.click()
    assert geoeffnet[-1] == quelle
    # Auswahl aufheben.
    w.k_weg.click()
    assert w.band is None and g.gewaehlt is None and not w.band_karte.isVisibleTo(w)
    # Eine Zeile der Tabelle waehlen = dasselbe wie ein Klick aufs Band.
    zeile = next(z for z in range(w.tabelle.rowCount()) if w.tabelle.item(z, 0).data(Qt.ItemDataRole.UserRole) == i)
    w.tabelle.selectRow(zeile)
    assert w.band == i and w.band_karte.isVisibleTo(w)
    # In Sichten zeigen: Reiter „Sichten“ mit genau diesem Ordner.
    w.k_sichten.click()
    _ereignisse(app)
    assert f.reiter_jetzt() == "sichten"
    assert f.sichten.ordner_jetzt == ziel.joinpath(*a.rechts[band.rechts].schluessel)
    f.close()


def test_datei_suchen(app, tmp_path, quelle, ziel):
    _schritte(quelle, ziel, "scan", "analyse", "kopieren")
    f = _fenster(app, tmp_path, ziel)
    f.reiter_wechseln("wohin")
    w = f.wohin
    QTest.keyClicks(w.suche, "urlaub")
    QTest.keyClick(w.suche, Qt.Key.Key_Return)
    assert w.treffer.isVisibleTo(w)
    namen = {w.treffer.item(z, 0).text() for z in range(w.treffer.rowCount())}
    assert "2026-01-01 Urlaub.jpg" in namen
    treffer = next(x for x in w.treffer_liste if Path(x.quelle).name == "2026-01-01 Urlaub.jpg")
    assert treffer.schicksal == wohin.KOPIERT and Path(treffer.ziel).is_file()
    assert w.treffer_info.text() == meldungen.wohin_treffer(len(w.treffer_liste), len(w.treffer_liste))
    w.suche.setText("gibt_es_nicht_xyz")
    w.suchen(w.suche.text())
    assert w.treffer_info.text() == "Keine Datei gefunden." and not w.treffer.isVisibleTo(w)
    f.close()


def test_hinweis_unter_dem_zeiger(app, tmp_path, quelle, ziel):
    _schritte(quelle, ziel, "scan", "analyse", "kopieren")
    f = _fenster(app, tmp_path, ziel)
    f.reiter_wechseln("wohin")
    g = f.wohin.grafik
    a = f.wohin.ansicht
    i = next(j for j, b in enumerate(a.baender) if b.schicksal == wohin.KOPIERT)
    _zeiger(g, _band_punkt(g, i))
    assert g.ueber == ("band", i)
    b = a.baender[i]
    text = g.tipp_text(("band", i))
    assert text.startswith(meldungen.n_dateien(b.n) + " · ")     # der Wert zuerst
    assert a.links[b.links].name in text and a.rechts[b.rechts].name in text
    assert meldungen.WOHIN_SCHICKSAL[wohin.KOPIERT] in text
    # Ein ganzer Knoten hebt seine Baender hervor.
    _zeiger(g, _knoten_punkt(g, "links", 0))
    assert g.ueber == ("links", 0) and g._hervorgehoben() == {j for j, b in enumerate(a.baender) if b.links == 0}
    f.close()


# ------------------------------------------------- Balken in der Uebersicht ----


def test_balken_in_der_uebersicht(app, tmp_path, quelle, ziel):
    _schritte(quelle, ziel, "scan", "analyse", "kopieren")
    f = _fenster(app, tmp_path, ziel)
    balken = f.haupt.wohin
    assert f.reiter_jetzt() == "archiv" and balken.isVisibleTo(f)
    assert sum(n for _s, n in balken.zeilen) == _zeilen_der_datenbank(f)
    assert [s for s, _n in balken.zeilen] == [s for s in wohin.SCHICKSALE if dict(balken.zeilen).get(s)]
    # Waehrend eines Schritts steht kein veralteter Balken da; danach der neue.
    f.schritt_starten("pruefen")
    assert not balken.isVisibleTo(f) and f.wohin.laeuft.isVisibleTo(f.wohin)
    _bis(app, lambda: f.in_ruhe() and not f.ab.lauf_lebt())
    assert balken.isVisibleTo(f)
    # „Genauer“ fuehrt zum Reiter „Wohin?“.
    balken.knopf.click()
    assert f.reiter_jetzt() == "wohin" and not f.wohin.laeuft.isVisibleTo(f.wohin)
    f.close()


def test_waehrend_eines_schritts_liest_der_reiter_nichts(app, tmp_path, quelle, ziel, monkeypatch):
    """Die Datenbank gehoert dem laufenden Schritt: der Reiter zeigt den letzten
    Stand mit Hinweis und liest nicht."""
    _schritte(quelle, ziel, "scan", "analyse", "kopieren")
    f = _fenster(app, tmp_path, ziel)
    f.reiter_wechseln("wohin")
    w = f.wohin
    vorher = w.daten
    gelesen: list[int] = []
    echt = wohin.lesen
    monkeypatch.setattr(wohin, "lesen", lambda *a, **k: gelesen.append(1) or echt(*a, **k))
    monkeypatch.setattr(f.ab, "lauf_lebt", lambda: True)
    f.ab._wohin_gemerkt = None                         # auch ohne Zwischenspeicher nicht lesen
    w.aktualisieren()
    assert gelesen == [] and w.daten is vorher and w.laeuft.isVisibleTo(w)
    assert w.ansicht is not None and w.ansicht.baender                # der letzte Stand bleibt stehen
    monkeypatch.setattr(f.ab, "lauf_lebt", lambda: False)
    w.aktualisieren()
    assert gelesen == [1] and not w.laeuft.isVisibleTo(w)
    f.close()


# ------------------------------------------------------ Zeichnen und Farben ----


def _daten(eintraege: list[wohin.Eintrag], ziel: str = "/Archiv") -> wohin.Daten:
    je: dict[str, int] = {}
    for e in eintraege:
        je[e.schicksal] = je.get(e.schicksal, 0) + e.n
    return wohin.Daten(ziel=ziel, eintraege=eintraege, n=sum(je.values()),
                       bytes=sum(e.bytes for e in eintraege), je_schicksal=je, stand=wohin.STAND_SORTIERT)


def test_farben_aus_der_geprueften_palette():
    """Die Farben sind gegen hell (#ffffff) und dunkel (#1a1a19/#2b2b2b) mit dem
    Pruefskript geprueft (v0.14) - hier festgehalten, damit niemand sie
    nebenbei aendert. Rot nur fuer Fehler, Gelb nur fuer „anderswo“."""
    hell, dunkel = wohinfenster.FARBEN["hell"], wohinfenster.FARBEN["dunkel"]
    assert (hell[wohin.KOPIERT], hell[wohin.DOPPELT], hell[wohin.SCHON_DA]) == ("#2a78d6", "#eb6834", "#1baf7a")
    assert (dunkel[wohin.KOPIERT], dunkel[wohin.DOPPELT], dunkel[wohin.SCHON_DA]) == ("#3987e5", "#d95926", "#199e70")
    for farben in (hell, dunkel):
        assert farben[wohin.GEPLANT] == farben[wohin.KOPIERT]           # derselbe Ton, als Schleier
        assert farben[wohin.FEHLER] == "#d03b3b" and farben[wohin.ANDERSWO] == "#fab219"
        assert set(farben) >= set(wohin.SCHICKSALE)
    assert wohinfenster.ZEICHEN[wohin.FEHLER] and wohinfenster.ZEICHEN[wohin.ANDERSWO]   # nie Farbe allein


@pytest.mark.parametrize("modus", ["hell", "dunkel"])
def test_baender_tragen_ihre_farbe(app, modus):
    eintraege = [wohin.Eintrag("/Q", ("A",), wohin.KOPIERT, ("2019",), 60, 600),
                 wohin.Eintrag("/Q", ("A",), wohin.DOPPELT, ("2019",), 30, 300),
                 wohin.Eintrag("/Q", ("B",), wohin.SCHON_DA, ("2020",), 30, 300),
                 wohin.Eintrag("/Q", ("B",), wohin.FEHLER, None, 5, 50)]
    g = wohinfenster.FlussGrafik()
    pal = QPalette(g.palette())
    grund = QColor("#ffffff" if modus == "hell" else "#1a1a19")
    pal.setColor(QPalette.ColorRole.Base, grund)
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#000000" if modus == "hell" else "#ffffff"))
    g.setPalette(pal)
    g.setzen(wohin.ansicht(_daten(eintraege), links=("/Q",)))
    g.resize(900, g.height())
    bild = g.grab().toImage()
    assert wohinfenster.dunkel(g.palette()) == (modus == "dunkel")
    geprueft = 0
    for i, b in enumerate(g.ansicht.baender):
        if b.schicksal not in (wohin.KOPIERT, wohin.DOPPELT, wohin.SCHON_DA):
            continue
        p = _band_punkt(g, i)
        ist = bild.pixelColor(p.x(), p.y())
        c = QColor(wohinfenster.FARBEN[modus][b.schicksal])
        a = wohinfenster.DECKKRAFT[0]
        soll = [round(getattr(c, k)() * a + getattr(grund, k)() * (1 - a)) for k in ("red", "green", "blue")]
        assert all(abs(x - y) <= 3 for x, y in zip((ist.red(), ist.green(), ist.blue()), soll)), (b.schicksal, ist.name())
        geprueft += 1
    assert geprueft == 3
    # Das gewaehlte Band tritt hervor, die anderen zurueck.
    g.waehlen(0)
    bild2 = g.grab().toImage()
    p0, p1 = _band_punkt(g, 0), _band_punkt(g, 1)
    abstand = lambda f1, f2: sum(abs(x - y) for x, y in zip(f1.getRgb()[:3], f2.getRgb()[:3]))  # noqa: E731
    assert abstand(bild2.pixelColor(p0), grund) > abstand(bild.pixelColor(p0), grund)
    assert abstand(bild2.pixelColor(p1), grund) < abstand(bild.pixelColor(p1), grund)


def test_kurze_namen_bleiben_ganz(app):
    """Passt ein Name in seine Spalte, steht er ganz da - frueher wurde „Quelle“
    zu „Q…e“, weil die Spalte auf den Pixel genau so breit war wie der Text."""
    eintraege = [wohin.Eintrag("/x/Quelle", ("A",), wohin.KOPIERT, ("2026", "2026-01 Januar"), 15, 100),
                 wohin.Eintrag("/x/Quelle", ("A",), wohin.DOPPELT, ("2026", "2026-02 Februar"), 5, 100),
                 wohin.Eintrag("/x/Karte", ("B",), wohin.KOPIERT, ("2026", "2026-12 Dezember"), 1, 100)]
    g = wohinfenster.FlussGrafik()
    g.setzen(wohin.ansicht(_daten(eintraege), rechts=("2026",)))
    for breite in (700, 900, 1168, 1600):
        g.resize(breite, g.height())
        g.lage_holen()
        for seite, knoten in (("links", g.ansicht.links), ("rechts", g.ansicht.rechts)):
            for k in knoten:
                gezeigt, _zahl = g.text_fuer(k, seite)
                assert gezeigt == g.beschriftung(k)[0], (breite, gezeigt)


def test_lange_namen_werden_gekuerzt_nicht_abgeschnitten(app):
    lang = "Ein sehr langer Ordnername " * 6
    eintraege = [wohin.Eintrag("/Q", (lang + "Ende",), wohin.KOPIERT, ("2019",), 10, 100)]
    g = wohinfenster.FlussGrafik()
    g.setzen(wohin.ansicht(_daten(eintraege), links=("/Q",)))
    g.resize(700, g.height())
    g.lage_holen()
    assert g.spalte_links <= 700 * 0.30 + 1
    # Was gezeichnet wird, passt in die Spalte (Mitte gekuerzt, Anfang und Ende bleiben).
    name, _zahl = g.beschriftung(g.ansicht.links[0])
    gekuerzt, _zahl = g.text_fuer(g.ansicht.links[0], "links")
    assert gekuerzt != name and gekuerzt.startswith("Ein") and gekuerzt.endswith("Ende") and "…" in gekuerzt
    g.grab()                                                # zeichnet ohne Fehler


def test_viele_ordner_bleiben_schnell(app):
    """10.000 Stroeme aus 300 Quellordnern in 120 Archivordner: hoechstens zehn
    Knoten je Seite, Zeichnen und Zeigen bleiben flott."""
    eintraege = [wohin.Eintrag("/Q", (f"Ordner {i:03d}",), wohin.KOPIERT if j % 5 else wohin.DOPPELT,
                               (str(1990 + j % 30), f"{1990 + j % 30}-{(i + j) % 12 + 1:02d}"), 1 + (i * j) % 17, 1000)
                 for i in range(300) for j in range(34)]
    daten = _daten(eintraege)
    beginn = time.perf_counter()
    a = wohin.ansicht(daten, links=("/Q",))
    g = wohinfenster.FlussGrafik()
    g.setzen(a)
    g.resize(1100, g.height())
    g.grab()
    for x in range(200, 900, 7):
        g.treffer(x, g.height() / 2)
    dauer = time.perf_counter() - beginn
    assert len(a.links) <= wohin.MAX_KNOTEN and len(a.rechts) <= wohin.MAX_KNOTEN
    assert a.links[-1].art == wohin.WEITERE
    assert sum(b.n for b in a.baender) == daten.n
    assert dauer < 3.0, dauer
