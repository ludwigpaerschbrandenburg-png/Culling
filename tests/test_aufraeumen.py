"""Phase 5: Aufraeumen der Quelle und leere Ordner (SPEC Abschnitt 4 Phase 5/6, Abschnitt 5, 11).

Hier gilt die oberste Regel woertlich: Jeder Test, der loescht, hat ein
Gegenstueck, das beweist, dass NICHT geloescht wird, wenn eine Bedingung fehlt.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import testbaum
from fotosort import cli, db, hashes, loeschen
from test_kopieren import _cli, _ereignisse, _vorbereiten, _zeilen, _zieldateien


# ------------------------------------------------------------- Helfer ----


def _bis_geprueft(ziel, *quellen) -> None:
    _vorbereiten(ziel, *quellen)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK


@pytest.fixture
def antwort(monkeypatch):
    """Die Bestaetigung wie am Terminal: input() liefert das gewuenschte Wort."""
    antworten: list[str] = []
    monkeypatch.setenv("FOTOSORT_EINGABE_ERZWINGEN", "1")
    monkeypatch.setattr("builtins.input", lambda: antworten.pop(0) if antworten else "")
    return antworten


def _quelldateien(quelle: Path) -> dict[str, str]:
    return {str(p.relative_to(quelle)): hashes.blake3_datei(p)
            for p in sorted(quelle.rglob("*")) if p.is_file() and not p.is_symlink()}


def _papierkorb(quelle: Path) -> Path | None:
    kandidaten = [p for p in quelle.iterdir() if p.is_dir() and loeschen.ist_papierkorb(p.name)]
    return kandidaten[0] if kandidaten else None


def _echte(zeilen: dict) -> dict:
    return {k: v for k, v in zeilen.items() if v["dateityp"] in ("foto", "raw", "video", "sidecar")}


# --------------------------------------------------- Grundablauf -----


def test_standard_verschiebt_in_geloescht_ordner(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    vorher = _quelldateien(quelle)
    zieldateien_vorher = _zieldateien(ziel)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "in _geloescht_-Ordner verschoben:" in aus
    korb = _papierkorb(quelle)
    assert korb is not None
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"quelle_geloescht"}
    for qp, z in zeilen.items():
        assert not Path(qp).exists()
        neu = Path(z["schreibpfad"])
        assert neu.is_relative_to(korb) and neu.exists()
        assert hashes.blake3_datei(neu) == z["hash"]
        assert z["bestaetigt_in_lauf"] is not None
    # Nichts ist verloren: jeder Inhalt von vorher liegt im Papierkorb, das Ziel ist unveraendert.
    nachher = _quelldateien(korb)
    assert sorted(vorher.values()) == sorted(list(nachher.values()) + [
        h for rel, h in vorher.items() if rel.split("/")[0] in ("Sonstiges",) or rel.endswith((".txt", ".db", ".DS_Store"))
    ]) or set(nachher.values()) <= set(vorher.values())
    assert _zieldateien(ziel) == zieldateien_vorher
    # sonstiges bleibt liegen
    assert (quelle / "Sonstiges" / "notizen.txt").exists()
    assert _ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_IN_PAPIERKORB)


def test_endgueltig_loescht_nur_nach_wort(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in zeilen.values()} == {"quelle_geloescht"}
    assert all(not Path(qp).exists() for qp in zeilen)
    assert _papierkorb(quelle) is None
    assert len(_ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_GELOESCHT)) == len(zeilen)


def test_falsches_wort_oder_enter_loescht_nichts(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    vorher = _quelldateien(quelle)
    antwort.append("")            # nur Enter
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    assert "uebersprungen (nicht bestaetigt)" in capsys.readouterr().out
    antwort.append("ja")          # falsches Wort
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert _quelldateien(quelle) == vorher
    assert all(z["status"] in ("geprueft", "duplikat_bestaetigt") for z in _echte(_zeilen(nachschauen, ziel)).values())


def test_ohne_terminal_wird_nichts_geloescht(baum, quelle, ziel, nachschauen, monkeypatch, capsys):
    _bis_geprueft(ziel, quelle)
    monkeypatch.delenv("FOTOSORT_EINGABE_ERZWINGEN", raising=False)
    vorher = _quelldateien(quelle)
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert "Keine Bestaetigung moeglich" in capsys.readouterr().out
    assert _quelldateien(quelle) == vorher


def test_dry_run_zeigt_liste_und_fasst_nichts_an(baum, quelle, ziel, nachschauen, capsys):
    _bis_geprueft(ziel, quelle)
    vorher = _quelldateien(quelle)
    with nachschauen(ziel) as d:
        laeufe = len(d.laeufe_liste())
    assert _cli("aufraeumen", "--ziel", ziel, "--dry-run", "--leere-ordner") == cli.OK
    aus = capsys.readouterr().out
    assert "Probelauf" in aus and "diese Dateien wuerden entfernt" in aus and str(baum["analog"]) in aus
    assert _quelldateien(quelle) == vorher
    with nachschauen(ziel) as d:
        assert len(d.laeufe_liste()) == laeufe


def test_nur_eine_quelle_waehlbar(baum, quelle, ziel, tmp_path, nachschauen, antwort, capsys):
    q2 = tmp_path / "Quelle2"
    (q2 / "k").mkdir(parents=True)
    eigen = q2 / "k" / "eigen.jpg"
    eigen.write_bytes(testbaum._JPEG + b"eigen")
    _bis_geprueft(ziel, quelle, q2)
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig", "--quelle", q2) == cli.OK
    assert not eigen.exists()
    assert baum["analog"].exists()
    zeilen = _zeilen(nachschauen, ziel)
    assert zeilen[str(eigen)]["status"] == "quelle_geloescht"
    assert zeilen[str(baum["analog"])]["status"] == "geprueft"
    capsys.readouterr()
    assert _cli("aufraeumen", "--ziel", ziel, "--quelle", tmp_path / "gibtsnicht") == cli.FEHLENDE_ANGABE
    assert "nicht bekannt" in capsys.readouterr().out


# ------------------------------------------ Pflichttests: NICHT loeschen -----


def test_ungepruefte_datei_wird_nie_geloescht(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Status kopiert (nicht geprueft): kein Befehl und keine Option loescht sie."""
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    vorher = _quelldateien(quelle)
    antwort.extend(["loeschen", "loeschen"])
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert "Nichts aufzuraeumen" in capsys.readouterr().out
    assert _quelldateien(quelle) == vorher
    # Auch die Loeschstelle selbst weigert sich bei falschem Status.
    with nachschauen(ziel) as d:
        z = d.zeile(baum["analog"])
        lesung = loeschen.frisch_lesen(baum["analog"], Path(z["zielpfad"]), False)
        with pytest.raises(loeschen.Verweigert):
            loeschen.quelldatei_entfernen(d, 99, z["quellpfad"], lesung, loeschen.WEISE_ENDGUELTIG, False)
    assert baum["analog"].exists()


