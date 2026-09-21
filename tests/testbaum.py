"""Erzeugt den kuenstlichen Testbaum (SPEC Abschnitt 11).

Nie mit echten Fotos testen. Alle Dateien entstehen vollstaendig aus Code:
ein 1x1-JPEG als feste Bytefolge, eine minimale TIFF-Struktur fuer RAW und
eine minimale Box-Struktur fuer MP4/MOV. Die Metadaten setzt danach
ExifTool; ohne ExifTool bricht der Erzeuger ab (SPEC Abschnitt 2).

In Phase 1 entsteht nur der Quellbaum. Der vorbelegte Zielbaum kommt ab
Phase 2, weil er die Zielpfad-Berechnung voraussetzt (SPEC Abschnitt 11).

Aufruf von Hand:
    PYTHONPATH=src .venv/bin/python tests/testbaum.py /tmp/testbaum
"""

from __future__ import annotations

import base64
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Gueltiges 1x1-Pixel-JPEG, rund 160 Byte.
_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)


def _tiff() -> bytes:
    """Minimale, gueltige TIFF-Struktur - Grundlage fuer .ARW und .TIF."""
    eintraege = [
        (256, 3, 1, 1),  # ImageWidth
        (257, 3, 1, 1),  # ImageLength
        (258, 3, 1, 8),  # BitsPerSample
        (259, 3, 1, 1),  # Compression = keine
        (262, 3, 1, 1),  # PhotometricInterpretation = schwarz/weiss
        (273, 4, 1, 0),  # StripOffsets, wird unten gesetzt
        (277, 3, 1, 1),  # SamplesPerPixel
        (278, 3, 1, 1),  # RowsPerStrip
        (279, 4, 1, 1),  # StripByteCounts
    ]
    kopf = struct.pack("<2sHI", b"II", 42, 8)
    daten_offset = 8 + 2 + 12 * len(eintraege) + 4
    teile = [kopf, struct.pack("<H", len(eintraege))]
    for kennung, typ, anzahl, wert in eintraege:
        if kennung == 273:
            wert = daten_offset
        if typ == 3:  # SHORT steht linksbuendig im 4-Byte-Feld
            teile.append(struct.pack("<HHIHH", kennung, typ, anzahl, wert, 0))
        else:
            teile.append(struct.pack("<HHII", kennung, typ, anzahl, wert))
    teile.append(struct.pack("<I", 0))
    teile.append(b"\x00")
    return b"".join(teile)


def _mp4(marke: bytes = b"isom") -> bytes:
    """Minimale, gueltige Box-Struktur: ftyp plus moov/mvhd."""
    ftyp = struct.pack(">I4s4sI4s", 20, b"ftyp", marke, 512, marke)
    matrix = struct.pack(
        ">9i", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000
    )
    mvhd = (
        struct.pack(">I4s", 108, b"mvhd")
        + b"\x00\x00\x00\x00"  # Version 0, keine Flags
        + struct.pack(">IIII", 0, 0, 1000, 0)  # Zeiten, Zeitbasis, Dauer
        + struct.pack(">ihhq", 0x00010000, 0x0100, 0, 0)  # Tempo, Lautstaerke
        + matrix
        + b"\x00" * 24
        + struct.pack(">I", 2)
    )
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    return ftyp + moov


def exiftool_pfad() -> str:
    """ExifTool finden; ohne ExifTool bricht der Erzeuger ab."""
    aus_umgebung = os.environ.get("FOTOSORT_EXIFTOOL", "").strip()
    gefunden = shutil.which(aus_umgebung) if aus_umgebung else shutil.which("exiftool")
    if not gefunden:
        raise RuntimeError(
            "ExifTool wurde nicht gefunden. Der Testbaum braucht es, um die\n"
            "Metadaten zu setzen. Pfad setzbar ueber FOTOSORT_EXIFTOOL."
        )
    return gefunden


def _exiftool(befehle: list[list[str]]) -> None:
    """Mehrere ExifTool-Aufrufe in einem Prozess (-@ liest Argumente)."""
    programm = exiftool_pfad()
    zeilen: list[str] = []
    for befehl in befehle:
        zeilen.extend(befehl)
        zeilen.append("-execute")
    eingabe = "\n".join(zeilen) + "\n"
    fertig = subprocess.run(
        [programm, "-stay_open", "False", "-@", "-"],
        input=eingabe,
        capture_output=True,
        text=True,
        check=False,
    )
    if fertig.returncode not in (0,):
        raise RuntimeError(
            f"ExifTool meldet einen Fehler:\n{fertig.stdout}\n{fertig.stderr}"
        )


def _schreiben(pfad: Path, inhalt: bytes) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


def _text(pfad: Path, inhalt: str) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


