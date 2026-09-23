"""Das Windows-Paket ohne PyInstaller (v0.6): eingebettetes Python, ExifTool
ueber perl.exe, Arbeitsprozess ueber pythonw.exe, gekuerztes Qt.

Hier wird geprueft, was ohne Windows und ohne Internet geht: die Regeln, nach
denen gebaut, gekuerzt und gestartet wird. Das fertige Paket selbst probiert
paket/pruefen.py aus (in der CI unter Windows wie auf einem frischen PC).
"""

from __future__ import annotations

import importlib.util
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from fotosort import cli, config, metadaten

WURZEL = Path(__file__).resolve().parent.parent
PAKET = WURZEL / "paket"


def _modul(name: str):
    """Ein Skript aus paket/ als Modul laden (sie importieren sich gegenseitig)."""
    if str(PAKET) not in sys.path:
        sys.path.insert(0, str(PAKET))
    spec = importlib.util.spec_from_file_location(name, PAKET / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _datei(pfad: Path, inhalt: bytes = b"") -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


# ------------------------------------------------------------- ExifTool ----


def test_exiftool_wird_ueber_perl_gestartet(tmp_path):
    """Der Starter exiftool.exe laedt nur perl532.dll und ruft darin Perl mit
    exiftool.pl auf. Deshalb wird perl.exe direkt gestartet, wo es geht."""
    starter = _datei(tmp_path / "ExifTool" / "exiftool.exe")
    perl = _datei(tmp_path / "ExifTool" / "exiftool_files" / "perl.exe")
    skript = _datei(tmp_path / "ExifTool" / "exiftool_files" / "exiftool.pl")
    assert metadaten.exiftool_befehl(str(starter)) == [str(perl), str(skript)]
    assert metadaten.exiftool_befehl(str(skript)) == [str(perl), str(skript)]
    # Ohne exiftool_files (etwa eine alte Ein-Datei-Fassung): der Starter selbst.
    allein = _datei(tmp_path / "alt" / "exiftool.exe")
    assert metadaten.exiftool_befehl(str(allein)) == [str(allein)]
    # Unter Linux oder aus PATH: unveraendert.
    assert metadaten.exiftool_befehl("/usr/bin/exiftool") == ["/usr/bin/exiftool"]
    # Ein Perl-Skript ohne perl.exe daneben: ueber das Perl des Systems.
    einzeln = _datei(tmp_path / "skript" / "exiftool.pl")
    assert metadaten.exiftool_befehl(str(einzeln)) == ["perl", str(einzeln)]


def _paket(tmp_path: Path, monkeypatch, mit_perl: bool = True) -> Path:
    """Ein Paketordner wie das Windows-Paket (nur die Dateien, auf die es ankommt)."""
    paket = tmp_path / "fotosort-windows (1)" / "fotosort"
    _datei(paket / "python" / "python.exe")
    _datei(paket / "lib" / "fotosort" / "__init__.py")
    if mit_perl:
        _datei(paket / "exiftool" / "exiftool_files" / "perl.exe")
        _datei(paket / "exiftool" / "exiftool_files" / "exiftool.pl")
    monkeypatch.setattr(cli, "__file__", str(paket / "lib" / "fotosort" / "cli.py"))
    return paket


def test_mitgeliefertes_exiftool_im_paket(tmp_path, monkeypatch):
    assert cli.paket_wurzel() is None                     # aus dem Quellcode heraus
    paket = _paket(tmp_path, monkeypatch)
    assert cli.paket_wurzel() == paket
    skript = paket / "exiftool" / "exiftool_files" / "exiftool.pl"
    assert cli.exiftool_mitgeliefert() == skript
    gefunden, wo = cli.exiftool_finden(config.Konfiguration())
    assert gefunden == str(skript) and "mitgeliefert, gestartet ueber perl.exe" in wo
    assert metadaten.exiftool_befehl(gefunden)[0] == str(skript.with_name("perl.exe"))
    # FOTOSORT_EXIFTOOL geht weiterhin vor.
    monkeypatch.setenv("FOTOSORT_EXIFTOOL", str(skript))
    assert cli.exiftool_finden(config.Konfiguration())[1].endswith("(FOTOSORT_EXIFTOOL)")


def test_paket_mit_altem_starter(tmp_path, monkeypatch):
    paket = _paket(tmp_path, monkeypatch, mit_perl=False)
    starter = _datei(paket / "exiftool" / "exiftool.exe")
    assert cli.exiftool_mitgeliefert() == starter


# ----------------------------------------------------------- Bauregeln ----


def test_kuerzen_laesst_nur_das_noetige(tmp_path):
    """Von PySide6 bleiben QtCore, QtGui, QtWidgets, zwei Anzeige-Plugins, der
    Windows-Stil und die C++-Laufzeit; kein einziges Programm (.exe)."""
    bauen = _modul("bauen")
    lib = tmp_path / "lib"
    bleibt = [
        "PySide6/__init__.py", "PySide6/QtCore.pyd", "PySide6/QtGui.pyd", "PySide6/QtWidgets.pyd",
        "PySide6/Qt6Core.dll", "PySide6/Qt6Gui.dll", "PySide6/Qt6Widgets.dll", "PySide6/pyside6.abi3.dll",
        "PySide6/msvcp140.dll", "PySide6/msvcp140_2.dll", "PySide6/vcruntime140_1.dll", "PySide6/concrt140.dll",
        "PySide6/support/deprecated.py", "PySide6/plugins/platforms/qwindows.dll",
        "PySide6/plugins/platforms/qoffscreen.dll", "PySide6/plugins/styles/qmodernwindowsstyle.dll",
        "shiboken6/__init__.py", "shiboken6/Shiboken.pyd", "shiboken6/shiboken6.abi3.dll", "shiboken6/msvcp140.dll",
        "blake3/blake3.cp312-win_amd64.pyd", "rich/console.py", "fotosort/cli.py",
        "PySide6_Essentials-6.11.2.dist-info/METADATA",
    ]
    weg = [
        "bin/pyside6-designer.exe", "bin/pygmentize.exe", "PySide6/designer.exe", "PySide6/uic.exe",
        "PySide6/QtQuick.pyd", "PySide6/Qt6Quick.dll", "PySide6/QtNetwork.pyd", "PySide6/Qt6Network.dll",
        "PySide6/opengl32sw.dll", "PySide6/vcomp140.dll", "PySide6/QtCore.pyi", "PySide6/pyside6.abi3.lib",
        "PySide6/qml/QtQuick/qmldir", "PySide6/translations/qt_de.qm", "PySide6/resources/icudtl.dat",
        "PySide6/include/pyside.h", "PySide6/plugins/imageformats/qjpeg.dll", "PySide6/plugins/tls/qopensslbackend.dll",
        "PySide6/plugins/platforms/qminimal.dll", "PySide6/support/__pycache__/deprecated.cpython-310.pyc",
        "shiboken6/include/sbkenum.h", "shiboken6/lib/cmake/Shiboken6/Shiboken6Config.cmake", "shiboken6/Shiboken.pyi",
        "shiboken6/vccorlib140.dll", "rich/__pycache__/console.cpython-312.pyc",
    ]
    for rel in bleibt + weg:
        _datei(lib / rel)
    assert bauen.kuerzen(lib) == len(weg)
    uebrig = sorted(p.relative_to(lib).as_posix() for p in lib.rglob("*") if p.is_file())
    assert uebrig == sorted(bleibt)
    assert not (lib / "bin").exists() and not (lib / "PySide6" / "plugins" / "imageformats").exists()


def test_startdateien_mit_crlf_und_ohne_klammerbloecke(tmp_path):
    """cmd.exe braucht CRLF fuer Sprungmarken; Klammerbloecke wuerden an einem
    Pfad wie "...\\fotosort-windows (1)\\..." zerbrechen."""
    bauen = _modul("bauen")
    bauen.startdateien(tmp_path, "9.9.9")
    for name, muss in (("start.bat", ['"%~dp0python\\pythonw.exe" -X utf8 "%~dp0lib\\fotosort_start.py" fenster']),
                       ("fotosort.bat", ['"%~dp0python\\python.exe" -X utf8 "%~dp0lib\\fotosort_start.py" %*'])):
        roh = (tmp_path / name).read_bytes()
        assert b"\r\n" in roh and b"\n" not in roh.replace(b"\r\n", b"")
        text = roh.decode("ascii")
        for teil in muss:
            assert teil in text, (name, teil)
        for zeile in text.splitlines():
            code = zeile.strip()
            if code.lower().startswith(("rem", "echo")):
                continue
            assert not code.endswith("(") and not code.startswith(")"), (name, zeile)
    assert (tmp_path / "VERSION.txt").read_text(encoding="utf-8").startswith("fotosort 9.9.9")
    assert (tmp_path / "LIESMICH.md").is_file()


def test_bibliotheksliste_fest_und_ohne_browser_fassung():
    zeilen = [z for z in (PAKET / "windows-bibliotheken.txt").read_text(encoding="utf-8").splitlines()
              if z.strip() and not z.startswith("#")]
    namen = {z.split("==")[0].lower() for z in zeilen}
    assert all("==" in z and "--hash=sha256:" in z for z in zeilen)
    assert {"pyside6-essentials", "shiboken6", "blake3", "rich", "tomli-w", "tzdata"} == namen
    assert not namen & {"fastapi", "uvicorn", "pyinstaller", "pygments"}


# ------------------------------------------------ Laufen ohne Beiwerk ----


def test_fotosort_braucht_weder_pygments_noch_fastapi(tmp_path):
    """Im Windows-Paket fehlen pygments, markdown-it (nur fuer rich-Extras) und
    die Browser-Fassung. Konsole, Fortschrittsbalken und das Fenster-Modul
    muessen ohne sie laden und laufen."""
    code = r'''
import importlib.abc, io, sys
class Sperre(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in ("pygments", "markdown_it", "mdurl", "fastapi", "uvicorn", "starlette"):
            raise ImportError("gesperrt: " + name)
sys.meta_path.insert(0, Sperre())
from rich.console import Console
from fotosort import cli, fortschritt, meldungen
from fotosort.oberflaeche import fenster
k = Console(file=io.StringIO(), force_terminal=True, width=100)
f = fortschritt.Fortschritt(k, 10, 1000, meldungen.kopieren_laeuft)
for _ in range(3):
    f.weiter(1, 100)
f.stop()
k.print(meldungen.restzeit(None, "wird_berechnet"))
rc = fenster.server_starten(0, True, None, k)
print("ok", rc)
'''
    aus = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         env={**__import__("os").environ, "PYTHONPATH": str(WURZEL / "src")})
    assert aus.returncode == 0, aus.stderr
    assert aus.stdout.strip().endswith("ok 1"), aus.stdout    # Browser-Fassung: klare Meldung statt Absturz


