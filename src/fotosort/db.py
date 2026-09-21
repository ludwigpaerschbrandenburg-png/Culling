"""SQLite: Schema, Statuswechsel, Sammelschreiben (SPEC Abschnitt 6).

Die Datenbank liegt immer lokal, nie auf einem Netzlaufwerk. Sie ist das
Gedaechtnis des Archivs: Es wird nie eine Zeile geloescht.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote_to_bytes

from . import FotosortFehler, meldungen, pfade

DATEINAME = "fotosort.db"
ARCHIV_UNTERORDNER = ".fotosortierer"
ARCHIV_ID_DATEI = "archiv-id.txt"
SICHERUNG = "fotosort.db.sicherung"
SICHERUNG_NEU = "fotosort.db.sicherung.neu"
SICHERUNG_VORHER = "fotosort.db.sicherung.vorher"
SPERRDATEI = "fotosort.sperre"

# So lange wartet SQLite auf eine belegte Datenbank, bevor es aufgibt.
BUSY_TIMEOUT_MS = 15000

# SPEC Abschnitt 6: genau diese elf Werte, umlautfrei. An diesen
# Zeichenketten haengt die Loeschberechtigung.
STATUS: frozenset[str] = frozenset(
    {
        "gefunden",
        "analysiert",
        "kopieren_laeuft",
        "kopiert",
        "geprueft",
        "verschoben",
        "duplikat",
        "duplikat_bestaetigt",
        "quelle_geloescht",
        "uebersprungen",
        "fehler",
    }
)

# Reihenfolge der Stufen fuer "fotosort status" (SPEC Abschnitt 8).
STUFEN: tuple[str, ...] = (
    "gefunden",
    "analysiert",
    "kopieren_laeuft",
    "kopiert",
    "geprueft",
    "quelle_geloescht",
)

# Anzeigereihenfolge aller Status.
STATUS_REIHE: tuple[str, ...] = (
    "gefunden",
    "analysiert",
    "kopieren_laeuft",
    "kopiert",
    "geprueft",
    "verschoben",
    "duplikat",
    "duplikat_bestaetigt",
    "quelle_geloescht",
    "uebersprungen",
    "fehler",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS dateien (
    quellpfad               TEXT PRIMARY KEY,
    quellwurzel             TEXT NOT NULL,
    groesse                 INTEGER NOT NULL DEFAULT 0,
    mtime                   REAL    NOT NULL DEFAULT 0,
    dateityp                TEXT    NOT NULL DEFAULT '',
    hash                    TEXT    NOT NULL DEFAULT '',
    kamera                  TEXT    NOT NULL DEFAULT '',
    aufnahme_zeit           TEXT    NOT NULL DEFAULT '',
    datum_quelle            INTEGER,
    datum_sicher            INTEGER,
    gruppe                  TEXT    NOT NULL DEFAULT '',
    zielpfad                TEXT    NOT NULL DEFAULT '',
    status                  TEXT    NOT NULL DEFAULT 'gefunden',
    fehlergrund             TEXT    NOT NULL DEFAULT '',
    bestaetigt_in_lauf      INTEGER,
    gefunden_in_lauf        INTEGER,
    zuletzt_gesehen_in_lauf INTEGER
);

CREATE INDEX IF NOT EXISTS dateien_status  ON dateien (status);
CREATE INDEX IF NOT EXISTS dateien_wurzel  ON dateien (quellwurzel);
CREATE INDEX IF NOT EXISTS dateien_zielpfad ON dateien (zielpfad);

CREATE TABLE IF NOT EXISTS ziel_index (
    zielpfad                TEXT PRIMARY KEY,
    groesse                 INTEGER NOT NULL DEFAULT 0,
    mtime                   REAL    NOT NULL DEFAULT 0,
    hash                    TEXT    NOT NULL DEFAULT '',
    zuletzt_gelesen_in_lauf INTEGER
);

CREATE TABLE IF NOT EXISTS laeufe (
    nummer  INTEGER PRIMARY KEY AUTOINCREMENT,
    befehl  TEXT NOT NULL DEFAULT '',
    start   TEXT NOT NULL DEFAULT '',
    ende    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lauf_ereignisse (
    lauf_nummer INTEGER NOT NULL,
    art         TEXT    NOT NULL,
    pfad        TEXT    NOT NULL DEFAULT '',
    anzahl      INTEGER NOT NULL DEFAULT 1,
    text        TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ereignisse_lauf ON lauf_ereignisse (lauf_nummer, art);
"""