# Wie viele Dateien der Quellbaum enthaelt, aufgeteilt nach Dateityp.
# Die Verknuepfung "verlinkt" wird nicht verfolgt, ihr Inhalt zaehlt nicht mit.
# "Papiere/Papierkorb/geloescht.jpg" zaehlt nur ohne Ausschlussmuster mit.
ERWARTET_JE_TYP: dict[str, int] = {
    "foto": 13,
    "raw": 1,
    "video": 2,
    "sidecar": 3,
    "sonstiges": 3,
}
ERWARTET_GESAMT = sum(ERWARTET_JE_TYP.values())

# Dieselbe Aufteilung, wenn das Ausschlussmuster "*/Papierkorb/*" gilt.
ERWARTET_JE_TYP_OHNE_PAPIERKORB = dict(ERWARTET_JE_TYP, foto=ERWARTET_JE_TYP["foto"] - 1)
ERWARTET_GESAMT_OHNE_PAPIERKORB = ERWARTET_GESAMT - 1

AUSSCHLUSSMUSTER_BEISPIEL = "*/Papierkorb/*"


def erzeugen(wurzel: Path) -> dict[str, Path]:
    """Legt <wurzel>/Quelle und <wurzel>/Ausserhalb an.

    Gibt ein Verzeichnis der wichtigsten Pfade zurueck.
    """
    exiftool_pfad()  # bricht ohne ExifTool ab, bevor etwas entsteht
    wurzel = Path(wurzel)
    quelle = wurzel / "Quelle"
    ausserhalb = wurzel / "Ausserhalb"
    quelle.mkdir(parents=True, exist_ok=True)
    ausserhalb.mkdir(parents=True, exist_ok=True)

    wo: dict[str, Path] = {"wurzel": wurzel, "quelle": quelle, "ausserhalb": ausserhalb}
    befehle: list[list[str]] = []

    # --- RAW + JPG als Paar, dazu beide einfachen Sidecar-Formen --------
    paar = quelle / "2026"
    raw = _schreiben(paar / "DSC01234.ARW", _tiff())
    jpg = _schreiben(paar / "DSC01234.JPG", _JPEG)
    wo["raw"] = raw
    wo["jpg"] = jpg
    befehle.append(
        [
            "-overwrite_original",
            "-EXIF:DateTimeOriginal=2026:01:01 12:30:00",
            "-EXIF:Model=ILCE-7CM2",
            "-EXIF:Make=SONY",
            str(raw),
        ]
    )
    befehle.append(
        [
            "-overwrite_original",
            "-EXIF:DateTimeOriginal=2026:01:01 12:30:00",
            "-EXIF:Model=ILCE-7CM2",
            "-EXIF:Make=SONY",
            str(jpg),
        ]
    )
    # Form 1: Stammname plus Endung. Form 2: vollstaendiger Name plus Endung.
    wo["sidecar_form1"] = _text(
        paar / "DSC01234.xmp", '<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n'
    )
    wo["sidecar_form2"] = _text(
        paar / "DSC01234.ARW.xmp", '<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n'
    )

    # --- Sony-Paar: Video ohne Offset plus XML-Sidecar (Form 3) ---------
    # 2026:03:15 23:30:00 UTC wird in Europe/Berlin zum 16.03. - der Tag
    # wechselt, genau wie SPEC Abschnitt 11 es verlangt.
    sony = _schreiben(paar / "C0001.MP4", _mp4())
    wo["video_ohne_offset"] = sony
    befehle.append(
        [
            "-overwrite_original",
            "-QuickTime:CreateDate=2026:03:15 23:30:00",
            "-QuickTime:ModifyDate=2026:03:15 23:30:00",
            str(sony),
        ]
    )
    wo["sidecar_form3"] = _text(
        paar / "C0001M01.XML",
        '<?xml version="1.0"?>\n<NonRealTimeMeta>\n'
        '  <CreationDate value="2026-03-16T00:30:00+01:00"/>\n'
        "</NonRealTimeMeta>\n",
    )

    # --- Video mit Zeitzonen-Offset ------------------------------------
    videos = quelle / "Videos"
    mov = _schreiben(videos / "MVI_0001.MOV", _mp4(b"qt  "))
    wo["video_mit_offset"] = mov
    befehle.append(
        [
            "-overwrite_original",
            "-api",
            "QuickTimeUTC=1",
            "-QuickTime:CreateDate=2026:02:10 09:00:00",
            "-QuickTime:CreationDate=2026:02:10 10:00:00+01:00",
            str(mov),
        ]
    )

    # --- Umlaute, Leerzeichen, Datum aus dem Dateinamen ----------------
    urlaub = quelle / "Urlaub 2026 Ümläute"
    wo["name_mit_uhrzeit"] = _schreiben(urlaub / "IMG_20260101_013000.jpg", _JPEG)
    wo["name_ohne_uhrzeit"] = _schreiben(urlaub / "2026-01-01 Urlaub.jpg", _JPEG)

    # --- Kaputtes Datum und gar kein Datum -----------------------------
    kaputt = _schreiben(urlaub / "kaputtes_datum.jpg", _JPEG)
    wo["kaputtes_datum"] = kaputt
    befehle.append(
        [
            "-overwrite_original",
            "-m",
            "-EXIF:DateTimeOriginal=1970:01:01 00:00:00",
            "-EXIF:Model=ILCE-7C",
            str(kaputt),
        ]
    )
    wo["ohne_datum"] = _schreiben(urlaub / "ohne_datum.jpg", _JPEG)

    # --- Duplikate innerhalb der Quelle --------------------------------
    doppelt = quelle / "Duplikate"
    wo["duplikat_a"] = _schreiben(doppelt / "kopie_a.jpg", _JPEG)
    wo["duplikat_b"] = _schreiben(doppelt / "kopie_b.jpg", _JPEG)
    for pfad in (wo["duplikat_a"], wo["duplikat_b"]):
        befehle.append(
            [
                "-overwrite_original",
                "-EXIF:DateTimeOriginal=2026:01:02 08:00:00",
                "-EXIF:Model=ILCE-7C",
                str(pfad),
            ]
        )

    # --- Namenskonflikt: gleicher Name, anderer Inhalt -----------------
    konflikt = _schreiben(quelle / "Namenskonflikt" / "DSC01234.JPG", _JPEG + b"anders")
    wo["namenskonflikt"] = konflikt
    befehle.append(
        [
            "-overwrite_original",
            "-EXIF:DateTimeOriginal=2026:01:01 12:30:00",
            "-EXIF:Model=ILCE-7CM2",
            str(konflikt),
        ]
    )

    # --- Analog-Scan ----------------------------------------------------
    scan_datei = _schreiben(quelle / "Analog" / "scan_001.tif", _tiff())
    wo["analog"] = scan_datei
    befehle.append(
        [
            "-overwrite_original",
            "-EXIF:DateTimeOriginal=2026:04:05 15:00:00",
            "-EXIF:Model=Noritsu Koki QSS-32_33",
            str(scan_datei),
        ]
    )

    # --- Dateien ausserhalb der Typenlisten -----------------------------
    sonstiges = quelle / "Sonstiges"
    wo["sonstiges_text"] = _text(sonstiges / "notizen.txt", "kein Bild\n")
    wo["reste_thumbs"] = _schreiben(sonstiges / "Thumbs.db", b"Rest")
    wo["reste_ds_store"] = _schreiben(sonstiges / ".DS_Store", b"Rest")

    # --- Von einem Ausschlussmuster getroffener Pfad --------------------
    wo["im_papierkorb"] = _schreiben(
        quelle / "Papiere" / "Papierkorb" / "geloescht.jpg", _JPEG
    )

    # --- Quelle, die sich nach dem Kopieren aendert (Phase 3 und 5) -----
    wechselhaft = _schreiben(quelle / "aendert_sich.jpg", _JPEG)
    wo["aendert_sich"] = wechselhaft
    befehle.append(
        [
            "-overwrite_original",
            "-EXIF:DateTimeOriginal=2026:05:06 17:45:00",
            "-EXIF:Model=ILCE-7C",
            str(wechselhaft),
        ]
    )

    # --- Versteckter Ordner: wird normal erfasst ------------------------
    wo["versteckt"] = _schreiben(quelle / ".versteckt" / "versteckt.jpg", _JPEG)

    # --- Tiefer Pfad mit langem Dateinamen ------------------------------
    tief = quelle / "tief"
    for stufe in range(1, 11):
        tief = tief / f"ebene_{stufe:02d}"
    langer_name = ("sehr_langer_dateiname_" * 8)[:180] + ".jpg"
    wo["tiefer_pfad"] = _schreiben(tief / langer_name, _JPEG)

    # --- Ordner, auf den nur eine Verknuepfung zeigt --------------------
    wo["nur_ueber_verknuepfung"] = _schreiben(
        ausserhalb / "nur_ueber_verknuepfung.jpg", _JPEG
    )
    verknuepfung = quelle / "verlinkt"
    if not verknuepfung.exists() and not verknuepfung.is_symlink():
        os.symlink(ausserhalb, verknuepfung, target_is_directory=True)
    wo["ordner_verknuepfung"] = verknuepfung

    _exiftool(befehle)
    return wo


def main(argv: list[str] | None = None) -> int:
    argumente = list(sys.argv[1:] if argv is None else argv)
    if not argumente:
        print("Aufruf: testbaum.py <Ordner>", file=sys.stderr)
        return 2
    ziel = Path(argumente[0])
    try:
        wo = erzeugen(ziel)
    except RuntimeError as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    print(f"Testbaum erzeugt unter: {wo['wurzel']}")
    print(f"  Quelle:     {wo['quelle']}")
    print(f"  Ausserhalb: {wo['ausserhalb']} (nur ueber die Verknuepfung erreichbar)")
    print(f"  Dateien in der Quelle: {ERWARTET_GESAMT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
