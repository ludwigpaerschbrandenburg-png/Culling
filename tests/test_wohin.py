"""Reiter "Wohin?" - der rechnende Kern (wohin.py, v0.14, ohne Qt).

Zuordnung: jede Datei landet in genau einem Strom (Quellordner -> Archivordner
oder Sammelkasten) mit genau einem Schicksal. Summen: zusammen genau die
Zeilen der Datenbank. Ebenen: hineinklicken links und rechts, "weitere".
Lage: Bandbreiten gleich Knotenhoehen, nichts ueberlappt, feste Reihenfolge.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fotosort import db, wohin


def _datenbank(tmp_path: Path) -> db.Datenbank:
    return db.Datenbank.oeffnen(tmp_path / "archiv")


def _zeile(d: db.Datenbank, quellpfad: Path, wurzel: Path, status: str, zielpfad: Path | str = "",
           schon: int = 0, groesse: int = 100, typ: str = "foto", grund: str = "") -> None:
    d.verbindung.execute(
        "INSERT INTO dateien (quellpfad, quellwurzel, groesse, dateityp, status, zielpfad, schon_im_archiv, fehlergrund)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (db.pfad_text(quellpfad), db.pfad_text(wurzel), groesse, typ, status,
         db.pfad_text(zielpfad) if zielpfad else "", schon, grund))


@pytest.fixture
def beispiel(tmp_path):
    """Zwei Quellen, ein Archiv, jede Statusart einmal - samt Sonderfaellen."""
    ziel = tmp_path / "Archiv"
    karte = tmp_path / "Karte"
    alt = tmp_path / "Alt"
    tag = ziel / "2019" / "2019-03 März" / "2019-03-04" / "A7C"
    d = _datenbank(tmp_path)
    _zeile(d, karte / "DCIM" / "a.jpg", karte, "kopiert", tag / "a.jpg", groesse=10)
    _zeile(d, karte / "DCIM" / "b.jpg", karte, "geprueft", tag / "b.jpg", groesse=20)
    _zeile(d, karte / "DCIM" / "c.jpg", karte, "verschoben", tag / "c.jpg", groesse=30)
    _zeile(d, karte / "DCIM" / "d.jpg", karte, "quelle_geloescht", tag / "d.jpg", groesse=40)
    _zeile(d, karte / "DCIM" / "e.jpg", karte, "analysiert", ziel / "2020.08" / "e.jpg", groesse=50)
    _zeile(d, karte / "DCIM" / "f.jpg", karte, "kopieren_laeuft", ziel / "2020.08" / "f.jpg", groesse=60)
    # Doppelte zeigen auf ihre Partnerdatei - dort liegt ihr Inhalt.
    _zeile(d, karte / "g.jpg", karte, "duplikat", tag / "a.jpg", groesse=10)
    _zeile(d, alt / "Handy" / "h.jpg", alt, "duplikat_bestaetigt", ziel / "Alte Handybilder" / "h.jpg",
           schon=1, groesse=70)
    _zeile(d, alt / "Handy" / "i.jpg", alt, "duplikat", ziel / "Alte Handybilder" / "i.jpg", schon=1, groesse=80)
    _zeile(d, alt / "Handy" / "j.txt", alt, "uebersprungen", typ="sonstiges", groesse=5)
    _zeile(d, alt / "k.jpg", alt, "fehler", ziel / "2019" / "k.jpg", grund="Metadaten nicht lesbar", groesse=6)
    _zeile(d, alt / "l.jpg", alt, "gefunden", groesse=7)
    _zeile(d, alt / "m.jpg", alt, "kopiert", tmp_path / "Woanders" / "2019" / "m.jpg", groesse=8)
    _zeile(d, alt / "n.mov", alt, "kopiert", ziel / "_Ohne_Datum" / "n.mov", groesse=9, typ="video")
    d.verbindung.commit()
    yield d, ziel, karte, alt
    d.schliessen()


def _je(daten: wohin.Daten) -> dict:
    """(Quellkette, Schicksal, Zielkette) -> Anzahl, ueber alle Quellen."""
    erg: dict = {}
    for e in daten.eintraege:
        schluessel = (e.wurzel, e.quelle, e.schicksal, e.ziel)
        erg[schluessel] = erg.get(schluessel, 0) + e.n
    return erg


# ------------------------------------------------------------ Zuordnung ----


def test_jede_statusart_landet_im_richtigen_strom(beispiel):
    d, ziel, karte, alt = beispiel
    daten = wohin.lesen(d, ziel)
    k, a = db.pfad_text(karte), db.pfad_text(alt)
    tag = ("2019", "2019-03 März", "2019-03-04", "A7C")
    assert _je(daten) == {
        (k, ("DCIM",), wohin.KOPIERT, tag): 4,                         # kopiert, geprueft, verschoben, quelle_geloescht
        (k, ("DCIM",), wohin.GEPLANT, ("2020.08",)): 2,                # analysiert, kopieren_laeuft
        (k, (), wohin.DOPPELT, tag): 1,                                # Partner liegt dort
        (a, ("Handy",), wohin.SCHON_DA, ("Alte Handybilder",)): 2,      # schon im Archiv, auch unbestaetigt
        (a, ("Handy",), wohin.BLEIBT, None): 1,
        (a, (), wohin.FEHLER, None): 1,                                # Fehler zaehlt, auch mit geplantem Ziel
        (a, (), wohin.OFFEN, None): 1,
        (a, (), wohin.ANDERSWO, None): 1,                              # Ziel liegt nicht im Archiv
        (a, (), wohin.KOPIERT, ("_Ohne_Datum",)): 1,
    }
    assert daten.ziel == db.pfad_text(ziel)


def test_summen_stimmen_mit_der_datenbank(beispiel):
    d, ziel, _karte, _alt = beispiel
    daten = wohin.lesen(d, ziel)
    zaehler = d.zaehler_je_status()
    assert sum(e.n for e in daten.eintraege) == sum(zaehler.values()) == daten.n == 14
    assert daten.je_schicksal[wohin.KOPIERT] == (zaehler["kopiert"] + zaehler["geprueft"] + zaehler["verschoben"]
                                                  + zaehler["quelle_geloescht"] - 1)   # eine liegt anderswo
    assert daten.je_schicksal[wohin.GEPLANT] == zaehler["analysiert"] + zaehler["kopieren_laeuft"]
    assert daten.je_schicksal[wohin.FEHLER] == zaehler["fehler"]
    assert sum(e.bytes for e in daten.eintraege) == daten.bytes == sum(
        r[0] for r in d.verbindung.execute("SELECT groesse FROM dateien"))
    assert daten.stand == wohin.STAND_SORTIERT


def test_stand_plan_und_leer(tmp_path):
    ziel = tmp_path / "Archiv"
    d = _datenbank(tmp_path)
    try:
        assert wohin.lesen(d, ziel).stand == wohin.STAND_LEER
        _zeile(d, tmp_path / "Q" / "x.jpg", tmp_path / "Q", "gefunden")
        d.verbindung.commit()
        assert wohin.lesen(d, ziel).stand == wohin.STAND_LEER          # noch nichts eingeplant
        _zeile(d, tmp_path / "Q" / "y.jpg", tmp_path / "Q", "analysiert", ziel / "2019" / "y.jpg")
        d.verbindung.commit()
        assert wohin.lesen(d, ziel).stand == wohin.STAND_PLAN
    finally:
        d.schliessen()


# ---------------------------------------------------------------- Ebenen ----


def test_oberste_ebene_quellen_links_jahre_und_kaesten_rechts(beispiel):
    d, ziel, karte, alt = beispiel
    a = wohin.ansicht(wohin.lesen(d, ziel))
    # Quellen heissen nach ihrem Ordner (der ganze Pfad steht im Hinweis).
    assert [k.name for k in a.links] == ["Alt", "Karte"]
    assert [k.schluessel for k in a.links] == [(db.pfad_text(alt),), (db.pfad_text(karte),)]
    assert [k.n for k in a.links] == [7, 7]
    namen = [k.name for k in a.rechts]
    # Echte Ordnernamen in fester Reihenfolge, "_" am Ende; danach die Kaesten.
    assert namen[:4] == ["2019", "2020.08", "Alte Handybilder", "_Ohne_Datum"]
    assert [k.art for k in a.rechts[4:]] == [wohin.BLEIBT, wohin.OFFEN, wohin.FEHLER, wohin.ANDERSWO]
    assert sum(k.n for k in a.links) == sum(k.n for k in a.rechts) == sum(b.n for b in a.baender) == 14
    assert a.rechts[0].tiefer and not a.rechts[1].tiefer and not a.rechts[4].tiefer


def test_gleichnamige_quellen_mit_ganzem_pfad(tmp_path):
    """Zwei Karten mit DCIM: dann steht der ganze Pfad da, sonst der Ordnername.
    Sortiert wird nach dem, was dasteht."""
    ziel = tmp_path / "Archiv"
    d = _datenbank(tmp_path)
    try:
        quellen = (tmp_path / "Karte B" / "DCIM", tmp_path / "Karte A" / "DCIM", tmp_path / "urlaub 2019",
                   tmp_path / "Urlaub 2018")
        for q in quellen:
            _zeile(d, q / "x.jpg", q, "kopiert", ziel / "2019" / f"{q.parent.name}_{q.name}.jpg")
        d.verbindung.commit()
        a = wohin.ansicht(wohin.lesen(d, ziel))
        assert [k.name for k in a.links] == [str(tmp_path / "Karte A" / "DCIM"), str(tmp_path / "Karte B" / "DCIM"),
                                             "Urlaub 2018", "urlaub 2019"]
    finally:
        d.schliessen()


def test_eine_quelle_beginnt_bei_ihren_unterordnern(tmp_path, beispiel):
    """Bei nur einer Quelle stuende links ein einziger Block - aufschlussreicher
    sind gleich ihre Unterordner. Bei mehreren Quellen oder ohne Unterordner
    beginnt die Ansicht oben."""
    d, ziel, karte, alt = beispiel
    assert wohin.start_links(wohin.lesen(d, ziel)) == ()                 # zwei Quellen
    ziel2 = tmp_path / "Archiv2"
    d2 = db.Datenbank.oeffnen(tmp_path / "archiv2")
    try:
        q = tmp_path / "Eine"
        _zeile(d2, q / "Handy" / "a.jpg", q, "kopiert", ziel2 / "2019" / "a.jpg")
        _zeile(d2, q / "Kamera" / "b.jpg", q, "kopiert", ziel2 / "2020" / "b.jpg")
        d2.verbindung.commit()
        daten = wohin.lesen(d2, ziel2)
        assert wohin.start_links(daten) == (db.pfad_text(q),)
        assert [k.name for k in wohin.ansicht(daten, wohin.start_links(daten)).links] == ["Handy", "Kamera"]
        d2.verbindung.execute("DELETE FROM dateien")
        _zeile(d2, q / "c.jpg", q, "kopiert", ziel2 / "2019" / "c.jpg")   # nur direkt in der Quelle
        d2.verbindung.commit()
        assert wohin.start_links(wohin.lesen(d2, ziel2)) == ()
    finally:
        d2.schliessen()


def test_hineinklicken_links_und_rechts(beispiel):
    d, ziel, karte, alt = beispiel
    daten = wohin.lesen(d, ziel)
    links = wohin.ansicht(daten, links=(db.pfad_text(karte),))
    assert [(k.name, k.art, k.n) for k in links.links] == [
        ("DCIM", wohin.ORDNER, 6), (wohin.name_direkt("Karte"), wohin.DIREKT, 1)]
    assert sum(k.n for k in links.rechts) == 7
    rechts = wohin.ansicht(daten, rechts=("2019",))
    # Nur was in 2019 liegt; die Kaesten gehoeren nicht dazu.
    assert [(k.name, k.n) for k in rechts.rechts] == [("2019-03 März", 5)]
    assert sum(k.n for k in rechts.links) == 5
    tiefer = wohin.ansicht(daten, links=(db.pfad_text(karte), "DCIM"), rechts=("2019", "2019-03 März", "2019-03-04"))
    assert [(k.name, k.n) for k in tiefer.links] == [(wohin.name_direkt("DCIM"), 4)]
    assert [(k.name, k.n, k.tiefer) for k in tiefer.rechts] == [("A7C", 4, False)]


def test_weitere_fasst_kleine_ordner_zusammen(tmp_path):
    ziel = tmp_path / "Archiv"
    quelle = tmp_path / "Q"
    d = _datenbank(tmp_path)
    try:
        for i in range(15):
            for j in range(i + 1):
                _zeile(d, quelle / f"Ordner {i:02d}" / f"{j}.jpg", quelle, "kopiert",
                       ziel / str(2000 + i) / f"{i}_{j}.jpg")
        d.verbindung.commit()
        a = wohin.ansicht(wohin.lesen(d, ziel), links=(db.pfad_text(quelle),), max_knoten=10)
        assert len(a.links) == 10 and len(a.rechts) == 10
        assert a.links[-1].art == wohin.WEITERE and len(a.links[-1].mitglieder) == 6
        assert a.links[-1].n == sum(range(1, 7))            # die sechs kleinsten
        assert [k.name for k in a.links[:-1]] == [f"Ordner {i:02d}" for i in range(6, 15)]
        assert a.rechts[-1].art == wohin.WEITERE
        assert sum(k.n for k in a.links) == sum(k.n for k in a.rechts) == sum(b.n for b in a.baender) == 120
    finally:
        d.schliessen()


# ------------------------------------------------------------------ Lage ----


def _pruefen_lage(a: wohin.Ansicht, lage: wohin.Lage, hoehe: float) -> None:
    for seite, knoten in (("links", lage.links), ("rechts", lage.rechts)):
        letzte_unterkante = -1.0
        for i, k in enumerate(knoten):
            assert k.y >= 0 and k.y + k.h <= hoehe + 1e-6, (seite, i)
            assert k.y >= letzte_unterkante - 1e-6, (seite, i)   # keine Ueberlappung
            letzte_unterkante = k.y + k.h
            # Die Baender fuellen den Knoten genau, lueckenlos und ohne Ueberlappung.
            enden = sorted((b.y0o, b.y0u) if seite == "links" else (b.y1o, b.y1u)
                           for b, band in zip(lage.baender, a.baender)
                           if (band.links if seite == "links" else band.rechts) == i)
            assert enden[0][0] == pytest.approx(k.y) and enden[-1][1] == pytest.approx(k.y + k.h)
            for (o1, u1), (o2, _u2) in zip(enden, enden[1:]):
                assert u1 == pytest.approx(o2)
    for b, band in zip(lage.baender, a.baender):
        dicke_l, dicke_r = b.y0u - b.y0o, b.y1u - b.y1o
        assert dicke_l == pytest.approx(dicke_r) and dicke_l >= wohin.MIN_BAND - 1e-9
        assert dicke_l == pytest.approx(max(band.n * lage.massstab, wohin.MIN_BAND))


def test_lage_baender_fuellen_die_knoten_genau(beispiel):
    d, ziel, _karte, _alt = beispiel
    a = wohin.ansicht(wohin.lesen(d, ziel))
    lage = wohin.lage(a, breite=900, hoehe=400, x_links=180, x_rechts=700)
    _pruefen_lage(a, lage, 400)
    # Kleine Knoten bekommen Platz fuer ihre Beschriftung: Mitten liegen mindestens eine Zeile auseinander.
    for knoten in (lage.links, lage.rechts):
        mitten = [k.mitte for k in knoten]
        assert all(b - a_ >= wohin.ZEILE - 1e-6 for a_, b in zip(mitten, mitten[1:]))
    assert all(k.x == 180 - wohin.KNOTEN_BREITE for k in lage.links) and all(k.x == 700 for k in lage.rechts)


def test_lage_mit_sehr_ungleichen_mengen_und_feste_reihenfolge(tmp_path):
    """1 Datei neben 100 000: Das kleine Band bleibt sichtbar (mindestens
    MIN_BAND), die Summen stimmen trotzdem, und zweimal gerechnet ist gleich."""
    ziel = tmp_path / "Archiv"
    q = tmp_path / "Q"
    d = _datenbank(tmp_path)
    try:
        d.verbindung.execute("BEGIN")          # eine Transaktion, sonst schreibt SQLite jede Zeile einzeln fest
        d.verbindung.executemany(
            "INSERT INTO dateien (quellpfad, quellwurzel, groesse, dateityp, status, zielpfad) VALUES (?, ?, 1, 'foto', ?, ?)",
            [(db.pfad_text(q / "gross" / f"{i}.jpg"), db.pfad_text(q), "kopiert", db.pfad_text(ziel / "2019" / f"{i}.jpg"))
             for i in range(100_000)]
            + [(db.pfad_text(q / "klein" / "1.jpg"), db.pfad_text(q), "duplikat", db.pfad_text(ziel / "2020" / "1.jpg")),
               (db.pfad_text(q / "klein" / "2.jpg"), db.pfad_text(q), "fehler", "")])
        d.verbindung.execute("COMMIT")
        a = wohin.ansicht(wohin.lesen(d, ziel), links=(db.pfad_text(q),))
        lage = wohin.lage(a, breite=800, hoehe=300, x_links=150, x_rechts=650)
        _pruefen_lage(a, lage, 300)
        assert lage == wohin.lage(a, breite=800, hoehe=300, x_links=150, x_rechts=650)
    finally:
        d.schliessen()


def test_band_unter_dem_zeiger(beispiel):
    """An den Knoten liegen die Baender nebeneinander - dort trifft der Zeiger
    genau eines. In der Mitte kreuzen sie sich; dann gilt das obenauf
    gezeichnete (das spaetere)."""
    d, ziel, _karte, _alt = beispiel
    a = wohin.ansicht(wohin.lesen(d, ziel))
    lage = wohin.lage(a, breite=900, hoehe=400, x_links=180, x_rechts=700)
    for i, b in enumerate(lage.baender):
        for x in (b.x0 + 0.5, b.x1 - 0.5):
            oben, unten = wohin.band_kanten(b, x)
            assert oben < unten and wohin.band_bei(lage, x, (oben + unten) / 2) == i
        x = (b.x0 + b.x1) / 2
        oben, unten = wohin.band_kanten(b, x)
        treffer = wohin.band_bei(lage, x, (oben + unten) / 2)
        assert treffer is not None and treffer >= i
    assert wohin.band_bei(lage, 10, 10) is None                         # links neben der Grafik
    assert wohin.band_bei(lage, 450, 10_000) is None                    # unter allem


# ----------------------------------------------------------------- Tempo ----


def test_eine_million_zeilen_in_wenigen_sekunden(tmp_path):
    ziel = tmp_path / "Archiv"
    d = _datenbank(tmp_path)
    try:
        sep = os.sep
        q = str(tmp_path / "Quelle")
        z = str(ziel)
        stati = ("kopiert", "geprueft", "duplikat", "analysiert", "fehler", "uebersprungen")
        zeilen = ((f"{q}{sep}Ordner {i % 500}{sep}Unter {i % 7}{sep}IMG_{i:07d}.JPG", q, 2_000_000 + i,
                   stati[i % 6], "" if i % 6 >= 4 else
                   f"{z}{sep}{2000 + i % 25}{sep}{2000 + i % 25}-{1 + i % 12:02d}{sep}Tag {i % 28}{sep}IMG_{i:07d}.JPG")
                  for i in range(1_000_000))
        # Nur fuer den Aufbau: Ohne die Indizes ist die Tabelle in Sekunden gefuellt.
        # Gelesen wird ohnehin die ganze Tabelle, die Indizes spielen dafuer keine Rolle.
        for (name,) in d.verbindung.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'dateien' AND sql IS NOT NULL").fetchall():
            d.verbindung.execute(f"DROP INDEX {name}")
        d.verbindung.execute("BEGIN")
        d.verbindung.executemany(
            "INSERT INTO dateien (quellpfad, quellwurzel, groesse, dateityp, status, zielpfad)"
            " VALUES (?, ?, ?, 'foto', ?, ?)", zeilen)
        d.verbindung.execute("COMMIT")
        beginn = time.monotonic()
        daten = wohin.lesen(d, ziel)
        a = wohin.ansicht(daten)
        wohin.lage(a, breite=1000, hoehe=500, x_links=200, x_rechts=800)
        dauer = time.monotonic() - beginn
        print(f"1 000 000 Zeilen gelesen und angeordnet in {dauer:.2f} s ({len(daten.eintraege)} Stroeme)")
        assert daten.n == 1_000_000 and sum(k.n for k in a.links) == 1_000_000
        assert dauer < 20, dauer
        # Hineinklicken rechnet nur noch auf den zusammengefassten Stroemen.
        beginn = time.monotonic()
        wohin.ansicht(daten, links=(q,), rechts=("2003",))
        assert time.monotonic() - beginn < 1.0
    finally:
        d.schliessen()


def test_entferntes_duplikat_bleibt_doppelt(tmp_path):
    """Nach dem Aufraeumen stehen Original und Duplikat auf quelle_geloescht;
    war_duplikat (seit v0.14) haelt fest, welches das Duplikat war."""
    ziel = tmp_path / "Archiv"
    q = tmp_path / "Q"
    d = _datenbank(tmp_path)
    try:
        _zeile(d, q / "a.jpg", q, "quelle_geloescht", ziel / "2019" / "a.jpg")
        _zeile(d, q / "b.jpg", q, "quelle_geloescht", ziel / "2019" / "a.jpg")
        d.verbindung.execute("UPDATE dateien SET war_duplikat = 1 WHERE quellpfad = ?", (db.pfad_text(q / "b.jpg"),))
        d.verbindung.commit()
        daten = wohin.lesen(d, ziel)
        assert daten.je_schicksal == {wohin.KOPIERT: 1, wohin.DOPPELT: 1}
    finally:
        d.schliessen()


# ------------------------------------------------ Dateien eines Bandes ----


def test_dateien_eines_bandes_passen_genau_zum_band(beispiel):
    """Klick auf ein Band listet seine Dateien: genau so viele, wie das Band
    zaehlt, jede mit seinem Schicksal - oben, links hineingeklickt und rechts."""
    d, ziel, karte, _alt = beispiel
    daten = wohin.lesen(d, ziel)
    for a in (wohin.ansicht(daten), wohin.ansicht(daten, links=(db.pfad_text(karte),)),
              wohin.ansicht(daten, rechts=("2019",)), wohin.ansicht(daten, links=(db.pfad_text(karte), "DCIM"))):
        for i, b in enumerate(a.baender):
            dateien, gesamt = wohin.band_dateien(d, ziel, a, i)
            assert gesamt == b.n == len(dateien), (a.pfad_links, a.pfad_rechts, b)
            assert {x.schicksal for x in dateien} == {b.schicksal}
            assert sum(x.groesse for x in dateien) == b.bytes


def test_dateien_eines_bandes_mit_weitere_und_grenze(tmp_path):
    ziel = tmp_path / "Archiv"
    q = tmp_path / "Q"
    d = _datenbank(tmp_path)
    try:
        for i in range(15):
            for j in range(i + 1):
                _zeile(d, q / f"Ordner {i:02d}" / f"{j}.jpg", q, "kopiert", ziel / "2019" / f"{i}_{j}.jpg")
        d.verbindung.commit()
        a = wohin.ansicht(wohin.lesen(d, ziel), links=(db.pfad_text(q),))
        weitere = next(i for i, b in enumerate(a.baender) if a.links[b.links].art == wohin.WEITERE)
        dateien, gesamt = wohin.band_dateien(d, ziel, a, weitere, grenze=5)
        assert gesamt == 21 and len(dateien) == 5
    finally:
        d.schliessen()


def test_datei_suchen(beispiel):
    d, ziel, karte, _alt = beispiel
    treffer, gesamt = wohin.suchen(d, ziel, "a.jpg")
    assert gesamt == len(treffer) == 1
    (t,) = treffer
    assert Path(t.quelle) == karte / "DCIM" / "a.jpg" and t.schicksal == wohin.KOPIERT
    assert Path(t.ziel).parts[-5:] == ("2019", "2019-03 März", "2019-03-04", "A7C", "a.jpg")
    treffer, gesamt = wohin.suchen(d, ziel, "K.JPG")               # Gross/Klein egal
    assert gesamt == 1 and treffer[0].schicksal == wohin.FEHLER and treffer[0].grund == "Metadaten nicht lesbar"
    assert wohin.suchen(d, ziel, "gibtsnicht") == ([], 0)
    assert wohin.suchen(d, ziel, "%") == ([], 0)                    # Platzhalter gelten als Zeichen
