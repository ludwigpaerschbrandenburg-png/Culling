"""Pruefungen am Inhalt des Windows-Pakets - laufen auf jedem System (auch Linux).

- programme(): alle .exe im Paket. Erlaubt sind nur das signierte Python
  (python\\python.exe, python\\pythonw.exe) und perl.exe von ExifTool.
- fehlende_abhaengigkeiten(): liest die Importtabellen aller .exe, .dll und
  .pyd (PE-Format) und meldet jede Bibliothek, die weder im Paket liegt noch
  zu Windows selbst gehoert. So faellt es beim Bau auf, wenn beim Kuerzen von
  Qt eine noetige Datei verloren ging - nicht erst auf dem PC des Nutzers.
"""

from __future__ import annotations

import struct
from pathlib import Path

ERLAUBTE_PROGRAMME = {
    "python/python.exe",
    "python/pythonw.exe",
    "exiftool/exiftool_files/perl.exe",
}

# Bibliotheken, die jedes Windows 10/11 mitbringt (System32). Die
# Microsoft-C++-Laufzeit (msvcp140*.dll, vcruntime140*.dll) gehoert NICHT
# dazu - sie muss im Paket liegen, ein frischer PC hat sie oft nicht.
SYSTEM = {
    "advapi32.dll", "authz.dll", "avrt.dll", "bcrypt.dll", "cfgmgr32.dll", "comctl32.dll",
    "comdlg32.dll", "credui.dll", "crypt32.dll", "d2d1.dll", "d3d11.dll", "d3d12.dll",
    "d3d9.dll", "d3dcompiler_47.dll", "dbghelp.dll", "dcomp.dll", "dnsapi.dll", "dwmapi.dll",
    "dwrite.dll", "dxgi.dll", "dxva2.dll", "gdi32.dll", "gdiplus.dll", "glu32.dll", "hid.dll",
    "imm32.dll", "iphlpapi.dll", "kernel32.dll", "mpr.dll", "msimg32.dll", "msvcrt.dll",
    "mswsock.dll", "ncrypt.dll", "netapi32.dll", "normaliz.dll", "ntdll.dll", "ole32.dll",
    "oleacc.dll", "oleaut32.dll", "opengl32.dll", "powrprof.dll", "propsys.dll", "psapi.dll",
    "rpcrt4.dll", "secur32.dll", "setupapi.dll", "shcore.dll", "shell32.dll", "shlwapi.dll",
    "ucrtbase.dll", "urlmon.dll", "user32.dll", "userenv.dll", "usp10.dll", "uxtheme.dll",
    "version.dll", "winhttp.dll", "wininet.dll", "winmm.dll", "winspool.drv", "wldap32.dll",
    "ws2_32.dll", "wsock32.dll", "wtsapi32.dll", "xinput1_4.dll", "dinput8.dll", "mf.dll",
    "mfplat.dll", "mfreadwrite.dll", "uiautomationcore.dll", "wevtapi.dll", "winusb.dll",
    "cabinet.dll", "msi.dll", "profapi.dll", "sechost.dll", "combase.dll", "wintrust.dll",
    # Unicode-Bibliothek (ICU) von Windows selbst, seit Windows 10 Version 1903 in
    # System32; Qt6Core.dll nutzt sie statt einer eigenen Kopie.
    "icuuc.dll", "icuin.dll", "icu.dll",
    # Zufallszahlen fuer Rust-Programme (blake3), seit Windows 8 in System32.
    "bcryptprimitives.dll",
}


def ist_system(name: str) -> bool:
    n = name.lower()
    return n in SYSTEM or n.startswith(("api-ms-win-", "ext-ms-win-"))


def programme(paket: Path) -> list[str]:
    """Alle .exe im Paket, als Pfad relativ zum Paket mit '/'."""
    return sorted(p.relative_to(paket).as_posix() for p in paket.rglob("*") if p.is_file() and p.suffix.lower() == ".exe")


def _cstr(daten: bytes, pos: int) -> str:
    ende = daten.find(b"\0", pos)
    return daten[pos:ende if ende >= 0 else len(daten)].decode("ascii", "replace")


