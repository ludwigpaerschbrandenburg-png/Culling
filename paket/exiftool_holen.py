"""ExifTool fuer Windows (64 Bit) von exiftool.org holen und fuer das Paket
ablegen: <ziel>/exiftool_files (perl.exe, exiftool.pl, Perl-Laufzeit und
Bibliotheken) plus VERSION.txt; daneben der Starter <ziel>/exiftool.exe, den
das Paket aber nicht mitnimmt - es startet perl.exe mit exiftool.pl direkt
(paket/bauen.py, metadaten.exiftool_befehl). Die Tests unter Windows nehmen
diesen Ordner ebenfalls (.github/workflows/tests.yml).

Aufruf:
    python paket/exiftool_holen.py <zielordner> [--version 13.59 | --version neueste]

Ohne --version wird die festgenagelte Version FESTE_VERSION genommen und die
geladene ZIP-Datei gegen FESTE_SHA256 geprueft - so nimmt jeder Bau
nachweislich dieselbe Fassung, und eine unterwegs veraenderte Datei faellt
auf. "--version neueste" fragt https://exiftool.org/ver.txt; eine andere
Version als die festgenagelte wird ohne Pruefsumme geladen (mit Hinweis).
Zum Anheben: FESTE_VERSION und FESTE_SHA256 zusammen aendern (die Pruefsumme
mit "sha256sum exiftool-<Version>_64.zip"). Laeuft in GitHub Actions;
braucht Internet.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

KOPF = {"User-Agent": "fotosort-paketbau (https://github.com/ludwigpaerschbrandenburg-png/Culling)"}
# Die festgenagelte Fassung: Version und SHA-256 der ZIP-Datei
# exiftool-<Version>_64.zip (Windows, 64 Bit, mit exiftool_files).
FESTE_VERSION = "13.59"
FESTE_SHA256 = "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"
NEUESTE = "neueste"
VERSUCHE = 3


def _laden(url: str, versuche: int = VERSUCHE) -> bytes:
    """Mit Wiederholung: Zeitueberschreitungen zu exiftool.org sind haeufig."""
    fehler: Exception | None = None
    for versuch in range(1, versuche + 1):
        try:
            anfrage = urllib.request.Request(url, headers=KOPF)
            with urllib.request.urlopen(anfrage, timeout=120) as antwort:
                return antwort.read()
        except urllib.error.HTTPError as f:
            if f.code == 404:       # gibt es dort nicht - Wiederholen hilft nicht
                raise
            fehler = f
            print(f"  Versuch {versuch}/{versuche} fehlgeschlagen: {url} ({f})", flush=True)
            if versuch < versuche:
                time.sleep(10 * versuch)
            continue
        except Exception as f:  # noqa: BLE001 - jeder Netzfehler wird wiederholt
            fehler = f
            print(f"  Versuch {versuch}/{versuche} fehlgeschlagen: {url} ({f})", flush=True)
            if versuch < versuche:
                time.sleep(10 * versuch)
    assert fehler is not None
    raise fehler


def aktuelle_version() -> str:
    try:
        return _laden("https://exiftool.org/ver.txt").decode("ascii").strip()
    except Exception as fehler:  # noqa: BLE001
        print(f"Versionsabfrage bei exiftool.org fehlgeschlagen ({fehler}); nehme {FESTE_VERSION}.", flush=True)
        return FESTE_VERSION


def version_waehlen(gewuenscht: str | None) -> tuple[str, str | None]:
    """(Version, erwartete SHA-256 oder None). Ohne Angabe die festgenagelte."""
    if not gewuenscht:
        return FESTE_VERSION, FESTE_SHA256
    if gewuenscht == NEUESTE:
        gewuenscht = aktuelle_version()
    if gewuenscht == FESTE_VERSION:
        return gewuenscht, FESTE_SHA256
    print(f"Hinweis: Version {gewuenscht} ist nicht die festgenagelte ({FESTE_VERSION}); keine Pruefsumme bekannt.", flush=True)
    return gewuenscht, None


def holen(ziel: Path, version: str | None) -> str:
    version, erwartet = version_waehlen(version)
    kandidaten = [
        f"https://exiftool.org/exiftool-{version}_64.zip",
        f"https://exiftool.org/exiftool-{version}.zip",
        f"https://sourceforge.net/projects/exiftool/files/exiftool-{version}_64.zip/download",
    ]
    daten = None
    quelle = ""
    for url in kandidaten:
        try:
            geladen = _laden(url)
        except Exception as fehler:  # noqa: BLE001 - naechste Adresse probieren
            print(f"  nicht geladen: {url} ({fehler})")
            continue
        summe = hashlib.sha256(geladen).hexdigest()
        if erwartet is not None and summe != erwartet:
            # Andere Bytes als erwartet: nie benutzen, naechste Adresse probieren.
            print(f"  Pruefsumme passt nicht: {url} (SHA-256 {summe}, erwartet {erwartet})")
            continue
        daten, quelle = geladen, url
        break
    if daten is None:
        raise SystemExit(f"ExifTool {version} liess sich von keiner Adresse mit passender Pruefsumme laden.")
    print(f"Geladen: {quelle} ({len(daten) / 1e6:.1f} MB, SHA-256 {hashlib.sha256(daten).hexdigest()})")

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
        f"SHA-256 der ZIP-Datei: {hashlib.sha256(daten).hexdigest()}\n"
        "Lizenz: wie Perl (Artistic License / GPL), siehe https://exiftool.org\n",
        encoding="utf-8",
    )
    return version


def pruefen(ziel: Path) -> None:
    """Beide Wege muessen dieselbe Version liefern: der Starter exiftool.exe
    und perl.exe mit exiftool.pl direkt (so startet das Paket ExifTool)."""
    perl = ziel / "exiftool_files" / "perl.exe"
    skript = ziel / "exiftool_files" / "exiftool.pl"
    if not perl.is_file() or not skript.is_file():
        raise SystemExit(f"exiftool_files mit perl.exe und exiftool.pl fehlt unter {ziel}")
    if not sys.platform.startswith("win"):
        print(f"Nicht unter Windows: {perl} wird nicht gestartet.")
        return
    versionen = {}
    for name, befehl in (("exiftool.exe", [str(ziel / "exiftool.exe")]), ("perl.exe exiftool.pl", [str(perl), str(skript)])):
        aus = subprocess.run(befehl + ["-ver"], capture_output=True, text=True, timeout=120)
        if aus.returncode != 0 or not aus.stdout.strip():
            raise SystemExit(f"{name} startet nicht: rc={aus.returncode} {aus.stderr.strip()}")
        versionen[name] = aus.stdout.strip()
        print(f"{name} startet: Version {versionen[name]}")
    if len(set(versionen.values())) != 1:
        raise SystemExit(f"Starter und perl.exe liefern verschiedene Versionen: {versionen}")


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
