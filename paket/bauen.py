"""Das Windows-Paket bauen - ohne PyInstaller, ohne eigene exe-Dateien.

Aus dem Test von v0.5: Norton prueft jede selbst gebaute exe bei jedem Start
und haelt sie bis zu 60 Sekunden fest. Deshalb startet im Paket nur noch das
offizielle, von der Python Software Foundation signierte Python - dasselbe
Programm, mit dem ein Python-Skript sonst auch laeuft:

  fotosort\\
    start.bat        oeffnet das Fenster: python\\pythonw.exe (ohne Konsole)
    fotosort.bat     Befehle mit Ausgabe: python\\python.exe
    LIESMICH.md, VERSION.txt
    python\\          "Windows embeddable package" (64 Bit) von python.org,
                     unveraendert bis auf python312._pth (Suchpfad ..\\lib)
    lib\\             fotosort, fotosort_start.py und die Bibliotheken; Qt nur mit
                     QtCore, QtGui, QtWidgets; alles vorkompiliert
    exiftool\\        ExifTool von exiftool.org: exiftool_files mit perl.exe und
                     exiftool.pl - ohne den Starter exiftool.exe, perl.exe wird
                     direkt gestartet (metadaten.exiftool_befehl)

Aufruf (auf jedem System, auch unter Linux; braucht Internet und Python 3.12):
    python paket/bauen.py --exiftool build/exiftool [--ausgabe build/paket]

Ergebnis: <ausgabe>/fotosort/. Der Bau bricht ab, wenn eine Pruefsumme nicht
stimmt, ein fremdes Programm (.exe) im Paket liegt oder eine Bibliothek fehlt,
die eine der Dateien braucht (paketinhalt.py).
"""

from __future__ import annotations

import argparse
import compileall
import hashlib
import py_compile
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import paketinhalt

WURZEL = Path(__file__).resolve().parent.parent

PYTHON_VERSION = "3.12.10"      # die letzte 3.12 mit fertigen Windows-Dateien, wie in den Tests
PYTHON_ZIP = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"
# Pruefsumme der Datei von python.org. Die Seite der Version nennt MD5
# fe8ef205f2e9c3ba44d0cf9954e1abd3; die Datei wurde damit geprueft und ihre
# SHA-256 hier festgehalten.
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
PTH = "python312._pth"
BIBLIOTHEKEN = WURZEL / "paket" / "windows-bibliotheken.txt"

# Was von PySide6 bleibt: nur die drei Qt-Module, die das Fenster braucht.
PYSIDE_DATEIEN = {
    "__init__.py", "_config.py", "_git_pyside_version.py",
    "QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd",
    "pyside6.abi3.dll", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
}
PYSIDE_ORDNER = {"support"}
PYSIDE_PLUGINS = {
    "platforms/qwindows.dll",            # das normale Windows-Fenster
    "platforms/qoffscreen.dll",          # ohne Bildschirm (Paketpruefung in der CI)
    "styles/qmodernwindowsstyle.dll",    # Windows-11-Grundstil unter dem eigenen Stylesheet
}
# Microsoft-C++-Laufzeit, von den Qt-Dateien gebraucht; ein frischer PC hat sie oft nicht.
LAUFZEIT_PRAEFIXE = ("msvcp140", "vcruntime140", "concrt140")


