"""Das gepackte Programm wirklich ausprobieren (in GitHub Actions unter
Windows, lokal auch unter Linux): startet es, findet es sein mitgeliefertes
ExifTool, gibt es --version aus, und laeuft der kuenstliche Testbaum einmal
durch scan, analyse, kopieren und pruefen?

Aufruf:
    python paket/pruefen.py <paketordner> <arbeitsordner>

Rueckgabe 0, wenn alles stimmt; sonst 1 mit Begruendung. Es werden nur
Dateien im Arbeitsordner angelegt (Testbaum, Ziel, Datenbank).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent


def _lauf(befehl: list[str], umgebung: dict, cwd: Path) -> tuple[int, str]:
    print("$", " ".join(befehl), flush=True)
    aus = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=umgebung, cwd=cwd, timeout=600)
    text = aus.stdout + aus.stderr
    print(text[-4000:], flush=True)
    return aus.returncode, text


def main() -> int:
    # Windows-Konsole (cp1252) kann nicht jedes Zeichen der Programmausgabe
    # darstellen: eigene Ausgabe auf UTF-8 mit Ersatzzeichen umstellen.
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) != 3:
        print("Aufruf: pruefen.py <paketordner> <arbeitsordner>")
        return 2
    paket = Path(sys.argv[1]).resolve()
    arbeit = Path(sys.argv[2]).resolve()
    exe = paket / ("fotosort.exe" if sys.platform.startswith("win") else "fotosort")
    exiftool = paket / "exiftool" / ("exiftool.exe" if sys.platform.startswith("win") else "exiftool")
    fehler: list[str] = []
    if not exe.is_file():
        return _ende([f"Programm fehlt: {exe}"])
    if not exiftool.is_file():
        fehler.append(f"mitgeliefertes ExifTool fehlt: {exiftool}")
    if sys.platform.startswith("win") and not (paket / "exiftool" / "exiftool_files").is_dir():
        fehler.append("Ordner exiftool_files (Perl-Bibliotheken) fehlt neben exiftool.exe")
    for name in ("fotosort.bat", "start.bat", "LIESMICH.md", "VERSION.txt"):
        if not (paket / name).is_file():
            fehler.append(f"{name} fehlt im Paket")

    shutil.rmtree(arbeit, ignore_errors=True)
    arbeit.mkdir(parents=True)
    # Das Programm darf ExifTool NUR im Paket finden: keine Umgebungsvariable,
    # kein ExifTool ueber PATH.
    umgebung = {k: v for k, v in os.environ.items() if k not in ("FOTOSORT_EXIFTOOL", "FOTOSORT_ZIEL")}
    umgebung["FOTOSORT_DATENBANK"] = str(arbeit / "datenbank")
    umgebung["PYTHONUTF8"] = "1"   # das Programm schreibt in die Rohrleitung als UTF-8
    umgebung["PATH"] = os.pathsep.join(
        p for p in umgebung.get("PATH", "").split(os.pathsep) if shutil.which("exiftool", path=p) is None
    )

    rc, text = _lauf([str(exe), "--version"], umgebung, arbeit)
    if rc != 0 or not re.search(r"^fotosort \d+\.\d+", text, re.M):
        fehler.append("--version nennt keine Programmversion")
    if not re.search(r"^ExifTool \d+\.\d+ \(.*mitgeliefert\)", text, re.M):
        fehler.append("--version findet das mitgelieferte ExifTool nicht")

    # Testbaum erzeugen (braucht ExifTool: hier ausdruecklich das aus dem Paket).
    erzeuger = dict(umgebung, FOTOSORT_EXIFTOOL=str(exiftool), PYTHONPATH=str(WURZEL / "src"))
    rc, text = _lauf([sys.executable, str(WURZEL / "tests" / "testbaum.py"), str(arbeit / "baum")], erzeuger, WURZEL)
    if rc != 0:
        return _ende(fehler + ["Testbaum liess sich nicht erzeugen"])
    quelle = arbeit / "baum" / "Quelle"
    ziel = arbeit / "Ziel"

    schritte = [
        (["scan", "--ziel", str(ziel), "--quelle", str(quelle), "--ziel-anlegen"], "Dateien gesamt:"),
        (["analyse", "--ziel", str(ziel)], "ILCE-7CM2"),
        (["kopieren", "--ziel", str(ziel)], "kopiert:"),
        (["pruefen", "--ziel", str(ziel)], "geprueft (Zieldatei stimmt):"),
        (["status", "--ziel", str(ziel)], "Aktuelle Phase: 5"),
    ]
    for argumente, erwartet in schritte:
        rc, text = _lauf([str(exe), *argumente], umgebung, arbeit)
        if rc != 0:
            fehler.append(f"{argumente[0]}: Rueckgabewert {rc}")
        if erwartet not in text:
            fehler.append(f"{argumente[0]}: '{erwartet}' fehlt in der Ausgabe")
    if not any(p.is_file() and ".fotosortierer" not in p.parts for p in ziel.rglob("*")):
        fehler.append("im Ziel liegen keine kopierten Dateien")
    return _ende(fehler)


def _ende(fehler: list[str]) -> int:
    if fehler:
        print("PAKETPRUEFUNG FEHLGESCHLAGEN:")
        for f in fehler:
            print("  -", f)
        return 1
    print("PAKETPRUEFUNG BESTANDEN: Programm startet, findet sein ExifTool und laeuft durch scan, analyse, kopieren, pruefen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
