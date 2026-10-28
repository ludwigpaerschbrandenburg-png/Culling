"""Dateiformate fuer die Testbilder (testbilder.py) - reine Bytes, kein Dateisystem.

Hier entstehen die Huellen, die keine Bibliothek fertig liefert: EXIF-Bloecke
(TIFF-Aufbau), JPEG mit EXIF, eine RAW-Datei mit eingebettetem Vorschau-JPEG,
ein HEIC mit EXIF-Eintrag, Videos (MOV/MP4/3GP und AVI) mit einem einzigen
Standbild im Motion-JPEG-Format, dazu XMP-, Sony-XML- und AAE-Begleitdateien.

Alles nach den offenen Beschreibungen der Formate (TIFF 6.0/EXIF 2.32,
ISO-BMFF/QuickTime, HEIF, RIFF/AVI). Im Container mit ExifTool und ffprobe
geprueft: ExifTool liest Datum, Kamera und Vorschaubild, ffmpeg spielt die
Videos ab.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone

# ------------------------------------------------------------ TIFF/EXIF ----

ASCII, SHORT, LONG, RATIONAL, BYTE = 2, 3, 4, 5, 1


class Ifd:
    """Ein IFD als Liste von Eintraegen. Werte sind fertige Bytes; ein Zeiger
    (Offset eines anderen IFD oder Datenblocks) steht als Name darin und wird
    erst beim Zusammensetzen (tiff) aufgeloest."""

    def __init__(self) -> None:
        self.eintraege: list[tuple[int, int, int, bytes | str]] = []

    def ascii(self, tag: int, text: str) -> "Ifd":
        daten = text.encode("utf-8") + b"\0"
        self.eintraege.append((tag, ASCII, len(daten), daten))
        return self

    def short(self, tag: int, *werte: int) -> "Ifd":
        self.eintraege.append((tag, SHORT, len(werte), struct.pack(f"<{len(werte)}H", *werte)))
        return self

    def long(self, tag: int, wert: int) -> "Ifd":
        self.eintraege.append((tag, LONG, 1, struct.pack("<I", wert)))
        return self

    def rational(self, tag: int, zaehler: int, nenner: int) -> "Ifd":
        self.eintraege.append((tag, RATIONAL, 1, struct.pack("<II", zaehler, nenner)))
        return self

    def roh(self, tag: int, daten: bytes, typ: int = BYTE) -> "Ifd":
        self.eintraege.append((tag, typ, len(daten), daten))
        return self

    def zeiger(self, tag: int, name: str) -> "Ifd":
        self.eintraege.append((tag, LONG, 1, name))
        return self

    def groesse(self) -> int:
        """Bytes fuer Eintraege plus ausgelagerte Werte (je auf gerade Laenge)."""
        aussen = sum(len(w) + (len(w) % 2) for _t, _ty, _n, w in self.eintraege
                     if isinstance(w, bytes) and len(w) > 4)
        return 2 + 12 * len(self.eintraege) + 4 + aussen


def tiff(ifds: list[tuple[str, Ifd]], bloecke: list[tuple[str, bytes]], kette: dict[str, str] | None = None) -> bytes:
    """Ein TIFF (little endian) aus benannten IFDs und Datenbloecken.

    Reihenfolge in der Datei: Kopf, die IFDs (der erste ist IFD0), dann die
    Bloecke. kette: welches IFD auf welches folgt (IFD0 -> IFD1)."""
    kette = kette or {}
    offsets: dict[str, int] = {}
    stelle = 8
    for name, ifd in ifds:
        offsets[name] = stelle
        stelle += ifd.groesse()
    for name, daten in bloecke:
        offsets[name] = stelle
        stelle += len(daten) + (len(daten) % 2)
    teile = [struct.pack("<2sHI", b"II", 42, offsets[ifds[0][0]])]
    for name, ifd in ifds:
        eintraege = sorted(ifd.eintraege, key=lambda e: e[0])
        aussen_ab = offsets[name] + 2 + 12 * len(eintraege) + 4
        kopf = [struct.pack("<H", len(eintraege))]
        aussen: list[bytes] = []
        for tag, typ, anzahl, wert in eintraege:
            if isinstance(wert, str):
                wert = struct.pack("<I", offsets[wert])
            if len(wert) <= 4:
                kopf.append(struct.pack("<HHI", tag, typ, anzahl) + wert.ljust(4, b"\0"))
            else:
                kopf.append(struct.pack("<HHII", tag, typ, anzahl, aussen_ab))
                gepolstert = wert + b"\0" * (len(wert) % 2)
                aussen.append(gepolstert)
                aussen_ab += len(gepolstert)
        folge = kette.get(name)
        kopf.append(struct.pack("<I", offsets[folge] if folge else 0))
        teile.extend(kopf)
        teile.extend(aussen)
    for _name, daten in bloecke:
        teile.append(daten + b"\0" * (len(daten) % 2))
    return b"".join(teile)


def ucs2(text: str) -> bytes:
    """Windows-Feld XPTitle/XPComment: UCS-2, kleines Ende zuerst, mit Abschluss."""
    return text.encode("utf-16-le") + b"\0\0"


def exif_ifds(werte: dict) -> tuple[Ifd, Ifd]:
    """IFD0 und EXIF-IFD aus einem Wertebuch.

    Schluessel (alle wahlweise): make, model, software, titel, kommentar,
    dto (DateTimeOriginal), create (CreateDate), offset (OffsetTimeOriginal),
    belichtung (Nenner von 1/x s), blende (x10), iso, brennweite, objektiv.
    Werte stehen als Text, wie die Kamera sie schreibt: "2023:03:14 18:22:05".
    """
    ifd0 = Ifd()
    if werte.get("make"):
        ifd0.ascii(0x010F, werte["make"])
    if werte.get("model") is not None and werte.get("model") != "":
        ifd0.ascii(0x0110, werte["model"])
    ifd0.short(0x0112, 1)
    ifd0.ascii(0x0131, werte.get("software") or "fotosort Testbild")
    if werte.get("geaendert"):
        ifd0.ascii(0x0132, werte["geaendert"])
    if werte.get("titel"):
        ifd0.roh(0x9C9B, ucs2(werte["titel"]))
    if werte.get("kommentar"):
        ifd0.roh(0x9C9C, ucs2(werte["kommentar"]))
    exif = Ifd()
    if werte.get("belichtung"):
        exif.rational(0x829A, 1, int(werte["belichtung"]))
    if werte.get("blende"):
        exif.rational(0x829D, int(werte["blende"]), 10)
    if werte.get("iso"):
        exif.short(0x8827, int(werte["iso"]))
    exif.roh(0x9000, b"0232", 7)
    if werte.get("dto"):
        exif.ascii(0x9003, werte["dto"])
    if werte.get("create"):
        exif.ascii(0x9004, werte["create"])
    if werte.get("offset"):
        exif.ascii(0x9011, werte["offset"])
    if werte.get("brennweite"):
        exif.rational(0x920A, int(werte["brennweite"]), 1)
    if werte.get("objektiv"):
        exif.ascii(0xA434, werte["objektiv"])
    ifd0.zeiger(0x8769, "exif")
    return ifd0, exif


def exif_block(werte: dict, vorschau: bytes | None = None) -> bytes:
    """EXIF als TIFF-Block; mit vorschau ein IFD1 mit JPEG (ThumbnailImage)."""
    ifd0, exif = exif_ifds(werte)
    ifds = [("ifd0", ifd0), ("exif", exif)]
    bloecke: list[tuple[str, bytes]] = []
    kette = {}
    if vorschau:
        ifd1 = Ifd().short(0x0103, 6).zeiger(0x0201, "vorschau").long(0x0202, len(vorschau))
        ifds.append(("ifd1", ifd1))
        bloecke.append(("vorschau", vorschau))
        kette["ifd0"] = "ifd1"
    return tiff(ifds, bloecke, kette)


def jpeg_mit_exif(jpeg: bytes, werte: dict) -> bytes:
    """Ein APP1-Segment mit EXIF hinter SOI (und hinter dem JFIF-APP0) einfuegen."""
    if jpeg[:2] != b"\xff\xd8":
        raise ValueError("kein JPEG")
    nutzlast = b"Exif\0\0" + exif_block(werte)
    if len(nutzlast) + 2 > 0xFFFF:
        raise ValueError("EXIF-Block zu gross fuer ein APP1-Segment")
    segment = b"\xff\xe1" + struct.pack(">H", len(nutzlast) + 2) + nutzlast
    stelle = 2
    if jpeg[2:4] == b"\xff\xe0":
        stelle = 4 + struct.unpack(">H", jpeg[4:6])[0]
    return jpeg[:stelle] + segment + jpeg[stelle:]


def raw_datei(werte: dict, vorschau: bytes, dng: bool = False) -> bytes:
    """Kuenstliche RAW-Datei im TIFF-Aufbau (wie ARW, NEF, CR2, DNG, ORF, RW2):
    IFD0 mit einem 1x1-Bild und den Kameradaten, IFD1 mit dem Vorschau-JPEG."""
    ifd0, exif = exif_ifds(werte)
    for tag, wert in ((256, 1), (257, 1), (258, 8), (259, 1), (262, 1), (277, 1), (278, 1)):
        ifd0.short(tag, wert)
    ifd0.zeiger(273, "pixel").long(279, 1)
    if dng:
        ifd0.roh(0xC612, b"\x01\x04\x00\x00")       # DNGVersion 1.4
    ifd1 = Ifd().short(0x0103, 6).zeiger(0x0201, "vorschau").long(0x0202, len(vorschau))
    return tiff([("ifd0", ifd0), ("exif", exif), ("ifd1", ifd1)],
                [("pixel", b"\x80"), ("vorschau", vorschau)], {"ifd0": "ifd1"})


# ------------------------------------------------------- ISO-BMFF/HEIF ----


def box(art: bytes, inhalt: bytes) -> bytes:
    return struct.pack(">I", 8 + len(inhalt)) + art + inhalt


def vollbox(art: bytes, version: int, flags: int, inhalt: bytes) -> bytes:
    return box(art, struct.pack(">I", (version << 24) | flags) + inhalt)


def heic(werte: dict, vorschau: bytes) -> bytes:
    """HEIC mit zwei Eintraegen: das Hauptbild (Platzhalter, kein echtes HEVC)
    und ein EXIF-Eintrag (cdsc) mit Kameradaten und Vorschau-JPEG. Anzeigen
    laesst sich nur die Vorschau - genau die zeigt der Reiter „Sichten“."""
    exif = struct.pack(">I", 6) + b"Exif\0\0" + exif_block(werte, vorschau)
    bild = b"\x00\x00\x00\x10\x26\x01" + b"\x00" * 14
    ftyp = box(b"ftyp", b"heic" + struct.pack(">I", 0) + b"mif1heic")
    hdlr = vollbox(b"hdlr", 0, 0, struct.pack(">I", 0) + b"pict" + b"\0" * 12 + b"\0")
    pitm = vollbox(b"pitm", 0, 0, struct.pack(">H", 1))
    iinf = vollbox(b"iinf", 0, 0, struct.pack(">H", 2)
                   + vollbox(b"infe", 2, 0, struct.pack(">HH", 1, 0) + b"hvc1\0")
                   + vollbox(b"infe", 2, 0, struct.pack(">HH", 2, 0) + b"Exif\0"))
    iref = vollbox(b"iref", 0, 0, box(b"cdsc", struct.pack(">HHH", 2, 1, 1)))
    hvcc = box(b"hvcC", bytes([1, 1, 0x60, 0, 0, 0, 0x90, 0, 0, 0, 0, 0, 0x5D, 0xF0, 0, 0xFC, 0xFD,
                               0xF8, 0xF8, 0, 0, 0x0F, 0]))
    ispe = vollbox(b"ispe", 0, 0, struct.pack(">II", 1200, 800))
    iprp = box(b"iprp", box(b"ipco", hvcc + ispe)
               + vollbox(b"ipma", 0, 0, struct.pack(">IHB", 1, 1, 2) + bytes([0x81, 0x02])))

    def meta(start: int) -> bytes:
        iloc = vollbox(b"iloc", 0, 0, bytes([0x44, 0x00]) + struct.pack(">H", 2)
                       + struct.pack(">HHHII", 1, 0, 1, start, len(bild))
                       + struct.pack(">HHHII", 2, 0, 1, start + len(bild), len(exif)))
        return vollbox(b"meta", 0, 0, hdlr + pitm + iloc + iinf + iref + iprp)

    start = len(ftyp) + len(meta(0)) + 8
    return ftyp + meta(start) + box(b"mdat", bild + exif)


def sekunden_1904(zeit_utc: datetime | None) -> int:
    """QuickTime zaehlt Sekunden seit 1904 (UTC); None -> 0 (kein Datum)."""
    if zeit_utc is None:
        return 0
    epoche = datetime(1904, 1, 1, tzinfo=timezone.utc)
    return int((zeit_utc.replace(tzinfo=timezone.utc) - epoche).total_seconds())


def film(jpeg: bytes, breite: int, hoehe: int, marke: bytes = b"qt  ",
         zeit_utc: datetime | None = None, sony_xml: str | None = None) -> bytes:
    """MOV/MP4/3GP mit einer Videospur aus einem einzigen Motion-JPEG-Bild
    (eine Sekunde lang). zeit_utc steht im Movie-Header (CreateDate);
    sony_xml haengt Sonys NonRealTimeMeta als meta/xml-Box ans Ende, wie
    Sony-Kameras es tun (CreationDateValue mit Zeitzone, Modell)."""
    zeitbasis, dauer = 600, 600
    sekunden = sekunden_1904(zeit_utc)
    ftyp = box(b"ftyp", marke + struct.pack(">I", 0x200) + marke + (b"mp42" if marke != b"qt  " else b""))
    jpeg_stelle = len(ftyp) + 8
    mdat = box(b"mdat", jpeg)
    matrix = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    mvhd = vollbox(b"mvhd", 0, 0, struct.pack(">IIII", sekunden, sekunden, zeitbasis, dauer)
                   + struct.pack(">IH", 0x10000, 0x100) + b"\0" * 10 + matrix + b"\0" * 24 + struct.pack(">I", 2))
    tkhd = vollbox(b"tkhd", 0, 3, struct.pack(">IIIII", sekunden, sekunden, 1, 0, dauer) + b"\0" * 8
                   + struct.pack(">hhhH", 0, 0, 0, 0) + matrix + struct.pack(">II", breite << 16, hoehe << 16))
    mdhd = vollbox(b"mdhd", 0, 0, struct.pack(">IIII", sekunden, sekunden, zeitbasis, dauer) + struct.pack(">HH", 0x55C4, 0))
    hdlr = vollbox(b"hdlr", 0, 0, struct.pack(">I", 0) + b"vide" + b"\0" * 12 + b"VideoHandler\0")
    vmhd = vollbox(b"vmhd", 0, 1, b"\0" * 8)
    dinf = box(b"dinf", vollbox(b"dref", 0, 0, struct.pack(">I", 1) + vollbox(b"url ", 0, 1, b"")))
    name = b"Photo - JPEG"
    eintrag = (b"\0" * 6 + struct.pack(">H", 1) + struct.pack(">HH", 0, 0) + b"appl" + struct.pack(">II", 0, 512)
               + struct.pack(">HH", breite, hoehe) + struct.pack(">II", 0x480000, 0x480000) + struct.pack(">I", 0)
               + struct.pack(">H", 1) + bytes([len(name)]) + name + b"\0" * (31 - len(name)) + struct.pack(">hh", 24, -1))
    stbl = box(b"stbl", vollbox(b"stsd", 0, 0, struct.pack(">I", 1) + box(b"jpeg", eintrag))
               + vollbox(b"stts", 0, 0, struct.pack(">III", 1, 1, dauer))
               + vollbox(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1))
               + vollbox(b"stsz", 0, 0, struct.pack(">III", 0, 1, len(jpeg)))
               + vollbox(b"stco", 0, 0, struct.pack(">II", 1, jpeg_stelle)))
    trak = box(b"trak", tkhd + box(b"mdia", mdhd + hdlr + box(b"minf", vmhd + dinf + stbl)))
    moov = box(b"moov", mvhd + trak)
    ende = b""
    if sony_xml is not None:
        hdlr_nrtm = box(b"hdlr", b"\0" * 8 + b"nrtm" + b"\0" * 13)
        ende = box(b"meta", b"\0\0\0\0" + hdlr_nrtm + box(b"xml ", sony_xml.encode("utf-8")))
    return ftyp + mdat + moov + ende


# ---------------------------------------------------------------- AVI ----


def _chunk(fcc: bytes, daten: bytes) -> bytes:
    return fcc + struct.pack("<I", len(daten)) + daten + (b"\0" if len(daten) % 2 else b"")


def avi(jpeg: bytes, breite: int, hoehe: int, idit: str) -> bytes:
    """AVI mit einem Motion-JPEG-Bild und dem Aufnahmedatum im IDIT-Eintrag
    ("THU AUG 15 14:22:33 2007"), wie alte Digitalkameras es schreiben."""
    avih = struct.pack("<IIIIIIIIII", 1000000, 0, 0, 0x10, 1, 0, 1, len(jpeg) + 8, breite, hoehe) + b"\0" * 16
    strh = b"vids" + b"MJPG" + struct.pack("<IHHIIIIIIIIhhhh", 0, 0, 0, 0, 1, 1, 0, 1, len(jpeg) + 8,
                                           0xFFFFFFFF, 0, 0, 0, breite, hoehe)
    strf = struct.pack("<IiiHH4sIiiII", 40, breite, hoehe, 1, 24, b"MJPG", breite * hoehe * 3, 0, 0, 0, 0)
    hdrl = _chunk(b"LIST", b"hdrl" + _chunk(b"avih", avih)
                  + _chunk(b"LIST", b"strl" + _chunk(b"strh", strh) + _chunk(b"strf", strf)))
    movi = _chunk(b"LIST", b"movi" + _chunk(b"00dc", jpeg))
    idx1 = _chunk(b"idx1", b"00dc" + struct.pack("<III", 0x10, 4, len(jpeg)))
    inhalt = b"AVI " + hdrl + _chunk(b"IDIT", idit.encode("ascii") + b"\n\0") + movi + idx1
    return b"RIFF" + struct.pack("<I", len(inhalt)) + inhalt


def idit_text(zeit: datetime) -> str:
    tage = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    monate = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    return f"{tage[zeit.weekday()]} {monate[zeit.month - 1]} {zeit.day:02d} {zeit:%H:%M:%S} {zeit.year}"


# ------------------------------------------------------- Begleitdateien ----


def xmp(datum: str | None = None, feld: str = "exif:DateTimeOriginal", bewertung: int | None = None,
        farbe: str | None = None, titel: str | None = None) -> str:
    """XMP-Begleitdatei wie von Lightroom: wahlweise mit Datum (feld),
    Sternen (xmp:Rating) und Farbe (xmp:Label)."""
    zeilen = []
    if datum:
        zeilen.append(f"   <{feld}>{datum}</{feld}>")
    if bewertung is not None:
        zeilen.append(f"   <xmp:Rating>{bewertung}</xmp:Rating>")
    if farbe:
        zeilen.append(f"   <xmp:Label>{farbe}</xmp:Label>")
    if titel:
        zeilen.append("   <dc:description><rdf:Alt><rdf:li xml:lang=\"x-default\">"
                      f"{_xml(titel)}</rdf:li></rdf:Alt></dc:description>")
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmlns:exif="http://ns.adobe.com/exif/1.0/"\n'
        '    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(zeilen) + ("\n" if zeilen else "")
        + "  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end=\"w\"?>\n"
    )


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def sony_xml(ortszeit_mit_zone: str, modell: str | None, seriennummer: str = "4711") -> str:
    """Sonys NonRealTimeMeta (Begleitdatei C0001M01.XML oder eingebettet)."""
    geraet = f'  <Device manufacturer="Sony" modelName="{_xml(modell)}" serialNo="{seriennummer}"/>\n' if modell else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20"'
            f' lastUpdate="{ortszeit_mit_zone}">\n'
            '  <Duration value="25"/>\n'
            f'  <CreationDate value="{ortszeit_mit_zone}"/>\n'
            + geraet
            + "</NonRealTimeMeta>\n")


def aae(text: str) -> str:
    """Apple-Bearbeitungsdatei (.AAE) - eine Property-Liste, kein Datum."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            '\t<key>adjustmentBaseVersion</key>\n\t<integer>0</integer>\n'
            '\t<key>adjustmentFormatIdentifier</key>\n\t<string>com.apple.photo</string>\n'
            f'\t<key>adjustmentFormatVersion</key>\n\t<string>{_xml(text)}</string>\n'
            '</dict>\n</plist>\n')


def pdf(text: str) -> bytes:
    """Ein kleines, gueltiges PDF mit einer Textzeile."""
    inhalt = f"BT /F1 18 Tf 40 760 Td ({text.encode('latin-1', 'replace').decode('latin-1')}) Tj ET".encode("latin-1")
    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    teile = [b"%PDF-1.4\n"]
    stellen = []
    for nr, obj in enumerate(objekte, start=1):
        stellen.append(sum(len(t) for t in teile))
        teile.append(f"{nr} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = sum(len(t) for t in teile)
    teile.append(f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode())
    teile.extend(f"{s:010d} 00000 n \n".encode() for s in stellen)
    teile.append(f"trailer\n<< /Size {len(objekte) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return b"".join(teile)


def gif(farbe: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    """Ein 1x1-GIF (zaehlt nicht als Foto: steht in keiner Endungsliste)."""
    r, g, b = farbe
    return (b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0) + bytes([r, g, b, 0, 0, 0])
            + b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + b"\x02\x02\x44\x01\x00\x3b")