# Sammelschreiben: alle 500 Dateien oder 2 Sekunden (SPEC Abschnitt 6).
STAPEL_DATEIEN = 500
STAPEL_SEKUNDEN = 2.0

_ID_MUSTER = re.compile(r"^[0-9a-f]{32}$")


# ------------------------------------------------------- Pfade speichern ----

# Auf alten Platten, Kameraspeicherkarten und falsch eingehaengten
# SMB-Freigaben kommen Dateinamen vor, die kein gueltiges UTF-8 sind. Python
# traegt solche Bytes als Ersatzzeichen (Surrogate) im Pfadtext; SQLite kann
# sie nicht als Text speichern und wuerde den ganzen Scan abbrechen. Solche
# Pfade werden deshalb umkehrbar umkodiert: ein Kennzeichen vorweg, dahinter
# die Bytes in Prozent-Schreibweise. Alle anderen Pfade bleiben, wie sie sind.
_ROH_KENNZEICHEN = "\ufffd%"


def pfad_text(pfad) -> str:
    """Pfad in die Form bringen, in der er in der Datenbank steht."""
    text = os.fsdecode(pfad) if isinstance(pfad, bytes) else str(pfad)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return _ROH_KENNZEICHEN + quote(os.fsencode(text))
    return text


def text_pfad(text):
    """Umkehrung von pfad_text: aus der Datenbank zurueck in einen Pfad."""
    if isinstance(text, str) and text.startswith(_ROH_KENNZEICHEN):
        return os.fsdecode(unquote_to_bytes(text[len(_ROH_KENNZEICHEN) :]))
    return text


# ------------------------------------------------------------ Archiv-ID ----


def archiv_id_datei(ziel: Path) -> Path:
    return Path(ziel) / ARCHIV_UNTERORDNER / ARCHIV_ID_DATEI


def archiv_id_vorhanden(ziel: Path) -> bool:
    return archiv_id_datei(ziel).is_file()


def archiv_id_lesen_oder_anlegen(ziel: Path) -> str:
    """Archiv-Kennung lesen; beim ersten Scan eines Ziels anlegen.

    Ist die Datei vorhanden, ihr Inhalt aber keine gueltige 32-stellige
    Hex-Kennung, wird abgebrochen. Es wird dann niemals eine neue erzeugt
    (SPEC Abschnitt 6).
    """
    datei = archiv_id_datei(ziel)
    if datei.is_file():
        roh = datei.read_text(encoding="utf-8")
        kennung = roh.strip().lstrip("﻿")
        if not _ID_MUSTER.match(kennung):
            raise FotosortFehler(meldungen.archiv_id_kaputt(datei, roh))
        return kennung
    kennung = uuid.uuid4().hex
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(kennung + "\n", encoding="utf-8")
    return kennung


def archiv_ordner(archiv_id: str, konf=None) -> Path:
    """Ordner mit Datenbank und Konfiguration.

    Vorrang: FOTOSORT_DATENBANK, dann der Konfigurationswert
    datenbank_ort, zuletzt der Standardpfad des Betriebssystems
    (SPEC Abschnitt 6).
    """
    aus_umgebung = os.environ.get("FOTOSORT_DATENBANK", "").strip()
    if aus_umgebung:
        return Path(aus_umgebung) / archiv_id

    if konf is not None:
        aus_konf = str(konf.wert("datenbank.datenbank_ort")).strip()
        if aus_konf:
            return Path(aus_konf) / archiv_id

    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        lokal = os.environ.get("LOCALAPPDATA", "")
        basis = Path(lokal) if lokal else Path.home() / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        basis = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return basis / "fotosortierer" / archiv_id


def datenbank_pfad(ordner: Path) -> Path:
    return Path(ordner) / DATEINAME


