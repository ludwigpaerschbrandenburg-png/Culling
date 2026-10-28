"""Gleiche Bilder mit Kopie-Namen: Ins Archiv kommt der Name ohne „Kopie“
(Entscheidung des Nutzers vom 28.10.2026, SPEC Abschnitt 4 Phase 3).

Windows legt beim Kopieren im selben Ordner „Bild - Kopie.jpg“ an. Bisher kam
von zwei gleichen Bildern das zuerst in der Reihenfolge der Quelle ins
Archiv - und „Bild - Kopie.jpg“ steht vor „Bild.jpg“ (Leerzeichen vor Punkt).
Die unterlegene Datei bleibt ein gewoehnliches Duplikat: Geloescht wird sie
nur nach den Regeln aus SPEC Abschnitt 5.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import testbaum
from fotosort import cli, dateitypen, hashes, kopieren, loeschen
from test_kopieren import _cli, _parts, _vorbereiten, _zeilen

GLEICH = testbaum._JPEG + b"gleicher Inhalt"


@pytest.fixture
def antwort(monkeypatch):
    """Die Bestaetigung wie am Terminal: input() liefert das gewuenschte Wort."""
    antworten: list[str] = []
    monkeypatch.setenv("FOTOSORT_EINGABE_ERZWINGEN", "1")
    monkeypatch.setattr("builtins.input", lambda: antworten.pop(0) if antworten else "")
    return antworten


def _archivnamen(ziel: Path) -> list[str]:
    return sorted(p.name for p in ziel.rglob("*") if p.is_file() and ".fotosortierer" not in p.parts)


@pytest.mark.parametrize(
    "name,rang",
    [
        ("Bild.jpg", 0), ("IMG_0001.JPG", 0), ("Kopierer.jpg", 0), ("Urlaub 2019.jpg", 0),
        ("DSC_1137.NEF", 0), ("Kopie.jpg", 0), ("ohne_endung", 0),
        ("Bild - Kopie.jpg", 1), ("Bild - Copy.JPG", 1), ("Bild Kopie.jpg", 1), ("Bild copy.jpg", 1),
        ("Kopie von Bild.jpg", 1), ("Copy of Bild.jpg", 1), ("BILD - KOPIE.JPG", 1),
        ("Bild - Kopie - Kopie.jpg", 1),
        ("Bild - Kopie (2).jpg", 2), ("Bild - Copy (3).jpg", 2), ("Bild (1).jpg", 2), ("Bild(2).jpg", 2),
        ("Kopie (2) von Bild.jpg", 2), ("Copy (3) of Bild.jpg", 2), ("Bild Kopie 2.jpg", 2),
        ("Bild copy 3.jpg", 2),
    ],
)
def test_kopie_rang_erkennt_die_namen(name, rang):
    assert dateitypen.kopie_rang(name) == rang


def test_im_archiv_landet_der_name_ohne_kopie(tmp_path, ziel, nachschauen, antwort):
    """Der Fall aus dem Testlauf: „Bild - Kopie.jpg“ steht in der Quelle vor
    „Bild.jpg“ - trotzdem kommt „Bild.jpg“ ins Archiv. Die Kopie ist ein
    Duplikat, wird geprueft und beim Aufraeumen mit weggeraeumt; nichts geht
    verloren."""
    q = tmp_path / "Q"
    kopie = testbaum._schreiben(q / "Reise" / "Bild - Kopie.jpg", GLEICH)
    original = testbaum._schreiben(q / "Reise" / "Bild.jpg", GLEICH)
    allein = testbaum._schreiben(q / "Reise" / "Anders - Kopie.jpg", testbaum._JPEG + b"anders")
    _vorbereiten(ziel, q)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    zo, zk = zeilen[str(original)], zeilen[str(kopie)]
    assert zo["status"] == "kopiert" and Path(zo["zielpfad"]).name == "Bild.jpg", zo
    assert zk["status"] == "duplikat" and zk["zielpfad"] == zo["zielpfad"], zk
    # Gibt es nur die Kopie, behaelt sie ihren Namen.
    assert Path(zeilen[str(allein)]["zielpfad"]).name == "Anders - Kopie.jpg"
    assert _archivnamen(ziel) == ["Anders - Kopie.jpg", "Bild.jpg"]
    assert not _parts(ziel)

    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(original)]["status"] == "geprueft"
    assert zeilen[str(kopie)]["status"] == "duplikat_bestaetigt"

    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert {zeilen[str(p)]["status"] for p in (original, kopie, allein)} == {"quelle_geloescht"}
    korb = next(p for p in q.iterdir() if p.is_dir() and loeschen.ist_papierkorb(p.name))
    for p in (original, kopie):
        assert not p.exists()
        assert hashes.blake3_datei(korb / "Reise" / p.name) == hashes.blake3_datei(Path(zo["zielpfad"]))


def test_auch_ueber_zwei_quellen(tmp_path, ziel, nachschauen):
    """Die Kopie liegt in der Quelle, die zuerst an der Reihe ist."""
    kopie = testbaum._schreiben(tmp_path / "A_Quelle" / "Karte" / "Bild - Kopie.jpg", GLEICH)
    original = testbaum._schreiben(tmp_path / "B_Quelle" / "Karte" / "Bild.jpg", GLEICH)
    _vorbereiten(ziel, tmp_path / "A_Quelle", tmp_path / "B_Quelle")
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(original)]["status"] == "kopiert"
    assert zeilen[str(kopie)]["status"] == "duplikat"
    assert _archivnamen(ziel) == ["Bild.jpg"]


def test_unter_kopien_gewinnt_die_ohne_nummer(tmp_path, ziel, nachschauen):
    q = tmp_path / "Q"
    x = [testbaum._schreiben(q / "X" / n, GLEICH + b"x") for n in ("X (2).jpg", "Kopie von X.jpg", "X.jpg")]
    y = [testbaum._schreiben(q / "Y" / n, GLEICH + b"y") for n in ("Y (2).jpg", "Kopie von Y.jpg")]
    _vorbereiten(ziel, q)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert [zeilen[str(p)]["status"] for p in x] == ["duplikat", "duplikat", "kopiert"]
    assert [zeilen[str(p)]["status"] for p in y] == ["duplikat", "kopiert"]
    assert _archivnamen(ziel) == ["Kopie von Y.jpg", "X.jpg"]


def test_verschiedener_inhalt_kommt_unter_beiden_namen_ins_archiv(tmp_path, ziel, nachschauen):
    q = tmp_path / "Q"
    testbaum._schreiben(q / "Reise" / "Bild - Kopie.jpg", GLEICH + b"bearbeitet")
    testbaum._schreiben(q / "Reise" / "Bild.jpg", GLEICH)
    _vorbereiten(ziel, q)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert {z["status"] for z in _zeilen(nachschauen, ziel).values()} == {"kopiert"}
    assert _archivnamen(ziel) == ["Bild - Kopie.jpg", "Bild.jpg"]


def test_seitenweise_kommt_jede_datei_genau_einmal_dran(tmp_path, ziel, nachschauen, monkeypatch):
    """Die Kopier-Reihenfolge laeuft seitenweise ueber die Datenbank. Mit dem
    Rang davor muss jede Zeile genau einmal drankommen - auch wenn Originale
    und Kopien ueber viele kleine Seiten verteilt sind."""
    monkeypatch.setattr(kopieren, "SEITE", 3)
    q = tmp_path / "Q"
    paare = []
    for i in range(8):
        inhalt = GLEICH + str(i).encode()
        paare.append((testbaum._schreiben(q / f"Tag{i % 3}" / f"IMG_{i:02d}.jpg", inhalt),
                      testbaum._schreiben(q / f"Tag{i % 3}" / f"IMG_{i:02d} - Kopie.jpg", inhalt)))
    _vorbereiten(ziel, q)
    assert _cli("kopieren", "--ziel", ziel, "--kopier-worker", 1) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    for original, kopie in paare:
        assert zeilen[str(original)]["status"] == "kopiert"
        assert zeilen[str(kopie)]["status"] == "duplikat"
    assert _archivnamen(ziel) == sorted(f"IMG_{i:02d}.jpg" for i in range(8))


def test_schon_analysiertes_archiv_bekommt_die_regel_beim_kopieren(tmp_path, ziel, nachschauen):
    """Ein Archiv, das noch mit v0.12 analysiert wurde (Rang ueberall 0), bekommt
    den Rang zu Beginn des Kopierens nachgetragen."""
    q = tmp_path / "Q"
    kopie = testbaum._schreiben(q / "Reise" / "Bild - Kopie.jpg", GLEICH)
    original = testbaum._schreiben(q / "Reise" / "Bild.jpg", GLEICH)
    _vorbereiten(ziel, q)
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET kopie_rang = 0")
        d.verbindung.commit()
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(original)]["status"] == "kopiert"
    assert zeilen[str(kopie)]["status"] == "duplikat"


def test_verschieben_nimmt_auch_den_namen_ohne_kopie(tmp_path, ziel, nachschauen, monkeypatch):
    """Verschieben ueber Laufwerksgrenzen (kopieren, beide Seiten frisch lesen,
    dann Quelle loeschen): „Bild.jpg“ kommt ins Archiv und verschwindet aus der
    Quelle; die Kopie bleibt als Duplikat liegen (nur ueber duplikat_bestaetigt).
    Auf demselben Laufwerk wird nur umbenannt, ohne zu lesen - dort gibt es
    keine Wahl, beide behalten ihren Namen (SPEC Abschnitt 4 Phase 3)."""
    monkeypatch.setattr(kopieren.pfade, "gleiches_laufwerk", lambda a, b: False)
    q = tmp_path / "Q"
    kopie = testbaum._schreiben(q / "Reise" / "Bild - Kopie.jpg", GLEICH)
    original = testbaum._schreiben(q / "Reise" / "Bild.jpg", GLEICH)
    _vorbereiten(ziel, q)
    assert _cli("kopieren", "--ziel", ziel, "--verschieben") == cli.OK
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(original)]["status"] == "quelle_geloescht" and not original.exists()
    assert zeilen[str(kopie)]["status"] == "duplikat" and kopie.exists()
    assert _archivnamen(ziel) == ["Bild.jpg"]
    assert hashes.blake3_datei(kopie) == hashes.blake3_datei(Path(zeilen[str(original)]["zielpfad"]))
