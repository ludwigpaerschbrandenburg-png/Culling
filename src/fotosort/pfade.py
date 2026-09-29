"""Pfad-Hilfen: langes Windows-Praefix, Netz- und Laufwerkserkennung, Lage
von Quelle und Ziel zueinander.

Die einzige Stelle im Programm, an der Windows und Linux sich unterscheiden
(docs/architektur.md Abschnitt 1). Die Windows-Zweige haengen an
sys.platform und stoeren unter Linux nicht.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PureWindowsPath

# SPEC Abschnitt 6: als Netz geltende Dateisystemtypen unter Linux.
# 9p und virtiofs gehoeren dazu, weil Docker Desktop und WSL2
# Windows-Pfade so einbinden.
NETZ_DATEISYSTEME: frozenset[str] = frozenset(
    {"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "9p", "virtiofs"}
)

_IST_WINDOWS = sys.platform.startswith("win")

# GetDriveType-Ergebnis fuer ein Netzlaufwerk.
_DRIVE_REMOTE = 4


# ----------------------------------------------------------- Grundlagen ----


def aufloesen(p: Path) -> Path:
    """Aufgeloester, absoluter Pfad. Verknuepfungen werden mit aufgeloest.

    strict=False, damit auch noch nicht vorhandene Pfade beantwortbar sind.
    """
    return Path(p).resolve(strict=False)


_PRAEFIX = "\\\\?\\"
_PRAEFIX_UNC = "\\\\?\\UNC\\"


def lang_text(text: str) -> str:
    r"""Windows-Schreibweise mit langem Praefix - als reine Textrechnung.

    Steht als eigene Funktion da, damit sie sich unter Linux mit
    PureWindowsPath-Texten testen laesst.
    """
    if text.startswith(_PRAEFIX):
        return text
    if not PureWindowsPath(text).is_absolute():
        return text
    if text.startswith("\\\\"):
        # UNC-Pfad: \\server\freigabe -> \\?\UNC\server\freigabe
        return _PRAEFIX_UNC + text[2:]
    return _PRAEFIX + text


def kurz_text(text: str) -> str:
    r"""Umkehrung von lang_text: das Praefix wieder abnehmen."""
    if text.startswith(_PRAEFIX_UNC):
        return "\\\\" + text[len(_PRAEFIX_UNC) :]
    if text.startswith(_PRAEFIX):
        return text[len(_PRAEFIX) :]
    return text


def lang(p: Path) -> Path:
    r"""Windows: Praefix \\?\ bzw. \\?\UNC\ gegen die 260-Zeichen-Grenze.

    Unter Linux unveraendert. SPEC Abschnitt 5: lange Pfade werden aktiv
    umgangen, nicht nur gemeldet.

    Das Praefix gehoert nur an die Systemschnittstelle (os.scandir, open,
    sqlite3). Alles, was danach verglichen oder gespeichert wird, laeuft
    vorher durch kurz(): Sonst haette ein Eintrag unterhalb der Wurzel das
    Praefix, die Quellwurzel aber nicht, und der Vergleich "liegt in" oder
    "relativ zur Wurzel" schluege fehl.
    """
    if not _IST_WINDOWS:
        return p if isinstance(p, Path) else Path(p)
    return Path(lang_text(str(Path(p))))


def kurz(p) -> Path:
    r"""Das lange Praefix wieder abnehmen. Unter Linux unveraendert."""
    if not _IST_WINDOWS:
        return Path(p)
    return Path(kurz_text(str(p)))


def _vorhandener_teil(p: Path) -> Path:
    """Naechster Vorfahre des Pfades, den es wirklich gibt."""
    kandidat = aufloesen(p)
    while True:
        if kandidat.exists():
            return kandidat
        eltern = kandidat.parent
        if eltern == kandidat:
            return kandidat
        kandidat = eltern


def _mountpunkte() -> list[tuple[str, str]]:
    """(Einhaengepunkt, Typ) aus /proc/mounts, laengster Punkt zuerst."""
    eintraege: list[tuple[str, str]] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            for zeile in fh:
                teile = zeile.split()
                if len(teile) < 3:
                    continue
                punkt = teile[1].replace("\\040", " ").replace("\\011", "\t")
                eintraege.append((punkt, teile[2]))
    except OSError:
        return []
    eintraege.sort(key=lambda e: len(e[0]), reverse=True)
    return eintraege


def dateisystem_typ(p: Path) -> str:
    """Typ des Dateisystems, auf dem der Pfad liegt; "" wenn unbekannt.

    Linux: ueber /proc/mounts, laengster passender Einhaengepunkt.
    """
    if _IST_WINDOWS:
        return ""
    text = str(_vorhandener_teil(p))
    for punkt, typ in _mountpunkte():
        if text == punkt:
            return typ
        praefix = punkt if punkt.endswith("/") else punkt + "/"
        if text.startswith(praefix):
            return typ
    return ""


def _windows_netzlaufwerk(p: Path) -> bool:  # pragma: no cover - nur Windows
    text = str(aufloesen(p))
    if text.startswith("\\\\?\\UNC\\") or (
        text.startswith("\\\\") and not text.startswith("\\\\?\\")
    ):
        return True
    if text.startswith("\\\\?\\"):
        text = text[4:]
    wurzel = os.path.splitdrive(text)[0]
    if not wurzel:
        return True
    try:
        import ctypes

        art = ctypes.windll.kernel32.GetDriveTypeW(wurzel + "\\")
    except Exception:
        return True
    return int(art) == _DRIVE_REMOTE


def ist_netzpfad(p: Path) -> bool:
    """Liegt der Pfad auf einem Netz-Dateisystem?

    Laesst sich der Typ nicht bestimmen, gilt der Pfad als Netzpfad
    (docs/architektur.md Abschnitt 2: die vorsichtige Antwort).
    """
    if _IST_WINDOWS:
        return _windows_netzlaufwerk(p)
    typ = dateisystem_typ(p)
    if not typ:
        return True
    return typ in NETZ_DATEISYSTEME


def gleiches_laufwerk(a: Path, b: Path) -> bool:
    """Liegen beide Pfade nachweislich auf demselben Laufwerk?

    False, wenn es sich nicht sicher feststellen laesst oder einer der
    beiden im Netz liegt (SPEC Abschnitt 4 Phase 3).
    """
    if ist_netzpfad(a) or ist_netzpfad(b):
        return False
    try:
        return _vorhandener_teil(a).stat().st_dev == _vorhandener_teil(b).stat().st_dev
    except OSError:
        return False


# ------------------------------------------------- Lage Quelle und Ziel ----


def liegt_in(kind: Path, eltern: Path) -> bool:
    """Liegt "kind" in "eltern"? Arbeitet auf aufgeloesten Pfaden.

    Gleichheit zaehlt mit: Der Zielordner selbst liegt im Ziel.
    """
    k = aufloesen(kind)
    e = aufloesen(eltern)
    try:
        return k == e or k.is_relative_to(e)
    except ValueError:
        return False


def ordner_kennung(p: Path) -> tuple | None:
    """(Geraet, Inode) eines vorhandenen Ordners; None, wenn es ihn nicht
    gibt oder das System keine Inode-Nummern liefert."""
    try:
        st = os.stat(lang(p))
    except OSError:
        return None
    if not st.st_ino:
        return None
    return (st.st_dev, st.st_ino)


def _liegt_in_nach_kennung(kind: Path, eltern: Path) -> bool:
    """Wie liegt_in, aber ueber Geraete- und Inode-Nummern der Ordnerkette:
    erkennt denselben Ordner auch ueber einen zweiten Pfad (Bind-Mount,
    zweite Netzfreigabe), den resolve() nicht zusammenfuehrt."""
    ke = ordner_kennung(eltern)
    if ke is None:
        return False
    p = aufloesen(kind)
    while True:
        if ordner_kennung(p) == ke:
            return True
        if p.parent == p:
            return False
        p = p.parent


#: Wo ein Archiv seine Kennung ablegt (wie db.ARCHIV_UNTERORDNER / db.ARCHIV_ID_DATEI;
#: hier noch einmal, weil db dieses Modul benutzt und nicht umgekehrt).
ARCHIV_MARKE = (".fotosortierer", "archiv-id.txt")


def archiv_kennung_in(ordner: Path) -> str:
    """Die Archiv-Kennung, die in diesem Ordner liegt ('' ohne). Daran wird das
    Ziel auch ueber einen zweiten Weg erkannt - zwei Einhaengungen derselben
    Netzfreigabe, zwei Laufwerksbuchstaben -, den weder resolve() noch
    Geraete- und Inode-Nummern zusammenfuehren."""
    try:
        text = lang(Path(ordner) / ARCHIV_MARKE[0] / ARCHIV_MARKE[1]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return text.strip().lstrip("\ufeff")


def lage_pruefen(quelle: Path, ziel: Path) -> str:
    """"gleich" | "ziel_in_quelle" | "quelle_in_ziel" | "getrennt".

    Erst ueber die aufgeloesten Pfade, dann ueber Geraete- und
    Inode-Nummern (SPEC §4 Phase 1: derselbe Ort ueber zwei Pfade), zuletzt
    ueber die Archiv-Kennung: Traegt die Quelle oder einer ihrer
    uebergeordneten Ordner die Kennung des Ziels, ist es das Ziel selbst.
    """
    q = aufloesen(quelle)
    z = aufloesen(ziel)
    if q == z:
        return "gleich"
    kq, kz = ordner_kennung(q), ordner_kennung(z)
    if kq is not None and kq == kz:
        return "gleich"
    if liegt_in(z, q) or _liegt_in_nach_kennung(z, q):
        return "ziel_in_quelle"
    if liegt_in(q, z) or _liegt_in_nach_kennung(q, z):
        return "quelle_in_ziel"
    kennung = archiv_kennung_in(z)
    if kennung:
        if archiv_kennung_in(q) == kennung:
            return "gleich"
        p = q
        while p.parent != p:
            p = p.parent
            if archiv_kennung_in(p) == kennung:
                return "quelle_in_ziel"
    return "getrennt"


def laufwerk_kennung(p: Path) -> str:
    """Kennung des physischen Laufwerks, nach der Quellen gruppiert werden.

    SPEC Abschnitt 4 Phase 1: Quellen auf verschiedenen Laufwerken werden
    parallel gelesen, auf demselben nacheinander. Linux: Geraetenummer der
    Wurzel. Windows: Laufwerksbuchstabe; bei Netzpfaden der Server, nicht die
    Freigabe, weil mehrere Freigaben meist auf denselben Platten liegen. Dass
    zwei Laufwerksbuchstaben auf derselben Platte liegen koennen, wird hier
    nicht erkannt (docs/todo.md, Phase 6).
    """
    p = aufloesen(Path(p))
    if _IST_WINDOWS:  # pragma: no cover - nur Windows
        text = kurz_text(str(p))
        if text.startswith("\\\\"):
            teile = text.lstrip("\\").split("\\")
            return "server:" + (teile[0].lower() if teile else "?")
        laufwerk = p.drive.rstrip(":").upper()
        return "laufwerk:" + (laufwerk or "?")
    try:
        return "dev:" + str(os.stat(_vorhandener_teil(p)).st_dev)
    except OSError:
        return "dev:?"


# ---------------------------------------- nicht ueberschreibendes Umbenennen ----


class KeinNoReplace(OSError):
    """Das Dateisystem kann kein nicht ueberschreibendes Umbenennen (exFAT, FAT32)."""


def umbenennen_ohne_ueberschreiben(von: Path, nach: Path) -> None:
    """von -> nach, ohne je eine vorhandene Datei zu ersetzen (SPEC §5).

    Linux: os.link auf den Zielnamen (schlaegt bei belegtem Namen mit
    FileExistsError fehl), danach os.unlink der Quelle. Windows: MoveFileExW
    OHNE MOVEFILE_REPLACE_EXISTING. Nie os.rename - das ersetzt still.
    Wirft FileExistsError, wenn der Zielname belegt ist, und KeinNoReplace,
    wenn das Dateisystem das Verfahren nicht kann.
    """
    von = Path(von)
    nach = Path(nach)
    if _IST_WINDOWS:  # pragma: no cover - nur Windows
        import ctypes
        from ctypes import wintypes

        # use_last_error=True: Nur so liefert ctypes.get_last_error() die
        # Fehlernummer GENAU dieses Aufrufs, nicht die eines spaeteren
        # Python-internen Aufrufs.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        bewegen = kernel32.MoveFileExW
        bewegen.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        bewegen.restype = wintypes.BOOL
        # MOVEFILE_WRITE_THROUGH (8): erst zurueckkehren, wenn der Umzug auf
        # der Platte steht. Ohne MOVEFILE_REPLACE_EXISTING: nie ueberschreiben.
        if bewegen(str(lang(von)), str(lang(nach)), 8):
            return
        fehler = ctypes.get_last_error()
        if fehler in (80, 183):  # ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS
            raise FileExistsError(str(nach))
        if fehler in (2, 3):  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND
            raise FileNotFoundError(str(von))
        raise OSError(fehler, f"MoveFileEx fehlgeschlagen (Fehler {fehler})", str(von))
    import errno

    if _renameat2_noreplace(von, nach):
        ordner_sichern(nach.parent)
        return
    # Rueckfall: link + unlink. Dazwischen traegt die Datei zwei Namen; kann
    # der zweite Schritt nicht gelingen (Quellordner nicht beschreibbar),
    # wird es gar nicht erst versucht - und scheitert er doch, wird der eben
    # angelegte eigene Name wieder entfernt: Die Quelle bleibt, wie sie war.
    if not os.access(lang(von.parent), os.W_OK):
        raise KeinNoReplace(f"Quellordner nicht beschreibbar: {von.parent}")
    try:
        os.link(lang(von), lang(nach))
    except FileExistsError:
        raise
    except OSError as fehler:
        if fehler.errno in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EMLINK, errno.EXDEV):
            raise KeinNoReplace(str(fehler)) from fehler
        raise
    try:
        os.unlink(lang(von))
    except OSError:
        try:
            os.unlink(lang(nach))
        except OSError:
            pass
        raise
    ordner_sichern(nach.parent)


_RENAME_NOREPLACE = 1
_renameat2 = None       # None = noch nicht gesucht, False = gibt es nicht


def _renameat2_noreplace(von: Path, nach: Path) -> bool:
    """Linux: renameat2(..., RENAME_NOREPLACE) - atomar und nie ueberschreibend
    (SPEC §5). True bei Erfolg; False, wenn Kernel oder Dateisystem es nicht
    koennen (dann link + unlink). FileExistsError bei belegtem Namen."""
    global _renameat2
    if not sys.platform.startswith("linux"):
        return False
    import ctypes
    import errno

    if _renameat2 is None:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            funktion = libc.renameat2
            funktion.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            funktion.restype = ctypes.c_int
            _renameat2 = funktion
        except (OSError, AttributeError):
            _renameat2 = False
    if not _renameat2:
        return False
    at_fdcwd = -100
    if _renameat2(at_fdcwd, os.fsencode(lang(von)), at_fdcwd, os.fsencode(lang(nach)), _RENAME_NOREPLACE) == 0:
        return True
    nummer = ctypes.get_errno()
    if nummer == errno.EEXIST:
        raise FileExistsError(nummer, os.strerror(nummer), str(nach))
    if nummer in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EPERM):
        return False                     # nicht unterstuetzt: Rueckfall
    if nummer == errno.EXDEV:
        raise KeinNoReplace(os.strerror(nummer))
    raise OSError(nummer, os.strerror(nummer), str(von))


def ordner_sichern(ordner: Path) -> None:
    """Den Verzeichniseintrag eines Ordners auf die Platte zwingen (fsync auf
    den Ordner). Unter Windows gibt es das nicht - NTFS schreibt Metadaten
    ueber sein Journal; dort und auf Dateisystemen ohne Ordner-fsync (einige
    Netzlaufwerke) ist das ein Nichts."""
    if _IST_WINDOWS:  # pragma: no cover - nur Windows
        return
    try:
        fd = os.open(lang(ordner), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def kann_ohne_ueberschreiben(ordner: Path) -> bool:
    """Einmalige Probe je Ziel-Dateisystem mit einer Wegwerfdatei (SPEC §5)."""
    if _IST_WINDOWS:  # pragma: no cover - MoveFileEx geht ueberall
        return True
    import uuid

    a = Path(ordner) / f".fotosort_probe_{uuid.uuid4().hex}"
    b = Path(str(a) + ".b")
    try:
        lang(a).write_bytes(b"probe")
        umbenennen_ohne_ueberschreiben(a, b)
        return True
    except KeinNoReplace:
        return False
    finally:
        for p in (a, b):
            try:
                os.unlink(lang(p))
            except OSError:
                pass


def freier_platz(pfad: Path) -> int:
    import shutil

    return shutil.disk_usage(lang(_vorhandener_teil(Path(pfad)))).free