def sicherung_pfad(ziel: Path) -> Path:
    return Path(ziel) / ARCHIV_UNTERORDNER / SICHERUNG


# ---------------------------------------------------------- Archivsperre ----


class Archivsperre:
    """Ein Lauf je Archiv (SPEC Abschnitt 6: die Datenbank ist das Gedaechtnis).

    Zwei gleichzeitige Laeufe auf dasselbe Archiv wuerden einander die
    Datenbank wegsperren und beide scheitern. Die Sperre haengt an einer
    eigenen Datei im Archiv-Ordner und wird vom Betriebssystem gehalten:
    Stuerzt das Programm ab, gibt das System sie von selbst wieder frei -
    eine liegengebliebene Sperrdatei blockiert also nie den naechsten Lauf.
    """

    def __init__(self, pfad: Path) -> None:
        self.pfad = Path(pfad)
        self._griff = None

    def nehmen(self) -> bool:
        """True, wenn die Sperre uns gehoert; False, wenn sie belegt ist."""
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        try:
            griff = open(self.pfad, "a+b")
        except OSError:
            # Laesst sich die Sperrdatei nicht anlegen (etwa auf einem nur
            # lesbaren Ordner), wird der Lauf davon nicht aufgehalten.
            return True
        if not _sperren(griff):
            griff.close()
            return False
        self._griff = griff
        return True

    def freigeben(self) -> None:
        if self._griff is None:
            return
        try:
            _entsperren(self._griff)
        finally:
            self._griff.close()
            self._griff = None


