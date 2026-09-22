"""ExifTool fuer Windows (64 Bit) von exiftool.org holen und fuer das Paket
ablegen: <ziel>/exiftool.exe neben <ziel>/exiftool_files (Perl-Laufzeit und
Bibliotheken, die die Windows-Fassung braucht) plus VERSION.txt.

Aufruf:
    python paket/exiftool_holen.py <zielordner> [--version 13.36]

Ohne --version wird die aktuelle Version von https://exiftool.org/ver.txt
genommen. Laeuft in GitHub Actions; braucht Internet.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

KOPF = {"User-Agent": "fotosort-paketbau (https://github.com/ludwigpaerschbrandenburg-png/Culling)"}


def _laden(url: str) -> bytes:
    anfrage = urllib.request.Request(url, headers=KOPF)
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:
        return antwort.read()


def aktuelle_version() -> str:
    return _laden("https://exiftool.org/ver.txt").decode("ascii").strip()


def holen(ziel: Path, version: str | None) -> str:
    version = version or aktuelle_version()
    kandidaten = [
        f"https://exiftool.org/exiftool-{version}_64.zip",
        f"https://exiftool.org/exiftool-{version}.zip",
        f"https://sourceforge.net/projects/exiftool/files/exiftool-{version}_64.zip/download",
    ]
    daten = None
    quelle = ""
    for url in kandidaten:
        try:
            daten = _laden(url)
            quelle = url
            break
        except Exception as fehler:  # noqa: BLE001 - naechste Adresse probieren
            print(f"  nicht geladen: {url} ({fehler})")
    if daten is None:
        raise SystemExit(f"ExifTool {version} liess sich von keiner Adresse laden.")
    print(f"Geladen: {quelle} ({len(daten) / 1e6:.1f} MB)")

    ziel.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(daten)) as zf:
            zf.extractall(tmp)
        exe = next((p for p in Path(tmp).rglob("exiftool(-k).exe")), None)
        if exe is None:
            exe = next((p for p in Path(tmp).rglob("exiftool*.exe")), None)
        if exe is None:
            raise SystemExit("In der ZIP-Datei liegt keine exiftool(-k).exe.")
        shutil.copyfile(exe, ziel / "exiftool.exe")
        bibliotheken = exe.parent / "exiftool_files"
        if bibliotheken.is_dir():
            shutil.copytree(bibliotheken, ziel / "exiftool_files", dirs_exist_ok=True)
            print(f"Perl-Bibliotheken kopiert: {sum(1 for _ in (ziel / 'exiftool_files').rglob('*'))} Eintraege")
        else:
            print("Hinweis: kein Ordner exiftool_files in der ZIP (aeltere Ein-Datei-Fassung).")
        for txt in exe.parent.glob("*.txt"):
            shutil.copyfile(txt, ziel / txt.name)
    (ziel / "VERSION.txt").write_text(
        f"ExifTool {version} von Phil Harvey, geladen von {quelle}\n"
        "Lizenz: wie Perl (Artistic License / GPL), siehe https://exiftool.org\n",
        encoding="utf-8",
    )
    return version


def pruefen(ziel: Path) -> None:
    exe = ziel / "exiftool.exe"
    if not sys.platform.startswith("win"):
        print(f"Nicht unter Windows: {exe} wird nicht gestartet.")
        return
    aus = subprocess.run([str(exe), "-ver"], capture_output=True, text=True, timeout=120)
    if aus.returncode != 0 or not aus.stdout.strip():
        raise SystemExit(f"exiftool.exe startet nicht: rc={aus.returncode} {aus.stderr.strip()}")
    print(f"exiftool.exe startet: Version {aus.stdout.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ziel", type=Path)
    ap.add_argument("--version", default=None)
    args = ap.parse_args()
    version = holen(args.ziel, args.version)
    pruefen(args.ziel)
    print(f"ExifTool {version} liegt unter {args.ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
