"""fotosort pruefen --alles: das ganze Archiv erneut lesen (Bitfaeule, veraenderte
oder verschwundene Archivdateien) und die Pruefsummen-Liste im Ziel."""

from __future__ import annotations

from pathlib import Path

from fotosort import cli, db, hashes, nachpruefen
from test_kopieren import _cli, _ereignisse, _vorbereiten, _zeilen


def _bis_geprueft(ziel, quelle) -> None:
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK


def _geprueft(nachschauen, ziel) -> list[dict]:
    return [z for z in _zeilen(nachschauen, ziel).values() if z["status"] == "geprueft"]


def _liste_lesen(ziel: Path) -> dict[str, str]:
    """Pruefsummen-Liste (Format von b3sum): relativer Pfad -> Hash."""
    ergebnis = {}
    for zeile in nachpruefen.pruefsummen_pfad(ziel).read_text(encoding="utf-8").splitlines():
        h, pfad = zeile.split("  ", 1)
        ergebnis[pfad] = h
    return ergebnis


def test_pruefen_schreibt_eine_pruefsummen_liste_die_stimmt(baum, quelle, ziel, nachschauen):
    """Neben dem Archiv liegt eine Liste im Format von b3sum: So laesst sich das
    Archiv auch ohne fotosort pruefen (b3sum --check), in zehn Jahren noch."""
    _bis_geprueft(ziel, quelle)
    liste = _liste_lesen(ziel)
    geprueft = _geprueft(nachschauen, ziel)
    assert geprueft and len(liste) >= len({z["zielpfad"] for z in geprueft})
    for rel, h in liste.items():
        pfad = ziel / rel
        assert hashes.blake3_datei(pfad) == h, rel
    assert db.ARCHIV_UNTERORDNER not in "".join(liste)


def test_unveraendertes_archiv_ist_ohne_befund(baum, quelle, ziel, nachschauen, capsys):
    _bis_geprueft(ziel, quelle)
    vorher = _zeilen(nachschauen, ziel)
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "Archiv nachgeprueft" in aus and "alle unveraendert" in aus
    assert _zeilen(nachschauen, ziel) == vorher


def test_veraenderte_archivdatei_wird_gefunden_und_aus_der_quelle_ersetzt(baum, quelle, ziel, nachschauen, capsys):
    """Ein Bit kippt auf der Platte (oder jemand bearbeitet ein Original im
    Archiv): Die Nachpruefung findet es, die Datei verliert ihre Loeschberechtigung,
    und das naechste Kopieren legt aus der noch vorhandenen Quelle eine frische
    Kopie daneben. Die veraenderte Datei bleibt liegen (nie ueberschreiben)."""
    _bis_geprueft(ziel, quelle)
    z = next(z for z in _geprueft(nachschauen, ziel) if z["quellpfad"] == str(baum["analog"]))
    kaputt = Path(z["zielpfad"])
    inhalt = bytearray(kaputt.read_bytes())
    inhalt[-1] ^= 0x01
    kaputt.write_bytes(bytes(inhalt))
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "veraendert" in aus and str(kaputt) in aus
    zeile = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert zeile["status"] == "fehler"
    assert len(_ereignisse(nachschauen, ziel, nachpruefen.ART_VERAENDERT)) == 1
    # Kopieren holt aus der Quelle eine frische Kopie; die kaputte bleibt liegen.
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert kaputt.read_bytes() == bytes(inhalt)
    neu = Path(_zeilen(nachschauen, ziel)[str(baum["analog"])]["zielpfad"])
    assert neu != kaputt and hashes.blake3_datei(neu) == hashes.blake3_datei(baum["analog"])
    assert _cli("pruefen", "--ziel", ziel) == cli.OK


def test_fehlende_archivdatei_nach_dem_aufraeumen_wird_laut_gemeldet(baum, quelle, ziel, nachschauen, capsys, monkeypatch):
    """Ist die Quelle schon geloescht, gibt es keinen Ersatz mehr - dann muss die
    Nachpruefung es wenigstens unuebersehbar sagen (Bericht, Rueckgabewert)."""
    _bis_geprueft(ziel, quelle)
    monkeypatch.setenv("FOTOSORT_EINGABE_ERZWINGEN", "1")
    monkeypatch.setattr("builtins.input", lambda: "loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    z = next(z for z in _zeilen(nachschauen, ziel).values() if z["status"] == "quelle_geloescht")
    Path(z["zielpfad"]).unlink()
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "FEHLT: 1" in aus and "Quelle schon geloescht" in aus
    assert _zeilen(nachschauen, ziel)[z["quellpfad"]]["status"] == "quelle_geloescht"
    assert len(_ereignisse(nachschauen, ziel, nachpruefen.ART_FEHLT)) == 1
    capsys.readouterr()
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    assert z["zielpfad"] in capsys.readouterr().out


def test_nachpruefung_laesst_sich_abbrechen_und_liest_nichts_doppelt(baum, quelle, ziel, nachschauen, monkeypatch):
    _bis_geprueft(ziel, quelle)
    gelesen: list[str] = []
    echt = nachpruefen._lesen

    def zaehlen(pfad, stop):
        gelesen.append(str(pfad))
        return echt(pfad, stop)

    monkeypatch.setattr(nachpruefen, "_lesen", zaehlen)
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.OK
    assert len(gelesen) == len(set(gelesen))