def _sperren(griff) -> bool:
    """Datei exklusiv sperren, ohne zu warten. True, wenn es geklappt hat."""
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        import msvcrt

        try:
            msvcrt.locking(griff.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        import fcntl

        fcntl.flock(griff.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:  # pragma: no cover - gibt es unter Linux immer
        return True
    except OSError:
        return False
    return True


def _entsperren(griff) -> None:
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        import msvcrt

        try:
            griff.seek(0)
            msvcrt.locking(griff.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    try:
        import fcntl

        fcntl.flock(griff.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError):  # pragma: no cover
        pass


def sperr_pfad(ordner: Path) -> Path:
    return Path(ordner) / SPERRDATEI


# ------------------------------------------------------------ Datenbank ----


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Datenbank:
    """Eine geoeffnete Archiv-Datenbank mit Sammelschreiben."""

    def __init__(
        self, verbindung: sqlite3.Connection, pfad: Path, sperre: "Archivsperre | None" = None
    ) -> None:
        self.verbindung = verbindung
        self.pfad = pfad
        self.sperre = sperre
        self._offen = 0
        self._letztes_schreiben = time.monotonic()
        self._in_transaktion = False

    # -- oeffnen und schliessen ------------------------------------------

    @classmethod
    def oeffnen(cls, archiv_ordner: Path, sperren: bool = False) -> "Datenbank":
        """Die Archiv-Datenbank oeffnen.

        Mit sperren=True wird das Archiv fuer diesen Lauf belegt; ein
        zweiter Lauf bricht dann mit einer Meldung ab, statt dass sich
        beide gegenseitig die Datenbank wegsperren.
        """
        ordner = Path(archiv_ordner)
        typ = pfade.dateisystem_typ(ordner)
        if pfade.ist_netzpfad(ordner):
            raise FotosortFehler(meldungen.datenbank_auf_netzlaufwerk(ordner, typ))
        ordner.mkdir(parents=True, exist_ok=True)

        sperre = None
        if sperren:
            sperre = Archivsperre(sperr_pfad(ordner))
            if not sperre.nehmen():
                raise FotosortFehler(meldungen.archiv_belegt(ordner))

        pfad = datenbank_pfad(ordner)
        try:
            verbindung = sqlite3.connect(
                str(pfade.lang(pfad)),
                isolation_level=None,
                timeout=BUSY_TIMEOUT_MS / 1000.0,
            )
            verbindung.row_factory = sqlite3.Row
            verbindung.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            verbindung.execute("PRAGMA journal_mode=WAL")
            verbindung.execute("PRAGMA synchronous=NORMAL")
            verbindung.execute("PRAGMA foreign_keys=ON")
            verbindung.executescript(SCHEMA)
        except BaseException:
            if sperre is not None:
                sperre.freigeben()
            raise
        return cls(verbindung, pfad, sperre)

    def schliessen(self) -> None:
        """Schliessen, ohne an einem Folgefehler haengen zu bleiben.

        Nach einem Abbruch mit Strg+C steht die Verbindung unter Umstaenden
        schief; das darf den Rueckgabewert des Programms nicht mehr aendern.
        """
        try:
            self.stapel_schreiben()
        except sqlite3.Error:
            pass
        try:
            self.verbindung.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        try:
            self.verbindung.close()
        except sqlite3.Error:
            pass
        if self.sperre is not None:
            self.sperre.freigeben()
            self.sperre = None

    # -- Sammelschreiben --------------------------------------------------

    def _beginnen(self) -> None:
        if not self._in_transaktion:
            self.verbindung.execute("BEGIN")
            self._in_transaktion = True

    def stapel_schreiben(self) -> None:
        """Sammelschreiben erzwingen.

        Die Merkvariable wird VOR dem COMMIT zurueckgesetzt: Kommt Strg+C
        genau waehrend des COMMIT, ist die Transaktion beendet, und ein
        zweiter Versuch duerfte nicht noch einmal ein COMMIT absetzen.
        """
        if self._in_transaktion:
            self._in_transaktion = False
            try:
                self.verbindung.execute("COMMIT")
            except sqlite3.OperationalError as fehler:
                if "no transaction is active" not in str(fehler):
                    raise
        self._offen = 0
        self._letztes_schreiben = time.monotonic()

    def _vielleicht_schreiben(self) -> None:
        self._offen += 1
        if (
            self._offen >= STAPEL_DATEIEN
            or (time.monotonic() - self._letztes_schreiben) >= STAPEL_SEKUNDEN
        ):
            self.stapel_schreiben()

    # -- Laeufe -----------------------------------------------------------

    def lauf_beginnen(self, befehl: str) -> int:
        self.stapel_schreiben()
        zeiger = self.verbindung.execute(
            "INSERT INTO laeufe (befehl, start, ende) VALUES (?, ?, '')",
            (befehl, _jetzt()),
        )
        return int(zeiger.lastrowid)

    def lauf_beenden(self, nummer: int) -> None:
        self.stapel_schreiben()
        self.verbindung.execute(
            "UPDATE laeufe SET ende = ? WHERE nummer = ?", (_jetzt(), nummer)
        )

    def letzter_lauf(self) -> sqlite3.Row | None:
        return self.verbindung.execute(
            "SELECT nummer, befehl, start, ende FROM laeufe ORDER BY nummer DESC LIMIT 1"
        ).fetchone()

    # -- Dateien ----------------------------------------------------------

    def datei_gesehen(
        self,
        quellpfad,
        quellwurzel,
        groesse: int,
        mtime: float,
        dateityp: str,
        lauf: int,
    ) -> str:
        """Eine gefundene Datei melden (SPEC Abschnitt 6, "Zweiter Scan").

        Gibt "neu", "unveraendert" oder "veraendert" zurueck.
        """
        quellpfad = pfad_text(quellpfad)
        quellwurzel = pfad_text(quellwurzel)
        self._beginnen()
        zeile = self.verbindung.execute(
            "SELECT groesse, mtime FROM dateien WHERE quellpfad = ?", (quellpfad,)
        ).fetchone()

        if zeile is None:
            self.verbindung.execute(
                "INSERT INTO dateien (quellpfad, quellwurzel, groesse, mtime,"
                " dateityp, status, gefunden_in_lauf, zuletzt_gesehen_in_lauf)"
                " VALUES (?, ?, ?, ?, ?, 'gefunden', ?, ?)",
                (quellpfad, quellwurzel, int(groesse), float(mtime), dateityp, lauf, lauf),
            )
            self._vielleicht_schreiben()
            return "neu"

        unveraendert = int(zeile["groesse"]) == int(groesse) and _gleiche_zeit(
            zeile["mtime"], mtime
        )
        if unveraendert:
            # Die Zeile bleibt, wie sie ist. Nur das Gesehen-Datum wandert mit.
            self.verbindung.execute(
                "UPDATE dateien SET zuletzt_gesehen_in_lauf = ?, quellwurzel = ?"
                " WHERE quellpfad = ?",
                (lauf, quellwurzel, quellpfad),
            )
            self._vielleicht_schreiben()
            return "unveraendert"

        # Veraendert: Status faellt auf gefunden zurueck, Hash, Zielpfad und
        # bestaetigt_in_lauf werden geleert (SPEC Abschnitt 6).
        self.verbindung.execute(
            "UPDATE dateien SET quellwurzel = ?, groesse = ?, mtime = ?, dateityp = ?,"
            " hash = '', zielpfad = '', bestaetigt_in_lauf = NULL,"
            " status = 'gefunden', fehlergrund = '', zuletzt_gesehen_in_lauf = ?"
            " WHERE quellpfad = ?",
            (quellwurzel, int(groesse), float(mtime), dateityp, lauf, quellpfad),
        )
        self._vielleicht_schreiben()
        return "veraendert"

    def status_setzen(
        self, quellpfad, status: str, fehlergrund: str = "", lauf: int | None = None
    ) -> None:
        """Status einer bekannten Zeile setzen."""
        if status not in STATUS:
            raise ValueError(f"Unbekannter Status: {status!r}")
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = ?, fehlergrund = ? WHERE quellpfad = ?",
            (status, fehlergrund, pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def zeile(self, quellpfad) -> sqlite3.Row | None:
        return self.verbindung.execute(
            "SELECT * FROM dateien WHERE quellpfad = ?", (pfad_text(quellpfad),)
        ).fetchone()

    def nicht_mehr_gesehen(self, quellwurzel, lauf: int) -> list[str]:
        """Bekannte Quellpfade, die dieser Scan nicht mehr gefunden hat.

        Nur fuer die gerade gescannte Wurzel (SPEC Abschnitt 6). Dateien mit
        Status quelle_geloescht oder verschoben fehlen erwartungsgemaess.
        """
        self.stapel_schreiben()
        zeilen = self.verbindung.execute(
            "SELECT quellpfad FROM dateien WHERE quellwurzel = ?"
            " AND (zuletzt_gesehen_in_lauf IS NULL OR zuletzt_gesehen_in_lauf != ?)"
            " AND status NOT IN ('quelle_geloescht', 'verschoben')"
            " ORDER BY quellpfad",
            (pfad_text(quellwurzel), lauf),
        ).fetchall()
        return [text_pfad(z["quellpfad"]) for z in zeilen]

    def nicht_mehr_gesehen_zaehlen(self, quellwurzel, lauf: int) -> int:
        """Nur die Anzahl - ohne alle Pfade in den Speicher zu holen.

        Bei einer halben Million Zeilen waeren das sonst mehrere zehn
        Megabyte fuer eine einzige Zahl.
        """
        self.stapel_schreiben()
        zeile = self.verbindung.execute(
            "SELECT COUNT(*) AS n FROM dateien WHERE quellwurzel = ?"
            " AND (zuletzt_gesehen_in_lauf IS NULL OR zuletzt_gesehen_in_lauf != ?)"
            " AND status NOT IN ('quelle_geloescht', 'verschoben')",
            (pfad_text(quellwurzel), lauf),
        ).fetchone()
        return int(zeile["n"])

    # -- Ereignisse -------------------------------------------------------

    def ereignis(self, lauf: int, art: str, pfad="", anzahl: int = 1, text: str = "") -> None:
        self._beginnen()
        self.verbindung.execute(
            "INSERT INTO lauf_ereignisse (lauf_nummer, art, pfad, anzahl, text)"
            " VALUES (?, ?, ?, ?, ?)",
            (lauf, art, pfad_text(pfad), int(anzahl), text),
        )
        self._vielleicht_schreiben()

    def ereignisse_zaehlen(self, lauf: int, art: str) -> int:
        zeile = self.verbindung.execute(
            "SELECT COALESCE(SUM(anzahl), 0) AS n FROM lauf_ereignisse"
            " WHERE lauf_nummer = ? AND art = ?",
            (lauf, art),
        ).fetchone()
        return int(zeile["n"])

    # -- Zaehler ----------------------------------------------------------

    def zaehler_je_status(self) -> dict[str, int]:
        """Alle elf Status, auch die mit 0."""
        self.stapel_schreiben()
        fertig = {name: 0 for name in STATUS_REIHE}
        for zeile in self.verbindung.execute(
            "SELECT status, COUNT(*) AS n FROM dateien GROUP BY status"
        ):
            fertig[zeile["status"]] = int(zeile["n"])
        return fertig

    def zaehler_je_dateityp(self) -> dict[str, int]:
        self.stapel_schreiben()
        fertig: dict[str, int] = {}
        for zeile in self.verbindung.execute(
            "SELECT dateityp, COUNT(*) AS n FROM dateien GROUP BY dateityp"
        ):
            fertig[zeile["dateityp"]] = int(zeile["n"])
        return fertig

    def gesamtgroesse(self) -> int:
        zeile = self.verbindung.execute(
            "SELECT COALESCE(SUM(groesse), 0) AS s FROM dateien"
        ).fetchone()
        return int(zeile["s"])

    # -- Sicherung --------------------------------------------------------

    def sichern_nach(self, ziel: Path, config_pfad: Path | None = None) -> None:
        """Sicherungskopie ins Ziel (SPEC Abschnitt 6).

        Erst die neue Fassung schreiben, dann den bisherigen Stand
        umbenennen, dann die neue atomar an ihren Platz. Genau zwei Staende.
        """
        self.stapel_schreiben()
        ordner = Path(ziel) / ARCHIV_UNTERORDNER
        ordner.mkdir(parents=True, exist_ok=True)
        neu = ordner / SICHERUNG_NEU
        fertig = ordner / SICHERUNG
        vorher = ordner / SICHERUNG_VORHER

        if neu.exists():
            neu.unlink()
        sicherung = sqlite3.connect(str(pfade.lang(neu)))
        try:
            self.verbindung.backup(sicherung)
        finally:
            sicherung.close()

        # Die einzige Stelle, an der ein Umbenennen ersetzen darf: eigene
        # Sicherungsstaende, keine Bild- oder Videodateien.
        if fertig.exists():
            os.replace(fertig, vorher)
        os.replace(neu, fertig)

        if config_pfad is not None and Path(config_pfad).is_file():
            ziel_conf = ordner / "config.toml"
            zwischen = ordner / "config.toml.neu"
            zwischen.write_bytes(Path(config_pfad).read_bytes())
            os.replace(zwischen, ziel_conf)


#: Toleranz beim Vergleich des Aenderungsdatums, in Sekunden.
#:
#: Sie faengt allein die Rundung beim Hin- und Herrechnen der Fliesskommazahl
#: ab - eine Tausendstelsekunde. Sie ist bewusst NICHT auf die zwei Sekunden
#: der FAT-Dateisysteme gesetzt: FAT rundet jeden Wert auf volle zwei
#: Sekunden ab, liefert fuer dieselbe Datei aber jedes Mal denselben Wert;
#: ein Versatz zwischen zwei Scans entsteht dadurch nicht. Eine Toleranz von
#: zwei Sekunden wuerde dagegen echte Aenderungen verschlucken, die kurz
#: nacheinander geschehen und die Groesse nicht veraendern.
#:
#: Verschiebt sich das Aenderungsdatum wirklich (Wechsel der Sommerzeit auf
#: exFAT-Karten, verschiedene Uhren auf derselben SMB-Freigabe), gilt die
#: Datei als veraendert und wird neu eingeordnet. Das ist die sichere Seite:
#: Es wird nichts geloescht und nichts uebersehen, nur noch einmal gearbeitet.
ZEIT_TOLERANZ = 0.001


def _gleiche_zeit(a, b) -> bool:
    """mtime-Vergleich mit einer kleinen Toleranz (siehe ZEIT_TOLERANZ)."""
    try:
        return abs(float(a) - float(b)) <= ZEIT_TOLERANZ
    except (TypeError, ValueError):
        return False
