"""Python-Wechsel unter einem bestehenden Archiv (v0.14).

Bis v0.13 lag dem Windows-Paket Python 3.12 bei, seit v0.14 Python 3.15. Ein
Archiv, das mit dem alten Paket begonnen wurde, muss sich mit dem neuen
weiterfuehren lassen. Ab Python 3.13 behandelt pathlib manche Windows-Pfade
anders. Schriebe das neue Python einen gespeicherten Pfad anders als das alte,
saehe ein neuer Scan dieselben Dateien als neu, die eigenen Kopien gaelten als
"schon im Archiv" - und die Originale wuerden nie aufgeraeumt.

Die beiden Pythons kommen aus FOTOSORT_PYTHON_ALT und FOTOSORT_PYTHON_NEU (CI:
Job "Wechsel 3.12 -> 3.15" unter Windows). Ohne diese Angaben laufen beide
Haelften mit dem Python der Tests, jeder Schritt in einem eigenen Prozess.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import testbaum
from fotosort import hashes
from test_kopieren import _zeilen, _zieldateien

SRC = Path(__file__).resolve().parents[1] / "src"


def _python(name: str) -> str:
    return os.environ.get(name) or sys.executable


def _fotosort(python: str, *argumente, eingabe: str | None = None) -> str:
    """Ein Befehl in einem eigenen Prozess mit genau diesem Python."""
    umgebung = dict(os.environ)
    umgebung["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), umgebung.get("PYTHONPATH", "")) if p)
    umgebung["PYTHONIOENCODING"] = "utf-8"
    if eingabe is not None:
        umgebung["FOTOSORT_EINGABE_ERZWINGEN"] = "1"
    befehl = [python, "-m", "fotosort", *(str(a) for a in argumente)]
    lauf = subprocess.run(befehl, env=umgebung, input=eingabe, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    assert lauf.returncode == 0, f"{' '.join(befehl)} -> {lauf.returncode}\n{lauf.stdout}\n{lauf.stderr}"
    return lauf.stdout


def _version(python: str) -> str:
    return subprocess.run([python, "-c", "import sys; print(sys.version.split()[0])"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _inhalte(ordner: Path) -> Counter:
    """Inhalt (Hash) aller echten Dateien unter ordner, mehrfach Vorkommendes mehrfach."""
    return Counter(hashes.blake3_datei(p) for p in ordner.rglob("*")
                   if p.is_file() and not p.is_symlink() and ".fotosortierer" not in p.parts)


def test_archiv_vom_alten_python_mit_dem_neuen_weiterfuehren(baum, quelle, ziel, nachschauen):
    alt, neu = _python("FOTOSORT_PYTHON_ALT"), _python("FOTOSORT_PYTHON_NEU")
    print(f"alt: {alt} ({_version(alt)}), neu: {neu} ({_version(neu)})")
    vorher = _inhalte(quelle)

    # 1. Altes Python: erfassen, lesen, kopieren - wie mit dem Paket bis v0.13.
    _fotosort(alt, "scan", "--quelle", quelle, "--ziel", ziel)
    _fotosort(alt, "analyse", "--ziel", ziel)
    _fotosort(alt, "kopieren", "--ziel", ziel)
    nach_alt = _zeilen(nachschauen, ziel)
    ziel_nach_alt = _zieldateien(ziel)
    kopiert = {p for p, z in nach_alt.items() if z["status"] == "kopiert"}
    assert kopiert, "das alte Python hat nichts kopiert"

    # 2. Dazwischen kommt ein neues Bild in die Quelle.
    nachzuegler = quelle / "Nachzuegler" / "neu_nach_dem_wechsel.jpg"
    nachzuegler.parent.mkdir()
    nachzuegler.write_bytes(testbaum._JPEG + b"nach dem Wechsel")
    vorher[hashes.blake3_datei(nachzuegler)] += 1

    # 3. Neues Python: noch einmal erfassen. Dieselben Pfade, keine neuen Zeilen
    #    ausser dem Nachzuegler, und nichts am Stand des alten Laufs geaendert.
    _fotosort(neu, "scan", "--quelle", quelle, "--ziel", ziel)
    zeilen = _zeilen(nachschauen, ziel)
    neue = set(zeilen) - set(nach_alt)
    assert set(nach_alt) <= set(zeilen)
    assert len(neue) == 1 and next(iter(neue)).endswith("neu_nach_dem_wechsel.jpg"), neue
    for pfad, z in nach_alt.items():
        assert (zeilen[pfad]["status"], zeilen[pfad]["zielpfad"], zeilen[pfad]["hash"]) == (
            z["status"], z["zielpfad"], z["hash"]), pfad

    # 4. Weiter mit dem neuen Python: Die eigenen Kopien sind kein "schon im
    #    Archiv", es wird nur der Nachzuegler kopiert, die Pruefung findet alles.
    _fotosort(neu, "analyse", "--ziel", ziel)
    _fotosort(neu, "kopieren", "--ziel", ziel)
    _fotosort(neu, "pruefen", "--ziel", ziel)
    zeilen = _zeilen(nachschauen, ziel)
    for pfad in kopiert:
        assert zeilen[pfad]["status"] == "geprueft" and not zeilen[pfad]["schon_im_archiv"], pfad
    (neuer,) = neue
    assert zeilen[neuer]["status"] == "geprueft"
    ziel_jetzt = _zieldateien(ziel)
    assert set(ziel_nach_alt) <= set(ziel_jetzt) and len(ziel_jetzt) == len(ziel_nach_alt) + 1
    assert all(ziel_jetzt[p] == h for p, h in ziel_nach_alt.items())
    zum_aufraeumen = {p for p, z in zeilen.items() if z["status"] in ("geprueft", "duplikat_bestaetigt")}

    # 5. Aufraeumen mit dem neuen Python: alles, was geprueft ist, wandert in den
    #    Ordner _geloescht_ - und kein Inhalt geht verloren.
    _fotosort(neu, "aufraeumen", "--ziel", ziel, eingabe="verschieben\n" * 10)
    zeilen = _zeilen(nachschauen, ziel)
    for pfad in zum_aufraeumen:
        assert zeilen[pfad]["status"] == "quelle_geloescht", pfad
    im_ziel = set(_zieldateien(ziel).values())
    assert all(z["hash"] in im_ziel for z in zeilen.values() if z["status"] == "quelle_geloescht")
    nachher = _inhalte(quelle)
    for inhalt, anzahl in vorher.items():
        assert nachher[inhalt] >= anzahl, "eine Datei der Quelle ist verschwunden"