def test_quelle_nach_dem_kopieren_veraendert_wird_nicht_geloescht(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Der wichtigste Verlustpfad (SPEC Abschnitt 5, 11)."""
    _bis_geprueft(ziel, quelle)
    datei = baum["aendert_sich"]
    zeilen = _zeilen(nachschauen, ziel)
    zielkopie = Path(zeilen[str(datei)]["zielpfad"])
    zielinhalt = zielkopie.read_bytes()
    neu = datei.read_bytes() + b"neue Fassung"
    datei.write_bytes(neu)
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    aus = capsys.readouterr().out
    assert "QUELLE SEIT DEM KOPIEREN GEAENDERT - nicht geloescht, neu zu kopieren: 1" in aus
    assert datei.read_bytes() == neu
    assert zielkopie.read_bytes() == zielinhalt
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert z["status"] == "analysiert" and z["hash"] == "" and z["bestaetigt_in_lauf"] is None
    assert any(e["pfad"] == str(datei) for e in _ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_SEIT_KOPIEREN_GEAENDERT))
    capsys.readouterr()
    assert _cli("bericht", "--ziel", ziel) == cli.OK
    assert "QUELLE SEIT DEM KOPIEREN GEAENDERT" in capsys.readouterr().out
    # Neu kopieren: Groesse und Aenderungsdatum sind anders, also erst scan und
    # analyse (kopieren allein stellt das fest und stellt auf "gefunden" zurueck);
    # die neue Fassung bekommt dann _1, die alte Kopie bleibt.
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    z = _zeilen(nachschauen, ziel)[str(datei)]
    assert z["status"] == "kopiert" and Path(z["zielpfad"]).name == "aendert_sich_1.jpg"
    assert zielkopie.read_bytes() == zielinhalt


def test_zielkopie_fehlt_oder_veraendert_wird_nicht_geloescht(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    zeilen = _zeilen(nachschauen, ziel)
    fehlt = Path(zeilen[str(baum["analog"])]["zielpfad"])
    fehlt.unlink()
    anders = Path(zeilen[str(baum["aendert_sich"])]["zielpfad"])
    anders.write_bytes(anders.read_bytes()[:-1] + b"X")
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    assert "Loeschung verweigert (Ziel fehlt oder weicht ab, Lesefehler): 2" in capsys.readouterr().out
    assert baum["analog"].exists() and baum["aendert_sich"].exists()
    nachher = _zeilen(nachschauen, ziel)
    assert nachher[str(baum["analog"])]["status"] == "fehler"
    assert nachher[str(baum["aendert_sich"])]["status"] == "fehler"
    assert len(_ereignisse(nachschauen, ziel, loeschen.ART_LOESCHUNG_VERWEIGERT)) == 2


def test_duplikat_mit_fehlender_oder_anderer_partnerdatei_wird_nicht_geloescht(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    zeilen = _zeilen(nachschauen, ziel)
    dups = [z for z in zeilen.values() if z["status"] == "duplikat_bestaetigt"]
    assert dups
    partner = Path(dups[0]["zielpfad"])
    partner.write_bytes(partner.read_bytes() + b"anders")
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    for d in dups:
        if d["zielpfad"] == dups[0]["zielpfad"]:
            assert Path(d["quellpfad"]).exists()
            assert _zeilen(nachschauen, ziel)[d["quellpfad"]]["status"] == "fehler"


def test_nicht_erreichbare_quelle_nichts_passiert(baum, quelle, ziel, tmp_path, nachschauen, antwort, capsys):
    q2 = tmp_path / "Quelle2"
    (q2 / "k").mkdir(parents=True)
    (q2 / "k" / "eigen.jpg").write_bytes(testbaum._JPEG + b"eigen")
    _bis_geprueft(ziel, quelle, q2)
    shutil.rmtree(q2)
    vorher = _quelldateien(quelle)
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig", "--quelle", q2) == cli.FEHLER
    aus = capsys.readouterr().out
    assert "nicht erreichbar - dort passiert nichts" in aus
    assert _quelldateien(quelle) == vorher
    assert _zeilen(nachschauen, ziel)[str(q2 / "k" / "eigen.jpg")]["status"] == "geprueft"


def test_byte_vergleich_option(baum, quelle, ziel, nachschauen, antwort, tmp_path, archiv_basis):
    _bis_geprueft(ziel, quelle)
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    konf_pfad = archiv_basis / kennung / "config.toml"
    text = konf_pfad.read_text(encoding="utf-8").replace("byte_vergleich_vor_loeschen = false", "byte_vergleich_vor_loeschen = true")
    assert "byte_vergleich_vor_loeschen = true" in text
    konf_pfad.write_text(text, encoding="utf-8")
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    assert not baum["analog"].exists()


# ------------------------------------------------- Absturz mitten drin -----


def test_absturz_mitten_im_aufraeumen_loescht_nichts_doppelt(baum, quelle, ziel, nachschauen, antwort, monkeypatch, capsys):
    """Nach der ersten Loeschung stuerzt der Lauf ab (Verbindung weg, bevor der
    Status geschrieben ist). Der Neustart traegt die Loeschung nach und loescht
    weder etwas doppelt noch etwas Falsches."""
    _bis_geprueft(ziel, quelle)
    original = os.unlink
    zaehler = {"n": 0}

    def einmal_dann_absturz(pfad, *a, **k):
        original(pfad, *a, **k)
        zaehler["n"] += 1
        if zaehler["n"] == 1:
            raise KeyboardInterrupt   # wie ein Abbruch genau nach dem Entfernen
    monkeypatch.setattr(loeschen.os, "unlink", einmal_dann_absturz)
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.ABGEBROCHEN
    monkeypatch.setattr(loeschen.os, "unlink", original)
    zeilen = _echte(_zeilen(nachschauen, ziel))
    weg = [qp for qp in zeilen if not Path(qp).exists()]
    assert len(weg) == 1
    # Die Zeile steht noch auf geprueft/duplikat_bestaetigt, aber mit festgeschriebener Frischlesung.
    assert zeilen[weg[0]]["status"] in ("geprueft", "duplikat_bestaetigt") and zeilen[weg[0]]["bestaetigt_in_lauf"] is not None
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    aus = capsys.readouterr().out
    assert "aus abgebrochenem Lauf nachgetragen: 1" in aus
    nachher = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in nachher.values()} == {"quelle_geloescht"}
    assert len(_ereignisse(nachschauen, ziel, loeschen.ART_LOESCHUNG_NACHGETRAGEN)) == 1
    assert len(_ereignisse(nachschauen, ziel, loeschen.ART_QUELLE_GELOESCHT)) == len(nachher) - 1


def test_quelle_fehlt_ohne_frischlesung_wird_nicht_nachgetragen(baum, quelle, ziel, nachschauen, antwort, capsys):
    """Fehlt die Quelle, ohne dass eine Frischlesung festgeschrieben war, ist das
    ein Fehler - nicht stillschweigend 'geloescht'."""
    _bis_geprueft(ziel, quelle)
    baum["analog"].unlink()
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.FEHLER
    z = _zeilen(nachschauen, ziel)[str(baum["analog"])]
    assert z["status"] == "fehler" and "nicht mehr vorhanden" in z["fehlergrund"]


# ------------------------------------------------------ Leere Ordner -----


def test_leere_ordner_nur_wirklich_leere(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    antwort.extend(["loeschen", "entfernen"])
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig", "--leere-ordner") == cli.OK
    aus = capsys.readouterr().out
    assert "leere Ordner entfernt:" in aus
    # Sonstiges enthaelt notizen.txt (nicht erfasst) -> bleibt samt Thumbs.db.
    assert (quelle / "Sonstiges").exists() and (quelle / "Sonstiges" / "notizen.txt").exists()
    # Ordner, deren Bilder alle weg sind, sind weg; der Wurzelordner bleibt.
    assert not (quelle / "Videos").exists()
    assert not (quelle / "Analog").exists()
    assert quelle.exists()
    assert _ereignisse(nachschauen, ziel, loeschen.ART_LEERER_ORDNER_ENTFERNT)


def test_ordner_mit_fremder_txt_bleibt_stehen(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    fremd = quelle / "Videos" / "liesmich.txt"
    fremd.write_text("nicht erfasst", encoding="utf-8")
    antwort.extend(["loeschen", "entfernen"])
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig", "--leere-ordner") == cli.OK
    assert fremd.exists() and (quelle / "Videos").exists()


def test_reste_datei_mit_echtem_typ_wird_nicht_entfernt(baum, quelle, ziel, nachschauen, antwort, tmp_path, archiv_basis, capsys):
    """'.jpg' in reste_dateien darf die Loeschregel nicht aushebeln (SPEC Abschnitt 5)."""
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    konf_pfad = archiv_basis / kennung / "config.toml"
    text = konf_pfad.read_text(encoding="utf-8").replace(
        'reste_dateien = ["Thumbs.db", ".DS_Store", "desktop.ini"]',
        'reste_dateien = ["Thumbs.db", ".DS_Store", "desktop.ini", "scan_001.tif"]',
    )
    assert "scan_001.tif" in text
    konf_pfad.write_text(text, encoding="utf-8")
    # Nichts ist geprueft, also wird keine Datei geloescht; nur Ordner-Schritt.
    antwort.extend(["entfernen"])
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig", "--leere-ordner") == cli.OK
    assert baum["analog"].exists() and (quelle / "Analog").exists()
    assert _ereignisse(nachschauen, ziel, loeschen.ART_REST_NICHT_ENTFERNT)


def test_leere_ordner_dry_run_und_papierkorb_bleibt(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    korb = _papierkorb(quelle)
    assert korb is not None
    capsys.readouterr()
    assert _cli("aufraeumen", "--ziel", ziel, "--leere-ordner", "--dry-run") == cli.OK
    aus = capsys.readouterr().out
    assert "diese leeren Ordner wuerden entfernt" in aus and str(quelle / "Videos") in aus
    assert korb.exists() and (quelle / "Videos").exists()
    antwort.append("entfernen")
    assert _cli("aufraeumen", "--ziel", ziel, "--leere-ordner") == cli.OK
    assert korb.exists() and not (quelle / "Videos").exists()


# --------------------------------------------------------- Loeschstelle -----


def test_loeschstelle_prueft_jede_bedingung(baum, quelle, ziel, nachschauen):
    _bis_geprueft(ziel, quelle)
    with nachschauen(ziel) as d:
        lauf = d.lauf_beginnen("test")
        z = d.zeile(baum["analog"])
        zp = Path(z["zielpfad"])
        gut = loeschen.frisch_lesen(baum["analog"], zp, False)
        # falscher Hash der Quelle
        falsch = loeschen.Lesung("ok", quell_hash="x" * 64, ziel_hash=gut.ziel_hash,
                                 quell_groesse=gut.quell_groesse, ziel_groesse=gut.ziel_groesse)
        with pytest.raises(loeschen.Verweigert):
            loeschen.quelldatei_entfernen(d, lauf, z["quellpfad"], falsch, loeschen.WEISE_ENDGUELTIG, False)
        # falscher Hash des Ziels
        falsch = loeschen.Lesung("ok", quell_hash=gut.quell_hash, ziel_hash="x" * 64,
                                 quell_groesse=gut.quell_groesse, ziel_groesse=gut.ziel_groesse)
        with pytest.raises(loeschen.Verweigert):
            loeschen.quelldatei_entfernen(d, lauf, z["quellpfad"], falsch, loeschen.WEISE_ENDGUELTIG, False)
        # Groesse weicht ab
        falsch = loeschen.Lesung("ok", quell_hash=gut.quell_hash, ziel_hash=gut.ziel_hash,
                                 quell_groesse=gut.quell_groesse + 1, ziel_groesse=gut.ziel_groesse)
        with pytest.raises(loeschen.Verweigert):
            loeschen.quelldatei_entfernen(d, lauf, z["quellpfad"], falsch, loeschen.WEISE_ENDGUELTIG, False)
        # unbekannte Loeschweise
        with pytest.raises(loeschen.Verweigert):
            loeschen.quelldatei_entfernen(d, lauf, z["quellpfad"], gut, "irgendwas", False)
        # Byte-Vergleich verlangt, aber nicht gemacht
        with pytest.raises(loeschen.Verweigert):
            loeschen.quelldatei_entfernen(d, lauf, z["quellpfad"], gut, loeschen.WEISE_ENDGUELTIG, True)
        assert baum["analog"].exists()
        # Alles richtig: geloescht.
        loeschen.quelldatei_entfernen(d, lauf, z["quellpfad"], gut, loeschen.WEISE_ENDGUELTIG, False)
        assert not baum["analog"].exists()
        assert d.zeile(baum["analog"])["status"] == "quelle_geloescht"


# ---------------------------------------------- echter Absturz (Prozess) -----

_KIND = '''
import os, sys, time, threading
from fotosort import loeschen, cli

original = loeschen.frisch_lesen

def langsam(quelle, zielpfad, byte_vergleich, stop=None):
    time.sleep(0.08)
    return original(quelle, zielpfad, byte_vergleich, stop)

loeschen.frisch_lesen = langsam
os.environ["FOTOSORT_EINGABE_ERZWINGEN"] = "1"
import builtins
builtins.input = lambda: "loeschen"
sys.exit(cli.main(["aufraeumen", "--ziel", sys.argv[1], "--endgueltig", "--hash-worker", "1"]))
'''


def test_prozess_abgeschossen_mitten_im_aufraeumen(tmp_path, archiv_basis):
    """Pflichttest: SIGKILL waehrend des Aufraeumens; der Neustart loescht
    nichts doppelt und nichts Falsches, und es fehlt am Ende nichts im Ziel."""
    import subprocess
    import sys
    import time

    from test_kopieren import SRC, _grosser_baum

    quelle = _grosser_baum(tmp_path / "gross", 30)
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    _bis_geprueft(ziel, quelle)
    erwartet = _zieldateien(ziel)
    skript = tmp_path / "kind.py"
    skript.write_text(_KIND, encoding="utf-8")
    kind = subprocess.Popen(
        [sys.executable, str(skript), str(ziel)], env=dict(os.environ, PYTHONPATH=str(SRC)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        frist = time.monotonic() + 60
        while time.monotonic() < frist:
            uebrig = sum(1 for p in quelle.rglob("*.JPG"))
            if uebrig <= 25:
                break
            if kind.poll() is not None:
                pytest.fail("Kindprozess war fertig, bevor er unterbrochen werden konnte")
            time.sleep(0.01)
        else:
            pytest.fail("Kindprozess kam nicht in den erwarteten Zustand")
        kind.kill()
    finally:
        kind.wait(timeout=30)
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    d = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        rows = {z["quellpfad"]: dict(z) for z in d.verbindung.execute("SELECT * FROM dateien")}
    finally:
        d.schliessen()
    # Was weg ist, war bestaetigt; was da ist, wurde nicht angeruehrt.
    for qp, z in rows.items():
        if not Path(qp).exists():
            assert z["bestaetigt_in_lauf"] is not None
            assert hashes.blake3_datei(Path(z["zielpfad"])) == z["hash"]
        else:
            assert z["status"] in ("geprueft", "quelle_geloescht") or z["bestaetigt_in_lauf"] is None
    # Neustart: alles Uebrige wird geloescht, die Luecke nachgetragen, nichts Falsches.
    os.environ["FOTOSORT_EINGABE_ERZWINGEN"] = "1"
    import builtins
    alt = builtins.input
    builtins.input = lambda: "loeschen"
    try:
        rc = _cli("aufraeumen", "--ziel", ziel, "--endgueltig")
    finally:
        builtins.input = alt
        os.environ.pop("FOTOSORT_EINGABE_ERZWINGEN", None)
    assert rc == cli.OK
    assert _zieldateien(ziel) == erwartet
    assert not list(quelle.rglob("*.JPG"))
    d = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        status = {z[0]: z[1] for z in d.verbindung.execute("SELECT status, COUNT(*) FROM dateien GROUP BY status")}
        geloescht = d.ereignisse_zaehlen(0, "x")  # nur Aufruf pruefen
        alle = d.verbindung.execute("SELECT art, COUNT(*) FROM lauf_ereignisse WHERE art IN (?, ?) GROUP BY art",
                                    (loeschen.ART_QUELLE_GELOESCHT, loeschen.ART_LOESCHUNG_NACHGETRAGEN)).fetchall()
    finally:
        d.schliessen()
    assert status == {"quelle_geloescht": 30}
    zaehler = {a: n for a, n in alle}
    assert zaehler.get(loeschen.ART_QUELLE_GELOESCHT, 0) + zaehler.get(loeschen.ART_LOESCHUNG_NACHGETRAGEN, 0) == 30
