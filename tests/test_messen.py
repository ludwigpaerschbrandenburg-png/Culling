"""Phase 6: fotosort messen (SPEC Abschnitt 7 und 8)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fotosort import cli, db, messen, pfade
from test_kopieren import _cli


def _inhalt(ordner: Path) -> list[str]:
    return sorted(str(p.relative_to(ordner)) for p in ordner.rglob("*"))


def test_messen_laesst_nichts_zurueck_und_legt_kein_archiv_an(baum, quelle, ziel, capsys):
    assert _cli("messen", "--quelle", quelle, "--ziel", ziel, "--mb", "1") == cli.OK
    aus = capsys.readouterr().out
    assert "Vorschlag fuer die config.toml" in aus and "kopier_worker" in aus
    assert "Lesetempo wird deshalb nicht gemessen" in aus      # Testbaum ist winzig
    assert _inhalt(ziel) == []
    assert not db.archiv_id_vorhanden(ziel)


def test_messen_misst_lesen_bei_genug_daten(tmp_path, ziel, capsys):
    quelle = tmp_path / "gross"
    quelle.mkdir()
    for i in range(6):
        (quelle / f"v{i}.bin").write_bytes(os.urandom(1024 * 1024) * 4)   # 6 x 4 MB
    e = messen.ausfuehren(quelle, ziel, None, mb=2)
    assert e.lesen_gemessen and e.schreiben_gemessen
    assert [s.worker for s in e.stufen] == list(messen.STUFEN)
    assert all(s.lesen_mb_s and s.lesen_mb_s > 0 for s in e.stufen)
    assert e.kopier_worker in messen.STUFEN and e.hash_worker in messen.STUFEN
    assert e.profil in ("hdd", "ssd", "netzwerk")
    assert _inhalt(ziel) == [] and _inhalt(quelle) == [f"v{i}.bin" for i in range(6)]


def test_messen_raeumt_auch_nach_fehler_auf(baum, quelle, ziel, monkeypatch, capsys):
    original = messen._schreiben

    def kaputt(ordner, worker, gesamt, stop, angelegt):
        original(ordner, worker, gesamt, stop, angelegt)      # legt Dateien an
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(messen, "_schreiben", kaputt)
    with pytest.raises(OSError):
        messen.ausfuehren(quelle, ziel, None, mb=1)
    assert _inhalt(ziel) == []


def test_messen_abbruch_raeumt_auf(baum, quelle, ziel, monkeypatch, capsys):
    monkeypatch.setattr(messen, "_schreiben", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert _cli("messen", "--quelle", quelle, "--ziel", ziel, "--mb", "1") == cli.ABGEBROCHEN
    assert "Messordner wurde entfernt" in capsys.readouterr().out
    assert _inhalt(ziel) == []


def test_messen_unbekannte_quelle_oder_ziel(tmp_path, ziel, quelle, capsys):
    assert _cli("messen", "--quelle", tmp_path / "nix", "--ziel", ziel) == cli.FEHLER
    assert _cli("messen", "--quelle", quelle, "--ziel", tmp_path / "nix") == cli.FEHLER


def test_empfehlung_kleinste_zahl_nahe_am_besten_wert(tmp_path, monkeypatch):
    e = messen.Ergebnis(stufen=[
        messen.Stufe(1, lesen_mb_s=50, schreiben_mb_s=100),
        messen.Stufe(2, lesen_mb_s=100, schreiben_mb_s=190),
        messen.Stufe(4, lesen_mb_s=400, schreiben_mb_s=200),
        messen.Stufe(8, lesen_mb_s=410, schreiben_mb_s=205),
    ])
    messen.empfehlung(e, tmp_path, tmp_path)
    assert e.kopier_worker == 2 and e.hash_worker == 4 and e.profil == "hdd"
    monkeypatch.setattr(messen.pfade, "ist_netzpfad", lambda p: True)
    messen.empfehlung(e, tmp_path, tmp_path)
    assert e.profil == "netzwerk" and "Netzlaufwerk" in e.hinweis


def test_messen_kennt_keinen_lauf_und_braucht_kein_exiftool(baum, quelle, ziel, monkeypatch, capsys):
    monkeypatch.setattr(cli, "exiftool_finden", lambda konf=None: (None, "nirgends"))
    assert _cli("messen", "--quelle", quelle, "--ziel", ziel, "--mb", "1") == cli.OK
