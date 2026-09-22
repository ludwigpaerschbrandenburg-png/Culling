"""Das eigenstaendige Programm bauen (PyInstaller, Ordner-Variante) und den
Paketordner zusammenstellen.

Aufruf (im Repository-Ordner, mit installiertem fotosort und PyInstaller):
    python paket/bauen.py --exiftool <ordner mit exiftool.exe und exiftool_files> [--ausgabe build/paket]

Ergebnis: <ausgabe>/fotosort/ mit fotosort.exe (das Fenster, PySide6, ohne Konsole) und
fotosort-konsole.exe (Befehle mit Ausgabe; unter Linux ohne .exe), _internal/ (Python, Qt
und Bibliotheken), exiftool/ (mitgeliefertes ExifTool), fotosort.bat, start.bat, LIESMICH.md,
VERSION.txt.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent


def bauen(ausgabe: Path, exiftool: Path | None) -> Path:
    sys.path.insert(0, str(WURZEL / "src"))
    from fotosort import __version__

    dist = ausgabe / "dist"
    # Was hinein muss (zwei Programme, gemeinsamer Ordner _internal, Seite der
    # Oberflaeche, Zeitzonen, Fensterbibliotheken) steht in paket/fotosort.spec.
    befehl = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(ausgabe / "work"),
        str(WURZEL / "paket" / "fotosort.spec"),
    ]
    print(" ".join(befehl))
    subprocess.run(befehl, check=True)
    paket = dist / "fotosort"
    endung = ".exe" if sys.platform.startswith("win") else ""
    for name in ("fotosort", "fotosort-konsole"):
        exe = paket / (name + endung)
        if not exe.is_file():
            raise SystemExit(f"PyInstaller hat {exe} nicht erzeugt.")
    for name in ("index.html", "fonts.css", "fonts/Inter-latin.woff2", "fonts/Inter-Regular.ttf"):
        if not (paket / "_internal" / "fotosort" / "oberflaeche" / "static" / name).is_file():
            raise SystemExit(f"Die Seite der Oberflaeche (static/{name}) fehlt im Paket.")

    if exiftool is not None:
        ziel = paket / "exiftool"
        shutil.rmtree(ziel, ignore_errors=True)
        shutil.copytree(exiftool, ziel)
        print(f"ExifTool uebernommen aus {exiftool}")
    for name in ("fotosort.bat", "start.bat", "LIESMICH.md"):
        shutil.copyfile(WURZEL / name, paket / name)
    (paket / "VERSION.txt").write_text(f"fotosort {__version__}\n", encoding="utf-8")
    print(f"Paket liegt unter {paket}")
    return paket


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exiftool", type=Path, default=None, help="Ordner mit exiftool.exe und exiftool_files")
    ap.add_argument("--ausgabe", type=Path, default=WURZEL / "build" / "paket")
    args = ap.parse_args()
    if args.exiftool is not None and not (args.exiftool / "exiftool.exe").is_file() \
            and not (args.exiftool / "exiftool").is_file():
        raise SystemExit(f"In {args.exiftool} liegt kein exiftool.exe.")
    bauen(args.ausgabe, args.exiftool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
