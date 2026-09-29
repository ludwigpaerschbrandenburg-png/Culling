"""fotosort pruefen --alles: das ganze Archiv erneut lesen (Bitfaeule, veraenderte
oder verschwundene Archivdateien) und die Pruefsummen-Liste im Ziel."""

from __future__ import annotations

from pathlib import Path

import pytest

from fotosort import cli, db, hashes, nachpruefen, pruefen
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


def _antwort(monkeypatch, wort: str) -> None:
    monkeypatch.setenv("FOTOSORT_EINGABE_ERZWINGEN", "1")
    monkeypatch.setattr("builtins.input", lambda: wort)


def _kippen(pfad: Path) -> None:
    inhalt = bytearray(pfad.read_bytes())
    inhalt[-1] ^= 0x01
    pfad.write_bytes(bytes(inhalt))


def _index_zahl(nachschauen, ziel) -> int:
    with nachschauen(ziel) as d:
        return d.verbindung.execute("SELECT COUNT(*) FROM ziel_index").fetchone()[0]


def test_von_hand_geloeschte_quelle_gilt_nicht_als_ersatz(baum, quelle, ziel, nachschauen, capsys):
    """Haeufigster Ablauf: alles geprueft, dann die Speicherkarte selbst formatiert
    (nicht ueber aufraeumen) - der Status sagt weiter "geprueft". Geht spaeter die
    Archivdatei kaputt, darf die Nachpruefung nicht "wird neu kopiert" sagen, denn
    kopiert werden kann nichts mehr: Sie sieht nach, ob die Quelle wirklich da ist."""
    _bis_geprueft(ziel, quelle)
    opfer = Path(baum["analog"])
    z = _zeilen(nachschauen, ziel)[str(opfer)]
    opfer.unlink()
    _kippen(Path(z["zielpfad"]))
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "eigenen Sicherung" in aus and "neu zu kopieren" not in aus
    text = _ereignisse(nachschauen, ziel, nachpruefen.ART_VERAENDERT)[0]["text"]
    assert "Quelle noch da" not in text and "Sicherung" in text
    # Die Loeschberechtigung ist trotzdem weg; kommt die Karte zurueck, wird neu kopiert.
    assert _zeilen(nachschauen, ziel)[str(opfer)]["status"] == "fehler"


def test_original_im_papierkorb_wird_genannt(baum, quelle, ziel, nachschauen, capsys, monkeypatch):
    """Aufgeraeumt in den Papierkorb der Quelle, dann fehlt die Archivdatei: Der
    Hinweis nennt die Datei im Papierkorb - das ist die naechste Rettung."""
    _bis_geprueft(ziel, quelle)
    _antwort(monkeypatch, "verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "quelle_geloescht" and z["schreibpfad"]
    Path(z["zielpfad"]).unlink()
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "Papierkorb" in aus and db.text_pfad(z["schreibpfad"]) in aus
    assert "Papierkorb" in _ereignisse(nachschauen, ziel, nachpruefen.ART_FEHLT)[0]["text"]


@pytest.mark.parametrize("fremd", ["0" * 64, "f" * 64])
def test_jede_zeile_wird_fuer_sich_verglichen(baum, quelle, ziel, nachschauen, capsys, fremd):
    """Zwei Zeilen zeigen auf dieselbe Archivdatei, aber mit verschiedenem Inhalt
    (A aufgeraeumt, Archivdatei spaeter weg, B danach unter demselben Namen
    abgelegt). Frueher entschied der "groessere" Hash: Mal galt die heile Datei
    von B als veraendert, mal fiel der Verlust von A nie auf."""
    _bis_geprueft(ziel, quelle)
    zeilen = _geprueft(nachschauen, ziel)
    b = next(z for z in zeilen if z["quellpfad"] == str(baum["analog"]))
    a = next(z for z in zeilen if z["zielpfad"] != b["zielpfad"])
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET zielpfad = ?, status = 'quelle_geloescht', hash = ? "
                             "WHERE quellpfad = ?", (b["zielpfad"], fremd, a["quellpfad"]))
        d.verbindung.commit()
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "eigenen Sicherung" in aus
    nachher = _zeilen(nachschauen, ziel)
    assert nachher[b["quellpfad"]]["status"] == "geprueft"
    assert nachher[a["quellpfad"]]["status"] == "quelle_geloescht"
    ereignisse = _ereignisse(nachschauen, ziel, nachpruefen.ART_VERAENDERT)
    assert [e["pfad"] for e in ereignisse] == [b["zielpfad"]]
    # Die Liste nennt fuer die Datei den Hash, den sie wirklich hat.
    rel = Path(b["zielpfad"]).relative_to(ziel.resolve()).as_posix()
    assert _liste_lesen(ziel)[rel] == b["hash"]