def _laden(url: str, ziel: Path, versuche: int = 3) -> None:
    fehler: Exception | None = None
    for versuch in range(1, versuche + 1):
        try:
            anfrage = urllib.request.Request(url, headers={"User-Agent": "fotosort-paketbau"})
            with urllib.request.urlopen(anfrage, timeout=120) as antwort:
                ziel.write_bytes(antwort.read())
            return
        except Exception as f:  # noqa: BLE001 - jeder Netzfehler wird wiederholt
            fehler = f
            print(f"  Versuch {versuch}/{versuche} fehlgeschlagen: {url} ({f})", flush=True)
            time.sleep(5 * versuch)
    raise SystemExit(f"Nicht geladen: {url} ({fehler})")


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def python_einrichten(python: Path, zwischenablage: Path) -> None:
    """Das eingebettete Python von python.org holen, Pruefsumme pruefen,
    auspacken und den Suchpfad um ..\\lib ergaenzen (sonst nichts aendern)."""
    zwischenablage.mkdir(parents=True, exist_ok=True)
    zip_datei = zwischenablage / PYTHON_ZIP
    if not zip_datei.is_file() or _sha256(zip_datei) != PYTHON_SHA256:
        print(f"Lade {PYTHON_URL}", flush=True)
        _laden(PYTHON_URL, zip_datei)
    summe = _sha256(zip_datei)
    if summe != PYTHON_SHA256:
        raise SystemExit(f"Pruefsumme von {PYTHON_ZIP} stimmt nicht: {summe} statt {PYTHON_SHA256}")
    with zipfile.ZipFile(zip_datei) as zf:
        zf.extractall(python)
    pth = python / PTH
    zeilen = pth.read_text(encoding="utf-8").splitlines()
    if "python312.zip" not in zeilen or "." not in zeilen:
        raise SystemExit(f"{PTH} sieht anders aus als erwartet: {zeilen}")
    # Kein "import site": Es gelten genau diese Pfade, nichts aus dem System
    # des Nutzers (kein PYTHONPATH, keine Benutzer-Pakete) - das eingebettete
    # Python laeuft dadurch abgeschottet.
    pth.write_text("python312.zip\r\n.\r\n..\\lib\r\n", encoding="ascii")
    print(f"Python {PYTHON_VERSION} (eingebettet, Pruefsumme stimmt) unter {python}")


def bibliotheken_installieren(lib: Path) -> None:
    """Die Bibliotheken fuer Windows 64 Bit / Python 3.12 nach lib\\ - genau die
    Versionen und Dateien aus windows-bibliotheken.txt (Pruefsummen)."""
    befehl = [
        sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
        "--target", str(lib), "--platform", "win_amd64", "--python-version", "3.12", "--implementation", "cp",
        "--only-binary=:all:", "--no-compile", "--no-deps", "--require-hashes", "-r", str(BIBLIOTHEKEN),
    ]
    print(" ".join(befehl), flush=True)
    subprocess.run(befehl, check=True)


