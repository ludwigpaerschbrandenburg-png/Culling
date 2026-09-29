"""fotosort zuruecklegen: den Ordner _geloescht_<Datum> an die alten Orte
zuruecklegen (SPEC §4 Phase 5, seit v0.8).

Die oberste Regel gilt auch hier: Nichts wird ueberschrieben, und die Datei
im Ordner _geloescht_ wird nie geloescht - hoechstens nicht ueberschreibend
umbenannt. Jeder Test, der etwas bewegt, hat ein Gegenstueck, das zeigt, was
stehen bleibt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fotosort import cli, hashes, loeschen, pfade, zuruecklegen
from test_aufraeumen import _bis_geprueft, _echte, _papierkorb, _quelldateien, antwort  # noqa: F401
from test_kopieren import _cli, _ereignisse, _zeilen, _zieldateien


def _aufgeraeumt(ziel, quelle, antwort) -> tuple[dict, Path]:
    """Bis in den Ordner _geloescht_; liefert (Quelldateien vorher, Ordner)."""
    _bis_geprueft(ziel, quelle)
    vorher = _quelldateien(quelle)
    antwort.append("verschieben")
    assert _cli("aufraeumen", "--ziel", ziel) == cli.OK
    korb = _papierkorb(quelle)
    assert korb is not None
    return vorher, korb


def test_alles_kommt_an_den_alten_ort_zurueck(baum, quelle, ziel, nachschauen, antwort, capsys):
    vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    im_archiv = _zieldateien(ziel)
    zeilen = _echte(_zeilen(nachschauen, ziel))
    capsys.readouterr()
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.OK
    aus = capsys.readouterr().out
    assert "zurueckgelegt" in aus.lower()
    # Jede Datei liegt wieder an ihrem Ort, Byte fuer Byte wie vorher.
    assert _quelldateien(quelle) == vorher
    assert not korb.exists()                      # leer geworden, entfernt
    assert _zieldateien(ziel) == im_archiv        # das Archiv ist unberuehrt
    nachher = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in nachher.values()} == {"gefunden"}
    assert all(z["schreibpfad"] == "" and z["hash"] == "" for z in nachher.values())
    assert len(_ereignisse(nachschauen, ziel, zuruecklegen.ART_ZURUECKGELEGT)) == len(zeilen)
    # Der naechste Durchgang erkennt sie wieder - der Inhalt liegt schon im Archiv.
    assert _cli("scan", "--ziel", ziel) == cli.OK
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _zieldateien(ziel) == im_archiv
    assert {z["status"] for z in _echte(_zeilen(nachschauen, ziel)).values()} <= {"duplikat", "uebersprungen"}


def test_belegter_alter_ort_wird_nie_ueberschrieben(baum, quelle, ziel, nachschauen, antwort, capsys):
    vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    ort = Path(baum["analog"])
    zeile = _zeilen(nachschauen, ziel)[str(ort)]
    im_korb = Path(zeile["schreibpfad"])
    ort.write_bytes(b"inzwischen etwas anderes")
    capsys.readouterr()
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.FEHLER
    aus = capsys.readouterr().out
    assert str(ort) in aus
    assert ort.read_bytes() == b"inzwischen etwas anderes"
    assert hashes.blake3_datei(im_korb) == zeile["hash"]            # bleibt im Ordner _geloescht_
    assert _zeilen(nachschauen, ziel)[str(ort)]["status"] == "quelle_geloescht"
    assert _ereignisse(nachschauen, ziel, zuruecklegen.ART_BELEGT)
    assert korb.exists()
    # Alle anderen sind zurueck.
    rest = {rel: h for rel, h in vorher.items() if (quelle / rel) != ort}
    jetzt = _quelldateien(quelle)
    assert all(jetzt.get(rel) == h for rel, h in rest.items())


def test_ohne_umbenennen_wird_kopiert_und_das_original_bleibt(baum, quelle, ziel, nachschauen, antwort, monkeypatch, capsys):
    """exFAT kann kein nicht ueberschreibendes Umbenennen: zurueckkopieren,
    Kopie zuruecklesen - die Datei im Ordner _geloescht_ bleibt liegen. Ihre
    Zeile gehoert jetzt der Kopie am alten Ort; die Datei im Ordner hat keine
    mehr, und das Programm fasst sie nie an."""
    vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    im_korb = _quelldateien(korb)

    def kein_umbenennen(von, nach):
        raise pfade.KeinNoReplace("exFAT")

    monkeypatch.setattr(zuruecklegen.pfade, "umbenennen_ohne_ueberschreiben", kein_umbenennen)
    capsys.readouterr()
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.OK
    assert "selbst" in capsys.readouterr().out          # Hinweis: Ordner selbst loeschen
    assert _quelldateien(korb) == im_korb               # nichts entfernt
    jetzt = _quelldateien(quelle)
    for rel, h in vorher.items():
        assert jetzt.get(rel) == h
    assert _ereignisse(nachschauen, ziel, zuruecklegen.ART_KOPIERT)
    # Der naechste Scan uebergeht den Ordner _geloescht_ - nichts darin bekommt eine Zeile.
    assert _cli("scan", "--ziel", ziel) == cli.OK
    assert not any(loeschen.ist_papierkorb(Path(q).relative_to(quelle).parts[0])
                   for q in _zeilen(nachschauen, ziel))


def test_kaputte_kopie_wird_zurueckgenommen(baum, quelle, ziel, nachschauen, antwort, monkeypatch):
    vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    monkeypatch.setattr(zuruecklegen.pfade, "umbenennen_ohne_ueberschreiben",
                        lambda von, nach: (_ for _ in ()).throw(pfade.KeinNoReplace("exFAT")))
    monkeypatch.setattr(zuruecklegen.hashes, "blake3_datei", lambda pfad, *a: "0" * 64)
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.FEHLER
    # Keine halbe oder falsche Kopie am alten Ort; alles liegt weiter im Ordner.
    assert all(not (quelle / rel).exists() for rel in _quelldateien(korb))
    assert {z["status"] for z in _echte(_zeilen(nachschauen, ziel)).values()} == {"quelle_geloescht"}


def test_probelauf_und_fremde_dateien_im_ordner(baum, quelle, ziel, nachschauen, antwort, capsys):
    vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    fremd = korb / "notiz.txt"
    fremd.write_text("vom Nutzer hineingelegt", encoding="utf-8")
    im_korb = _quelldateien(korb)
    capsys.readouterr()
    assert _cli("zuruecklegen", "--ziel", ziel, "--dry-run") == cli.OK
    assert "wuerden" in capsys.readouterr().out
    assert _quelldateien(korb) == im_korb
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.OK
    assert fremd.read_text(encoding="utf-8") == "vom Nutzer hineingelegt"   # ohne Zeile: unberuehrt
    assert korb.exists() and list(korb.rglob("*")) == [fremd]


def test_endgueltig_geloeschtes_bleibt_unberuehrt(baum, quelle, ziel, nachschauen, antwort, capsys):
    _bis_geprueft(ziel, quelle)
    antwort.append("loeschen")
    assert _cli("aufraeumen", "--ziel", ziel, "--endgueltig") == cli.OK
    vorher = _zeilen(nachschauen, ziel)
    capsys.readouterr()
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.OK
    assert "nichts" in capsys.readouterr().out.lower()
    assert _zeilen(nachschauen, ziel) == vorher


def test_von_hand_zurueckgeholte_datei_nimmt_der_scan_wieder_auf(baum, quelle, ziel, nachschauen, antwort):
    """Pruefer-Befund (v0.8): Liegt eine Datei im Status quelle_geloescht
    wieder an ihrem Ort - von Hand zurueckgeholt oder das Zuruecklegen wurde
    zwischen Umbenennen und Datenbank unterbrochen -, nimmt der naechste Scan
    sie wieder auf, auch wenn Groesse und Aenderungszeit gleich sind."""
    import os
    _vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    ort = Path(baum["analog"])
    zeile = _zeilen(nachschauen, ziel)[str(ort)]
    im_korb = Path(zeile["schreibpfad"])
    os.link(im_korb, ort)            # wie von Hand zurueckgeholt: gleicher Inhalt, gleiche Zeit
    os.unlink(im_korb)
    assert _cli("scan", "--ziel", ziel) == cli.OK
    neu = _zeilen(nachschauen, ziel)[str(ort)]
    assert neu["status"] == "gefunden" and neu["schreibpfad"] == "" and neu["hash"] == ""
    assert _cli("analyse", "--ziel", ziel) == cli.OK
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _zeilen(nachschauen, ziel)[str(ort)]["status"] == "duplikat"   # Inhalt liegt schon im Archiv
    assert ort.exists()


def test_leere_ordner_nur_im_ordner_geloescht_nie_hinter_einer_verknuepfung(baum, quelle, ziel, antwort, tmp_path):
    import os
    _vorher, korb = _aufgeraeumt(ziel, quelle, antwort)
    draussen = tmp_path / "draussen"
    (draussen / "leer").mkdir(parents=True)
    try:
        os.symlink(draussen, korb / "verlinkt", target_is_directory=True)
    except OSError:
        pytest.skip("Verknuepfungen nicht erlaubt")
    assert _cli("zuruecklegen", "--ziel", ziel) == cli.OK
    assert (draussen / "leer").is_dir()            # hinter der Verknuepfung wird nichts entfernt