def pe_importe(pfad: Path) -> tuple[str, list[str], list[str]]:
    """(Maschine, Importe, verzoegerte Importe) einer Windows-Datei (PE).

    Maschine: "x64", "x86" oder die Nummer. Wirft ValueError, wenn die Datei
    kein PE-Format hat.
    """
    daten = Path(pfad).read_bytes()
    if daten[:2] != b"MZ":
        raise ValueError("kein MZ-Kopf")
    pe = struct.unpack_from("<I", daten, 0x3C)[0]
    if daten[pe:pe + 4] != b"PE\0\0":
        raise ValueError("kein PE-Kopf")
    maschine, abschnitte, _zeit, _sym, _nsym, opt_groesse, _merkmale = struct.unpack_from("<HHIIIHH", daten, pe + 4)
    opt = pe + 24
    magie = struct.unpack_from("<H", daten, opt)[0]
    if magie == 0x20B:          # PE32+ (64 Bit)
        basis = struct.unpack_from("<Q", daten, opt + 24)[0]
        verzeichnisse = opt + 112
    elif magie == 0x10B:        # PE32 (32 Bit)
        basis = struct.unpack_from("<I", daten, opt + 28)[0]
        verzeichnisse = opt + 96
    else:
        raise ValueError(f"unbekannter Optional-Header {magie:#x}")
    tabelle = []
    for i in range(abschnitte):
        k = opt + opt_groesse + 40 * i
        vgroesse, vadresse, rgroesse, rzeiger = struct.unpack_from("<IIII", daten, k + 8)
        tabelle.append((vadresse, max(vgroesse, rgroesse), rzeiger))

    def versatz(rva: int) -> int:
        for vadresse, groesse, rzeiger in tabelle:
            if vadresse <= rva < vadresse + groesse:
                return rva - vadresse + rzeiger
        raise ValueError(f"RVA {rva:#x} in keinem Abschnitt")

    importe: list[str] = []
    rva, groesse = struct.unpack_from("<II", daten, verzeichnisse + 8 * 1)
    if rva and groesse:
        pos = versatz(rva)
        while True:
            _oft, _z, _f, name_rva, ft = struct.unpack_from("<IIIII", daten, pos)
            if not name_rva and not ft:
                break
            importe.append(_cstr(daten, versatz(name_rva)))
            pos += 20
    verzoegert: list[str] = []
    rva, groesse = struct.unpack_from("<II", daten, verzeichnisse + 8 * 13)
    if rva and groesse:
        pos = versatz(rva)
        while True:
            attribute, name_rva = struct.unpack_from("<II", daten, pos)
            if not name_rva:
                break
            if not attribute & 1:            # alte Form: virtuelle Adresse statt RVA
                name_rva -= basis
            verzoegert.append(_cstr(daten, versatz(name_rva)))
            pos += 32
    art = {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(maschine, f"{maschine:#x}")
    return art, importe, verzoegert


def binaerdateien(paket: Path) -> list[Path]:
    return sorted(p for p in paket.rglob("*") if p.is_file() and p.suffix.lower() in (".exe", ".dll", ".pyd"))


def fehlende_abhaengigkeiten(paket: Path) -> tuple[list[str], list[str]]:
    """(Fehler, Hinweise). Fehler: eine Datei braucht eine Bibliothek, die
    weder im Paket noch in Windows liegt, oder ist keine 64-Bit-Datei.
    Hinweise: verzoegert geladene Bibliotheken, die fehlen (werden nur bei
    Bedarf geladen, etwa fuer Funktionen, die das Programm nicht nutzt)."""
    dateien = binaerdateien(paket)
    vorhanden = {p.name.lower() for p in dateien}
    fehler: list[str] = []
    hinweise: list[str] = []
    for p in dateien:
        rel = p.relative_to(paket).as_posix()
        try:
            art, importe, verzoegert = pe_importe(p)
        except (ValueError, struct.error) as grund:
            fehler.append(f"{rel}: nicht lesbar ({grund})")
            continue
        if art != "x64":
            fehler.append(f"{rel}: keine 64-Bit-Datei ({art})")
        for name in importe:
            if name.lower() not in vorhanden and not ist_system(name):
                fehler.append(f"{rel} braucht {name} - fehlt im Paket")
        for name in verzoegert:
            if name.lower() not in vorhanden and not ist_system(name):
                hinweise.append(f"{rel} laedt bei Bedarf {name} - nicht im Paket")
    return fehler, hinweise