def fotosort_kopieren(lib: Path) -> None:
    shutil.copytree(WURZEL / "src" / "fotosort", lib / "fotosort",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(WURZEL / "paket" / "fotosort_start.py", lib / "fotosort_start.py")


def _weg(pfad: Path) -> int:
    if not pfad.exists():
        return 0
    if pfad.is_dir():
        n = sum(1 for p in pfad.rglob("*") if p.is_file())
        shutil.rmtree(pfad)
        return n
    pfad.unlink()
    return 1


def kuerzen(lib: Path) -> int:
    """Alles entfernen, was das Programm nicht braucht - allem voran jedes
    Programm (.exe), das pip oder PySide6 mitbringt."""
    weg = _weg(lib / "bin")                       # Startprogramme von pip (pygmentize.exe, pyside6-*.exe ...)
    pyside = lib / "PySide6"
    for p in list(pyside.iterdir()):
        if p.is_dir():
            if p.name == "plugins":
                continue
            if p.name not in PYSIDE_ORDNER:
                weg += _weg(p)
        elif p.name not in PYSIDE_DATEIEN and not p.name.lower().startswith(LAUFZEIT_PRAEFIXE):
            weg += _weg(p)
    plugins = pyside / "plugins"
    for p in sorted(plugins.rglob("*"), reverse=True):
        rel = p.relative_to(plugins).as_posix()
        if p.is_file() and rel not in PYSIDE_PLUGINS:
            weg += _weg(p)
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    shiboken = lib / "shiboken6"
    for name in ("include", "lib"):
        weg += _weg(shiboken / name)
    for p in list(shiboken.iterdir()):
        if p.is_file() and p.suffix.lower() == ".dll" and p.name.lower().startswith(("vcamp140", "vccorlib140", "vcomp140")):
            weg += _weg(p)
    for muster in ("*.exe", "*.pyi", "*.lib", "*.pyc"):
        for p in list(lib.rglob(muster)):
            weg += _weg(p)
    for p in sorted(lib.rglob("__pycache__"), reverse=True):
        weg += _weg(p)
    return weg


def vorkompilieren(lib: Path) -> None:
    """Vorkompilieren, damit der erste Start schnell ist und nichts in den
    Programmordner geschrieben werden muss. "unchecked-hash": gilt unabhaengig
    vom Datum der Dateien (ZIP-Entpacken aendert es). Die Dateinamen im
    Bytecode sind relativ zu lib\\ - Fehlermeldungen finden ihre Zeilen ueber
    den Suchpfad trotzdem."""
    if sys.version_info[:2] != (3, 12):
        print(f"Hinweis: nicht vorkompiliert (baue mit Python {sys.version.split()[0]}, "
              "das Paket enthaelt 3.12). Python kompiliert dann beim ersten Start.")
        return
    ok = compileall.compile_dir(
        str(lib), quiet=1, workers=0, stripdir=str(lib),
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    if not ok:
        raise SystemExit("Vorkompilieren fehlgeschlagen.")


def exiftool_uebernehmen(quelle: Path, ziel: Path) -> None:
    """ExifTool ohne den Starter: exiftool_files (perl.exe, exiftool.pl,
    Bibliotheken, Lizenzen) und die Textdateien."""
    if not (quelle / "exiftool_files" / "perl.exe").is_file() or not (quelle / "exiftool_files" / "exiftool.pl").is_file():
        raise SystemExit(f"In {quelle} fehlt exiftool_files mit perl.exe und exiftool.pl.")
    ziel.mkdir(parents=True)
    shutil.copytree(quelle / "exiftool_files", ziel / "exiftool_files")
    for txt in quelle.glob("*.txt"):
        shutil.copyfile(txt, ziel / txt.name)
    print(f"ExifTool uebernommen aus {quelle} (perl.exe direkt, ohne Starter)")


def startdateien(paket: Path, version: str) -> None:
    for name in ("start.bat", "fotosort.bat"):
        # Zeilenenden immer CRLF: cmd.exe verstolpert sich sonst an Sprungmarken.
        text = (WURZEL / name).read_text(encoding="ascii").replace("\r\n", "\n").replace("\n", "\r\n")
        (paket / name).write_bytes(text.encode("ascii"))
    shutil.copyfile(WURZEL / "LIESMICH.md", paket / "LIESMICH.md")
    (paket / "VERSION.txt").write_text(
        f"fotosort {version}\r\nPython {PYTHON_VERSION} (python.org, Windows embeddable package, 64 Bit)\r\n",
        encoding="utf-8",
    )


def uebersicht(paket: Path) -> None:
    for ordner in sorted(p for p in paket.iterdir() if p.is_dir()):
        dateien = [p for p in ordner.rglob("*") if p.is_file()]
        print(f"  {ordner.name + chr(92):<10} {len(dateien):6d} Dateien  {sum(p.stat().st_size for p in dateien) / 1e6:7.1f} MB")
    alle = [p for p in paket.rglob("*") if p.is_file()]
    print(f"  gesamt     {len(alle):6d} Dateien  {sum(p.stat().st_size for p in alle) / 1e6:7.1f} MB")
    print("  Programme:", ", ".join(paketinhalt.programme(paket)))


def bauen(ausgabe: Path, exiftool: Path) -> Path:
    sys.path.insert(0, str(WURZEL / "src"))
    from fotosort import __version__

    paket = ausgabe / "fotosort"
    shutil.rmtree(paket, ignore_errors=True)
    paket.mkdir(parents=True)
    python_einrichten(paket / "python", ausgabe / "downloads")
    lib = paket / "lib"
    bibliotheken_installieren(lib)
    fotosort_kopieren(lib)
    print(f"Gekuerzt: {kuerzen(lib)} Dateien entfernt (Qt-Module, Werkzeuge, Programme, Kopfdateien)")
    vorkompilieren(lib)
    exiftool_uebernehmen(exiftool, paket / "exiftool")
    startdateien(paket, __version__)

    fremd = [p for p in paketinhalt.programme(paket) if p not in paketinhalt.ERLAUBTE_PROGRAMME]
    if fremd:
        raise SystemExit("Fremde Programme im Paket: " + ", ".join(fremd))
    fehler, hinweise = paketinhalt.fehlende_abhaengigkeiten(paket)
    for h in hinweise:
        print("  Hinweis:", h)
    if fehler:
        raise SystemExit("Fehlende Bibliotheken:\n  " + "\n  ".join(fehler))
    print(f"Paket fotosort {__version__} liegt unter {paket}")
    uebersicht(paket)
    return paket


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exiftool", type=Path, required=True, help="Ordner von paket/exiftool_holen.py (mit exiftool_files)")
    ap.add_argument("--ausgabe", type=Path, default=WURZEL / "build" / "paket")
    args = ap.parse_args()
    bauen(args.ausgabe.resolve(), args.exiftool.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