def _abziehen_waehrend(monkeypatch, modul, ziel: Path) -> None:
    """Das Ziel verschwindet, nachdem das Archiv geoeffnet ist (USB-Platte
    schlaeft ein, Netz reisst ab), und ist danach wieder da."""
    echt = modul.ausfuehren
    weg = ziel.with_name(ziel.name + "_abgezogen")

    def abgezogen(ziel_, *a, **k):
        ziel.rename(weg)
        try:
            return echt(ziel_, *a, **k)
        finally:
            weg.rename(ziel)

    monkeypatch.setattr(modul, "ausfuehren", abgezogen)


def test_verschwundenes_ziel_beim_nachpruefen_stellt_nichts_um(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    """Ist das ganze Ziel weg, fehlt ploetzlich jede Archivdatei. Dann ist nicht
    das Archiv kaputt: abbrechen, nichts umstellen, nichts aus dem Ziel-Index
    nehmen, klar sagen - statt tausendfach "aus der Sicherung holen"."""
    _bis_geprueft(ziel, quelle)
    vorher = _zeilen(nachschauen, ziel)
    index = _index_zahl(nachschauen, ziel)
    _abziehen_waehrend(monkeypatch, nachpruefen, ziel)
    capsys.readouterr()
    assert _cli("pruefen", "--alles", "--ziel", ziel) == cli.FEHLER
    assert "nicht mehr erreichbar" in capsys.readouterr().out
    assert _zeilen(nachschauen, ziel) == vorher
    assert not _ereignisse(nachschauen, ziel, nachpruefen.ART_FEHLT)
    assert _index_zahl(nachschauen, ziel) == index


def test_verschwundenes_ziel_beim_pruefen_stellt_nichts_um(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    vorher = _zeilen(nachschauen, ziel)
    _abziehen_waehrend(monkeypatch, pruefen, ziel)
    capsys.readouterr()
    assert _cli("pruefen", "--ziel", ziel) == cli.FEHLER
    assert "nicht mehr erreichbar" in capsys.readouterr().out
    assert _zeilen(nachschauen, ziel) == vorher


def test_pruefsummen_liste_auch_bei_anderer_schreibweise_des_ziels(baum, quelle, ziel, nachschauen, monkeypatch):
    """Relativ, ueber eine Verknuepfung (unter Windows auch: andere Gross-/
    Kleinschreibung, Laufwerksbuchstabe statt Netzpfad): dieselbe Liste."""
    _bis_geprueft(ziel, quelle)
    vorher = _liste_lesen(ziel)
    assert vorher
    monkeypatch.chdir(ziel.parent)
    assert _cli("pruefen", "--ziel", Path(ziel.name)) == cli.OK
    assert _liste_lesen(ziel) == vorher
    verknuepfung = ziel.parent / "ueber_verknuepfung"
    try:
        verknuepfung.symlink_to(ziel, target_is_directory=True)
    except OSError:
        pytest.skip("Verknuepfungen sind hier nicht erlaubt")
    assert _cli("pruefen", "--ziel", verknuepfung) == cli.OK
    assert _liste_lesen(ziel) == vorher


def test_pruefsummen_liste_bleibt_wenn_zeilen_nicht_passen(baum, quelle, ziel, nachschauen, capsys):
    """Liegen Archivdateien laut Datenbank nicht unter dem angegebenen Ziel, wird
    die gute alte Liste nicht durch eine lueckenhafte ersetzt - mit Hinweis."""
    _bis_geprueft(ziel, quelle)
    vorher = _liste_lesen(ziel)
    z = _geprueft(nachschauen, ziel)[0]
    with nachschauen(ziel) as d:
        d.verbindung.execute("UPDATE dateien SET zielpfad = ? WHERE quellpfad = ?",
                             (db.pfad_text(ziel.parent / "anderswo" / "x.jpg"), z["quellpfad"]))
        d.verbindung.commit()
    capsys.readouterr()
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    assert "nicht erneuert" in capsys.readouterr().out
    assert _liste_lesen(ziel) == vorher
