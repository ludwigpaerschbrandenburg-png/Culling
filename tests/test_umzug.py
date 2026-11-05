"""Archiv an einem neuen Ort (v0.14, Pruefung Fehler 1).

Unter Windows bekommt eine USB-Platte beim naechsten Einstecken oft einen
anderen Laufwerksbuchstaben (E: -> F:). Die Datenbank speichert die
Archivpfade absolut. Bisher hielten "Pruefen" und "Aufraeumen" danach alle
Kopien fuer fehlend, und ein neuer Lauf hielt die eigenen Kopien fuer "schon im
Archiv" - die Originale wurden nie aufgeraeumt. Ein schon geplantes Kopieren
schrieb sogar an den alten Pfad.

Hier wird der neue Buchstabe nachgestellt, indem der ganze Archivordner
umbenannt wird - fuer das Programm ist das dasselbe.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
from pathlib import Path

from fotosort import cli, db, pfade, umzug
from test_aufraeumen import antwort  # noqa: F401  (Vorrichtung)
from test_kopieren import _cli, _vorbereiten, _zeilen, _zieldateien


def _bis_geprueft(quelle: Path, ziel: Path) -> None:
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK


def _alle_archivpfade(nachschauen, ziel: Path) -> list[str]:
    """Jeder gespeicherte Pfad ins Archiv, aus allen Tabellen."""
    with nachschauen(ziel) as d:
        v = d.verbindung
        pfade_ = [r[0] for r in v.execute("SELECT zielpfad FROM dateien WHERE zielpfad != ''")]
        pfade_ += [r[0] for r in v.execute("SELECT schreibpfad FROM dateien WHERE schreibpfad != ''")]
        pfade_ += [r[0] for r in v.execute("SELECT zielpfad FROM abgelegt")]
        pfade_ += [r[0] for r in v.execute("SELECT zielpfad FROM ziel_index")]
    return pfade_


def _unter(text: str, wurzel: Path) -> bool:
    return db.text_pfad(text).startswith(str(wurzel) + os.sep)


def _archiv_ordner(nachschauen, ziel: Path) -> Path:
    with nachschauen(ziel) as d:
        return Path(d.pfad).parent


# ------------------------------------------------------- Grundablauf ----


def test_neuer_laufwerksbuchstabe_pfade_werden_umgeschrieben(quelle, tmp_path, nachschauen, capsys, antwort):  # noqa: F811
    alt = tmp_path / "E" / "Archiv"
    alt.mkdir(parents=True)
    _bis_geprueft(quelle, alt)
    alt = pfade.aufloesen(alt)
    vorher = _zeilen(nachschauen, alt)
    geprueft = {p for p, z in vorher.items() if z["status"] == "geprueft"}
    assert geprueft
    assert all(_unter(t, alt) for t in _alle_archivpfade(nachschauen, alt))
    inhalt = _zieldateien(alt)

    neu = tmp_path / "F" / "Archiv"
    neu.parent.mkdir()
    os.rename(alt, neu)                      # die Platte heisst jetzt F:
    neu = pfade.aufloesen(neu)
    capsys.readouterr()

    assert _cli("pruefen", "--ziel", neu) == cli.OK
    aus = capsys.readouterr().out
    assert "Das Archiv lag bisher unter" in aus and str(alt) in aus and str(neu) in aus
    zeilen = _zeilen(nachschauen, neu)
    for p in geprueft:
        assert zeilen[p]["status"] == "geprueft", p     # nichts als "fehlt" zurueckgefallen
    archivpfade = _alle_archivpfade(nachschauen, neu)
    assert archivpfade and all(_unter(t, neu) for t in archivpfade)
    assert _zieldateien(neu) == inhalt                  # im Archiv nichts angefasst

    # Vorher eine Sicherung der Datenbank, mit den alten Pfaden.
    sicherungen = sorted(_archiv_ordner(nachschauen, neu).glob(umzug.SICHERUNG_MUSTER))
    assert len(sicherungen) == 1 and str(sicherungen[0]) in aus
    with contextlib.closing(sqlite3.connect(sicherungen[0])) as v:
        alte = [r[0] for r in v.execute("SELECT zielpfad FROM dateien WHERE zielpfad != ''")]
    assert alte and all(_unter(t, alt) for t in alte)

    # Ein zweiter Befehl findet nichts mehr umzustellen.
    capsys.readouterr()
    assert _cli("pruefen", "--ziel", neu) == cli.OK
    assert "Das Archiv lag bisher unter" not in capsys.readouterr().out
    assert len(sorted(_archiv_ordner(nachschauen, neu).glob(umzug.SICHERUNG_MUSTER))) == 1

    # Ein neuer Durchgang haelt die eigenen Kopien nicht fuer "schon im Archiv",
    # und das Aufraeumen findet die Kopien am neuen Ort.
    _vorbereiten(neu, quelle)
    assert _cli("kopieren", "--ziel", neu) == cli.OK
    zeilen = _zeilen(nachschauen, neu)
    assert not any(z["schon_im_archiv"] for p, z in zeilen.items() if p in geprueft)
    assert _zieldateien(neu) == inhalt                  # nichts doppelt kopiert
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", neu) == cli.OK
    zeilen = _zeilen(nachschauen, neu)
    for p in geprueft:
        assert zeilen[p]["status"] == "quelle_geloescht", p


def test_umzug_zwischen_analyse_und_kopieren_schreibt_nie_an_den_alten_ort(quelle, tmp_path, nachschauen):
    """Die Zielnamen werden in der Analyse geplant. Taucht unter dem alten Pfad
    inzwischen ein anderer Ordner auf (anderes Laufwerk mit dem alten
    Buchstaben), darf dort nichts entstehen."""
    alt = tmp_path / "E" / "Archiv"
    alt.mkdir(parents=True)
    _vorbereiten(alt, quelle)
    alt = pfade.aufloesen(alt)
    neu = tmp_path / "F" / "Archiv"
    neu.parent.mkdir()
    os.rename(alt, neu)
    alt.mkdir()                                  # fremder Ordner unter dem alten Pfad
    assert _cli("kopieren", "--ziel", neu) == cli.OK
    assert list(alt.iterdir()) == []
    neu = pfade.aufloesen(neu)
    kopiert = [z for z in _zeilen(nachschauen, neu).values() if z["status"] == "kopiert"]
    assert kopiert and all(_unter(z["zielpfad"], neu) and Path(db.text_pfad(z["zielpfad"])).is_file()
                           for z in kopiert)


# ------------------------------------------------------- Verweigern ----


def test_archiv_zweimal_vorhanden_bricht_ab_und_aendert_nichts(quelle, tmp_path, nachschauen, capsys):
    """Liegt das Archiv am alten Ort noch da (dieselbe Archiv-Kennung), ist der
    neue Ordner eine Kopie. Welcher gilt, weiss das Programm nicht: abbrechen."""
    alt = tmp_path / "E" / "Archiv"
    alt.mkdir(parents=True)
    _bis_geprueft(quelle, alt)
    neu = tmp_path / "F" / "Archiv"
    shutil.copytree(alt, neu)
    vorher = _zeilen(nachschauen, alt)
    capsys.readouterr()
    for befehl in ("pruefen", "kopieren", "scan"):
        assert _cli(befehl, "--ziel", neu) == cli.FEHLER
        aus = capsys.readouterr().out
        assert "zweimal" in aus and str(pfade.aufloesen(alt)) in aus, aus
    assert _zeilen(nachschauen, alt) == vorher
    assert not list(_archiv_ordner(nachschauen, alt).glob(umzug.SICHERUNG_MUSTER))
    # Am alten Ort geht es ganz normal weiter.
    assert _cli("pruefen", "--ziel", alt) == cli.OK


def test_nur_lesende_befehle_stellen_nichts_um(quelle, tmp_path, nachschauen):
    alt = tmp_path / "E" / "Archiv"
    alt.mkdir(parents=True)
    _bis_geprueft(quelle, alt)
    alt = pfade.aufloesen(alt)
    neu = tmp_path / "F" / "Archiv"
    neu.parent.mkdir()
    os.rename(alt, neu)
    vorher = _zeilen(nachschauen, neu)
    assert _cli("status", "--ziel", neu) == cli.OK
    assert _cli("bericht", "--ziel", neu) == cli.OK
    assert _zeilen(nachschauen, neu) == vorher
    assert not list(_archiv_ordner(nachschauen, neu).glob(umzug.SICHERUNG_MUSTER))


# ------------------------------------- Datenbank von vor v0.14 -----


def test_datenbank_ohne_gespeicherten_ort_findet_den_alten_ueber_die_dateien(quelle, tmp_path, nachschauen, capsys):
    """Datenbanken bis v0.13 kennen ihren Archivort nicht. Der alte Ort ergibt
    sich dann aus den gespeicherten Pfaden der Dateien, die am neuen Ort mit
    derselben Groesse wieder auftauchen."""
    alt = tmp_path / "E" / "Archiv"
    alt.mkdir(parents=True)
    _bis_geprueft(quelle, alt)
    alt = pfade.aufloesen(alt)
    with nachschauen(alt) as d:
        d.verbindung.execute("DELETE FROM archiv_angaben")
        d.verbindung.commit()
    geprueft = {p for p, z in _zeilen(nachschauen, alt).items() if z["status"] == "geprueft"}
    neu = tmp_path / "F" / "Archiv"
    neu.parent.mkdir()
    os.rename(alt, neu)
    neu = pfade.aufloesen(neu)
    capsys.readouterr()
    assert _cli("pruefen", "--ziel", neu) == cli.OK
    assert "Das Archiv lag bisher unter" in capsys.readouterr().out
    zeilen = _zeilen(nachschauen, neu)
    assert all(zeilen[p]["status"] == "geprueft" for p in geprueft)
    assert all(_unter(t, neu) for t in _alle_archivpfade(nachschauen, neu))


def test_datenbank_ohne_gespeicherten_ort_am_selben_ort_merkt_ihn_sich(quelle, ziel, nachschauen, capsys):
    _bis_geprueft(quelle, ziel)
    with nachschauen(ziel) as d:
        d.verbindung.execute("DELETE FROM archiv_angaben")
        d.verbindung.commit()
    capsys.readouterr()
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert "Das Archiv lag bisher unter" not in capsys.readouterr().out
    with nachschauen(ziel) as d:
        assert d.angabe_lesen(umzug.ANGABE_WURZEL) == db.pfad_text(pfade.aufloesen(ziel))


# ------------------------------------------------ Pfade umschreiben ----


def test_umschreiben_auch_mit_windows_pfaden_und_laufwerkswurzel(tmp_path):
    """Die Rechnung selbst, mit Windows-Pfaden (auch unter Linux pruefbar):
    Archiv direkt auf der Laufwerkswurzel, Unterordner, Namen mit "%" und "_"
    (in SQL-LIKE Platzhalter) und ein aehnlich beginnender Nachbarordner, der
    NICHT dazugehoert."""
    d = db.Datenbank.oeffnen(tmp_path / "a")
    try:
        v = d.verbindung
        zeilen = [
            ("q1", "E:\\2019\\01\\a.jpg"), ("q2", "E:\\2019\\b%_c.jpg"), ("q3", "E:\\x.jpg"),
            ("q4", "E:\\Archiv\\y.jpg"), ("q5", "G:\\fremd\\z.jpg"),
        ]
        for q, z in zeilen:
            v.execute("INSERT INTO dateien (quellpfad, quellwurzel, zielpfad, schreibpfad) VALUES (?, '', ?, ?)",
                      (q, z, z))
            v.execute("INSERT INTO abgelegt (zielpfad, lauf) VALUES (?, 1)", (z,))
            v.execute("INSERT INTO ziel_index (zielpfad) VALUES (?)", (z,))
        v.commit()
        n = umzug.umschreiben(d, "E:\\", "F:\\Fotos", trenner="\\")
        assert n == 4
        neu = dict(v.execute("SELECT quellpfad, zielpfad FROM dateien"))
        assert neu == {"q1": "F:\\Fotos\\2019\\01\\a.jpg", "q2": "F:\\Fotos\\2019\\b%_c.jpg",
                       "q3": "F:\\Fotos\\x.jpg", "q4": "F:\\Fotos\\Archiv\\y.jpg", "q5": "G:\\fremd\\z.jpg"}
        assert dict(v.execute("SELECT quellpfad, schreibpfad FROM dateien")) == neu
        for tabelle in ("abgelegt", "ziel_index"):
            assert sorted(r[0] for r in v.execute(f"SELECT zielpfad FROM {tabelle}")) == sorted(neu.values())

        n = umzug.umschreiben(d, "F:\\Fotos\\2019", "H:\\Neu", trenner="\\")
        assert n == 2
        assert dict(v.execute("SELECT quellpfad, zielpfad FROM dateien"))["q1"] == "H:\\Neu\\01\\a.jpg"
        # "F:\Fotos\2019x" gehoert nicht zu "F:\Fotos\2019".
        v.execute("INSERT INTO dateien (quellpfad, quellwurzel, zielpfad) VALUES ('q6', '', 'F:\\Fotos\\2019x\\d.jpg')")
        v.commit()
        assert umzug.umschreiben(d, "F:\\Fotos\\2019", "H:\\Neu", trenner="\\") == 0
    finally:
        d.schliessen()


def test_umschreiben_mit_nicht_lesbaren_namen(tmp_path):
    """Namen, die kein gueltiges UTF-8 sind, stehen kodiert in der Datenbank
    (db.pfad_text) - auch sie ziehen mit um."""
    d = db.Datenbank.oeffnen(tmp_path / "a")
    try:
        v = d.verbindung
        roh = "/alt/Archiv/2019/bild_\udcff.jpg"
        gespeichert = db.pfad_text(roh)
        assert gespeichert != roh
        v.execute("INSERT INTO dateien (quellpfad, quellwurzel, zielpfad) VALUES ('q', '', ?)", (gespeichert,))
        v.execute("INSERT INTO abgelegt (zielpfad, lauf) VALUES (?, 1)", (gespeichert,))
        v.commit()
        assert umzug.umschreiben(d, "/alt/Archiv", "/neu/Archiv", trenner="/") == 1
        (z,) = v.execute("SELECT zielpfad FROM dateien").fetchone()
        assert db.text_pfad(z) == "/neu/Archiv/2019/bild_\udcff.jpg"
        (a,) = v.execute("SELECT zielpfad FROM abgelegt").fetchone()
        assert a == z
    finally:
        d.schliessen()


# ------------------------------------------------- letzte Absicherung ----


def test_kopieren_schreibt_nie_ausserhalb_des_gewaehlten_archivs(quelle, ziel, tmp_path, nachschauen):
    """Auch wenn ein geplanter Zielname - auf welchem Weg auch immer - ausserhalb
    des Archivs liegt: Das Kopieren bricht ab, statt dort etwas anzulegen."""
    from fotosort import config, kopieren
    _vorbereiten(ziel, quelle)
    aussen = tmp_path / "Fremd"
    aussen.mkdir()
    with nachschauen(ziel) as d:
        (q,) = d.verbindung.execute("SELECT quellpfad FROM dateien WHERE status = 'analysiert' LIMIT 1").fetchone()
        d.verbindung.execute("UPDATE dateien SET zielpfad = ? WHERE quellpfad = ?",
                             (db.pfad_text(aussen / "bild.jpg"), q))
        d.verbindung.commit()
        lauf = d.lauf_beginnen("test")
        try:
            kopieren.ausfuehren(pfade.aufloesen(ziel), config.Konfiguration(), d, lauf, None)
        except cli.FotosortFehler as fehler:
            assert "ausserhalb des Archivs" in str(fehler)
        else:
            raise AssertionError("Kopieren haette abbrechen muessen")
    assert list(aussen.iterdir()) == []
