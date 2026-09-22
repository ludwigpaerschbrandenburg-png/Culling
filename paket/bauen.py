"""Das eigenstaendige Programm bauen (PyInstaller, Ordner-Variante) und den
Paketordner zusammenstellen.

Aufruf (im Repository-Ordner, mit installiertem fotosort und PyInstaller):
    python paket/bauen.py --exiftool <ordner mit exiftool.exe und exiftool_files> [--ausgabe build/paket]

Ergebnis: <ausgabe>/fotosort/ mit fotosort.exe (bzw. fotosort unter Linux),
_internal/ (Python und Bibliotheken), exiftool/ (mitgeliefertes ExifTool),
fotosort.bat, start.bat, LIESMICH.md, VERSION.txt.
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
    befehl = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir", "--console", "--name", "fotosort",
        "--distpath", str(dist), "--workpath", str(ausgabe / "work"), "--specpath", str(ausgabe),
        # Zeitzonendaten (Video-Umrechnung) und deren Paketangaben mitnehmen.
        "--collect-all", "tzdata",
        "--collect-submodules", "rich",
        str(WURZEL / "paket" / "fotosort_start.py"),
    ]
    print(" ".join(befehl))
    subprocess.run(befehl, check=True)
    paket = dist / "fotosort"
    exe = paket / ("fotosort.exe" if sys.platform.startswith("win") else "fotosort")
    if not exe.is_file():
        raise SystemExit(f"PyInstaller hat {exe} nicht erzeugt.")

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