# ------------------------------------------------ Windows-Dateien lesen ----


def _kleine_pe(importe: list[str], verzoegert: list[str], maschine: int = 0x8664) -> bytes:
    """Eine minimale 64-Bit-Windows-Datei (PE32+) mit Import- und
    Verzoegert-Import-Tabelle - nur fuer den Test des Lesers."""
    datei = bytearray(0x200 + 0x1000)
    datei[0:2] = b"MZ"
    struct.pack_into("<I", datei, 0x3C, 0x40)
    datei[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", datei, 0x44, maschine, 1, 0, 0, 0, 240, 0x2022)
    opt = 0x58
    struct.pack_into("<H", datei, opt, 0x20B)
    struct.pack_into("<Q", datei, opt + 24, 0x180000000)
    struct.pack_into("<I", datei, opt + 108, 16)
    struct.pack_into("<II", datei, opt + 112 + 8 * 1, 0x1000, 20 * (len(importe) + 1))
    struct.pack_into("<II", datei, opt + 112 + 8 * 13, 0x1400, 32 * (len(verzoegert) + 1))
    abschnitt = opt + 240
    datei[abschnitt:abschnitt + 8] = b".idata\0\0"
    struct.pack_into("<IIII", datei, abschnitt + 8, 0x1000, 0x1000, 0x1000, 0x200)
    namen_rva = 0x1800
    for i, name in enumerate(importe):
        struct.pack_into("<IIIII", datei, 0x200 + 20 * i, 0, 0, 0, namen_rva, 0x1F00)
        datei[0x200 + namen_rva - 0x1000:0x200 + namen_rva - 0x1000 + len(name)] = name.encode()
        namen_rva += 0x40
    for i, name in enumerate(verzoegert):
        struct.pack_into("<II", datei, 0x200 + 0x400 + 32 * i, 1, namen_rva)
        datei[0x200 + namen_rva - 0x1000:0x200 + namen_rva - 0x1000 + len(name)] = name.encode()
        namen_rva += 0x40
    return bytes(datei)


def test_importtabellen_und_fehlende_bibliotheken(tmp_path):
    inhalt = _modul("paketinhalt")
    pe = _datei(tmp_path / "a.pyd", _kleine_pe(["KERNEL32.dll", "Qt6Core.dll"], ["d3d12.dll", "selten.dll"]))
    assert inhalt.pe_importe(pe) == ("x64", ["KERNEL32.dll", "Qt6Core.dll"], ["d3d12.dll", "selten.dll"])
    paket = tmp_path / "paket"
    _datei(paket / "lib" / "PySide6" / "QtCore.pyd", _kleine_pe(["KERNEL32.dll", "Qt6Core.dll", "MSVCP140.dll"], ["selten.dll"]))
    _datei(paket / "lib" / "PySide6" / "Qt6Core.dll", _kleine_pe(["api-ms-win-crt-heap-l1-1-0.dll", "icuuc.dll"], []))
    fehler, hinweise = inhalt.fehlende_abhaengigkeiten(paket)
    assert fehler == ["lib/PySide6/QtCore.pyd braucht MSVCP140.dll - fehlt im Paket"]   # C++-Laufzeit gehoert ins Paket
    assert hinweise == ["lib/PySide6/QtCore.pyd laedt bei Bedarf selten.dll - nicht im Paket"]
    _datei(paket / "lib" / "PySide6" / "msvcp140.dll", _kleine_pe(["KERNEL32.dll"], []))
    _datei(paket / "python" / "alt32.dll", _kleine_pe([], [], maschine=0x14C))
    fehler, _ = inhalt.fehlende_abhaengigkeiten(paket)
    assert fehler == ["python/alt32.dll: keine 64-Bit-Datei (x86)"]
    _datei(paket / "lib" / "bin" / "pygmentize.exe", _kleine_pe([], []))
    _datei(paket / "python" / "python.exe", _kleine_pe([], []))
    assert inhalt.programme(paket) == ["lib/bin/pygmentize.exe", "python/python.exe"]
    assert [p for p in inhalt.programme(paket) if p not in inhalt.ERLAUBTE_PROGRAMME] == ["lib/bin/pygmentize.exe"]
    with pytest.raises(ValueError):
        inhalt.pe_importe(_datei(tmp_path / "kein.dll", b"Hallo"))
