"""SQLite: Schema, Statuswechsel, Sammelschreiben (SPEC Abschnitt 6).

Die Datenbank liegt immer lokal, nie auf einem Netzlaufwerk. Sie ist das
Gedaechtnis des Archivs: Es wird nie eine Zeile geloescht.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote_to_bytes

from . import FotosortFehler, dateitypen, meldungen, pfade

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

SCHEMA_VERSION = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS quellen (
    wurzel                   TEXT PRIMARY KEY,
    hinzugefuegt_in_lauf     INTEGER,
    zuletzt_gescannt_in_lauf INTEGER,
    erreichbar               INTEGER NOT NULL DEFAULT 1,
    laufwerk                 TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS dateien (
    quellpfad               TEXT PRIMARY KEY,
    quellwurzel             TEXT NOT NULL,
    groesse                 INTEGER NOT NULL DEFAULT 0,
    mtime                   REAL    NOT NULL DEFAULT 0,
    dateityp                TEXT    NOT NULL DEFAULT '',
    hash                    TEXT    NOT NULL DEFAULT '',
    kamera                  TEXT    NOT NULL DEFAULT '',
    kamera_modell           TEXT    NOT NULL DEFAULT '',
    aufnahme_zeit           TEXT    NOT NULL DEFAULT '',
    datum_quelle            INTEGER,
    datum_sicher            INTEGER,
    datum_hinweis           TEXT    NOT NULL DEFAULT '',
    gruppe                  TEXT    NOT NULL DEFAULT '',
    zielpfad                TEXT    NOT NULL DEFAULT '',
    schreibpfad             TEXT    NOT NULL DEFAULT '',
    status                  TEXT    NOT NULL DEFAULT 'gefunden',
    fehlergrund             TEXT    NOT NULL DEFAULT '',
    bestaetigt_in_lauf      INTEGER,
    kopiert_in_lauf         INTEGER,
    umbenannt               INTEGER NOT NULL DEFAULT 0,
    gefunden_in_lauf        INTEGER,
    zuletzt_gesehen_in_lauf INTEGER
);

CREATE INDEX IF NOT EXISTS dateien_status  ON dateien (status);
CREATE INDEX IF NOT EXISTS dateien_wurzel  ON dateien (quellwurzel);
CREATE INDEX IF NOT EXISTS dateien_zielpfad ON dateien (zielpfad);
CREATE INDEX IF NOT EXISTS dateien_status_typ ON dateien (status, dateityp);
CREATE INDEX IF NOT EXISTS dateien_hash ON dateien (hash);
CREATE INDEX IF NOT EXISTS dateien_gruppe ON dateien (quellwurzel, gruppe, quellpfad);
CREATE TABLE IF NOT EXISTS ziel_index (
    zielpfad                TEXT PRIMARY KEY,
    groesse                 INTEGER NOT NULL DEFAULT 0,
    mtime                   REAL    NOT NULL DEFAULT 0,
    hash                    TEXT    NOT NULL DEFAULT '',
    zuletzt_gelesen_in_lauf INTEGER
);

CREATE INDEX IF NOT EXISTS ziel_index_hash ON ziel_index (hash);

CREATE TABLE IF NOT EXISTS laeufe (
    nummer          INTEGER PRIMARY KEY AUTOINCREMENT,
    befehl          TEXT NOT NULL DEFAULT '',
    start           TEXT NOT NULL DEFAULT '',
    ende            TEXT NOT NULL DEFAULT '',
    zusammenfassung TEXT NOT NULL DEFAULT ''
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


def ist_roh_kodiert(text: str) -> bool:
    """Steht der Pfad in der umkehrbaren Roh-Schreibweise (kein gueltiges UTF-8)?"""
    return str(text).startswith(_ROH_KENNZEICHEN)


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


def _schema_pruefen(verbindung: sqlite3.Connection, pfad: Path) -> None:
    """Eine Datenbank mit aelterem Schema ablehnen statt still weiterzumachen.

    Eine frische Datei hat user_version 0 und keine Tabellen. Eine Datei mit
    Tabellen, aber falscher Version, stammt aus einem frueheren Stand des
    Programms (SPEC Abschnitt 6).
    """
    version = int(verbindung.execute("PRAGMA user_version").fetchone()[0])
    if version == SCHEMA_VERSION:
        return
    hat_tabellen = verbindung.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'dateien'"
    ).fetchone()[0]
    if hat_tabellen:
        raise FotosortFehler(meldungen.datenbank_schema_veraltet(pfad, version, SCHEMA_VERSION))


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
            _schema_pruefen(verbindung, pfad)
            verbindung.executescript(SCHEMA)
            verbindung.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
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

    def lauf_beenden(self, nummer: int, zusammenfassung: dict | None = None) -> None:
        """Ende eintragen; dazu die Zahlen des Laufs (Dateien, Bytes, Sekunden)
        fuer "Dauer und Durchsatz je Phase" im Bericht (SPEC Abschnitt 10)."""
        self.stapel_schreiben()
        text = json.dumps(zusammenfassung, ensure_ascii=True) if zusammenfassung else ""
        self.verbindung.execute(
            "UPDATE laeufe SET ende = ?, zusammenfassung = ? WHERE nummer = ?",
            (_jetzt(), text, nummer),
        )

    def laeufe_liste(self) -> list[sqlite3.Row]:
        self.stapel_schreiben()
        return self.verbindung.execute("SELECT * FROM laeufe ORDER BY nummer").fetchall()

    def lauf_zeile(self, nummer: int) -> sqlite3.Row | None:
        self.stapel_schreiben()
        return self.verbindung.execute("SELECT * FROM laeufe WHERE nummer = ?", (nummer,)).fetchone()

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
        if status == "fehler":
            # Ein Fehler ist keine bestaetigte Loeschung: Die Kennung "Quelle
            # und Ziel frisch gelesen" verliert ihre Beweiskraft (Pruefbefund).
            self.verbindung.execute(
                "UPDATE dateien SET status = ?, fehlergrund = ?, bestaetigt_in_lauf = NULL WHERE quellpfad = ?",
                (status, fehlergrund, pfad_text(quellpfad)),
            )
        else:
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

    # -- Quellen (SPEC Abschnitt 4 Phase 1, Abschnitt 6) ------------------

    def quelle_aufnehmen(self, wurzel, laufwerk: str, lauf: int) -> bool:
        """Eine Quelle in die Liste aufnehmen. True, wenn sie neu war."""
        wurzel = pfad_text(wurzel)
        self._beginnen()
        vorhanden = self.verbindung.execute(
            "SELECT 1 FROM quellen WHERE wurzel = ?", (wurzel,)
        ).fetchone()
        if vorhanden:
            self.verbindung.execute(
                "UPDATE quellen SET laufwerk = ? WHERE wurzel = ?", (laufwerk, wurzel)
            )
            self._vielleicht_schreiben()
            return False
        self.verbindung.execute(
            "INSERT INTO quellen (wurzel, hinzugefuegt_in_lauf, laufwerk) VALUES (?, ?, ?)",
            (wurzel, lauf, laufwerk),
        )
        self._vielleicht_schreiben()
        return True

    def quellen_liste(self) -> list[sqlite3.Row]:
        self.stapel_schreiben()
        return self.verbindung.execute("SELECT * FROM quellen ORDER BY wurzel").fetchall()

    def quelle_gescannt(self, wurzel, lauf: int, erreichbar: bool) -> None:
        self._beginnen()
        if erreichbar:
            self.verbindung.execute(
                "UPDATE quellen SET zuletzt_gescannt_in_lauf = ?, erreichbar = 1 WHERE wurzel = ?",
                (lauf, pfad_text(wurzel)),
            )
        else:
            self.verbindung.execute(
                "UPDATE quellen SET erreichbar = 0 WHERE wurzel = ?", (pfad_text(wurzel),)
            )
        self._vielleicht_schreiben()

    def zaehler_je_quelle(self) -> dict[str, dict[str, int]]:
        """Je Quelle: Anzahl gesamt, Anzahl je Dateityp und Bytes.

        "bytes" zaehlt nur die erfassten Dateien (Foto, RAW, Video, Sidecar);
        sonstige Dateien werden nie angefasst und gehoeren nicht zur Datenmenge.
        """
        self.stapel_schreiben()
        ergebnis: dict[str, dict[str, int]] = {}
        for z in self.verbindung.execute(
            "SELECT quellwurzel, dateityp, COUNT(*) AS n, COALESCE(SUM(groesse), 0) AS b"
            " FROM dateien GROUP BY quellwurzel, dateityp"
        ):
            eintrag = ergebnis.setdefault(z["quellwurzel"], {"gesamt": 0, "bytes": 0})
            typ = z["dateityp"] or "sonstiges"
            eintrag[typ] = int(z["n"])
            eintrag["gesamt"] += int(z["n"])
            if dateitypen.ist_echter_typ(typ):
                eintrag["bytes"] += int(z["b"])
        return ergebnis

    def zaehler_je_status_und_quelle(self) -> dict[str, dict[str, int]]:
        self.stapel_schreiben()
        ergebnis: dict[str, dict[str, int]] = {}
        for z in self.verbindung.execute(
            "SELECT quellwurzel, status, COUNT(*) AS n FROM dateien GROUP BY quellwurzel, status"
        ):
            ergebnis.setdefault(z["quellwurzel"], {})[z["status"]] = int(z["n"])
        return ergebnis

    # -- Analyse (SPEC Abschnitt 4 Phase 2) -------------------------------

    ECHTE_TYPEN_SQL = "('foto', 'raw', 'video', 'sidecar')"

    def zu_analysieren(self, ab: str = "", grenze: int = 5000) -> list[sqlite3.Row]:
        """Die naechsten Zeilen mit Status gefunden und echtem Dateityp.

        Seitenweise ueber quellpfad, damit nicht alles auf einmal im
        Speicher liegt. Der Aufrufer traegt den letzten Pfad als "ab" weiter.
        """
        self.stapel_schreiben()
        return self.verbindung.execute(
            "SELECT quellpfad, quellwurzel, dateityp, groesse, mtime FROM dateien"
            f" WHERE status = 'gefunden' AND dateityp IN {self.ECHTE_TYPEN_SQL}"
            " AND quellpfad > ? ORDER BY quellpfad LIMIT ?",
            (ab, int(grenze)),
        ).fetchall()

    def anzahl_zu_analysieren(self) -> int:
        self.stapel_schreiben()
        return int(
            self.verbindung.execute(
                "SELECT COUNT(*) FROM dateien WHERE status = 'gefunden'"
                f" AND dateityp IN {self.ECHTE_TYPEN_SQL}"
            ).fetchone()[0]
        )

    def ordner_inhalt(self, ordner_text: str, trenner: str) -> list[sqlite3.Row]:
        """Alle Dateien echten Typs direkt in diesem Quellordner, jeder Status.

        Fuer die Gruppenbildung: Auch eine schon analysierte RAW-Datei bleibt
        die Hauptdatei ihres noch nicht analysierten Sidecars.
        """
        anfang = ordner_text.rstrip(trenner) + trenner
        zeilen = self.verbindung.execute(
            "SELECT quellpfad, dateityp, status, kamera, kamera_modell, aufnahme_zeit,"
            " datum_quelle, datum_sicher, datum_hinweis, zielpfad, gruppe, mtime, groesse,"
            " fehlergrund"
            " FROM dateien WHERE quellpfad > ? AND quellpfad < ?"
            f" AND dateityp IN {self.ECHTE_TYPEN_SQL} ORDER BY quellpfad",
            # Obergrenze: das hoechste UTF-8-Zeichen (F4 8F BF BF). U+FFFF
            # (EF BF BF) laege VOR Emoji und allem ab U+10000 - Dateien mit
            # solchen Namen fielen sonst still aus dem Bereich.
            (anfang, anfang + "\U0010ffff"),
        ).fetchall()
        # Nur direkte Kinder: kein weiterer Trenner hinter dem Anfang.
        return [z for z in zeilen if trenner not in z["quellpfad"][len(anfang):]]

    def analyse_setzen(
        self,
        quellpfad,
        *,
        kamera: str,
        kamera_modell: str,
        aufnahme_zeit: str,
        datum_quelle: int,
        datum_sicher: int,
        datum_hinweis: str,
        gruppe: str,
        zielpfad,
        status: str = "analysiert",
        fehlergrund: str = "",
    ) -> None:
        if status not in STATUS:
            raise ValueError(f"Unbekannter Status: {status!r}")
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET kamera = ?, kamera_modell = ?, aufnahme_zeit = ?,"
            " datum_quelle = ?, datum_sicher = ?, datum_hinweis = ?, gruppe = ?,"
            " zielpfad = ?, status = ?, fehlergrund = ? WHERE quellpfad = ?",
            (
                kamera, kamera_modell, aufnahme_zeit, datum_quelle, int(datum_sicher),
                datum_hinweis, pfad_text(gruppe), pfad_text(zielpfad) if zielpfad else "",
                status, fehlergrund, pfad_text(quellpfad),
            ),
        )
        self._vielleicht_schreiben()

    def analyse_zusammenfassung(self) -> dict:
        """Zahlen fuer die Zusammenfassung nach der Analyse (SPEC Abschnitt 4 Phase 2)."""
        self.stapel_schreiben()
        v = self.verbindung
        je_jahr_quelle: dict[str, dict[str, int]] = {}
        for z in v.execute(
            "SELECT quellwurzel, CASE WHEN aufnahme_zeit = '' OR datum_sicher = 0"
            " THEN 'ohne Datum' ELSE substr(aufnahme_zeit, 1, 4) END AS jahr, COUNT(*) AS n"
            " FROM dateien WHERE status = 'analysiert' GROUP BY quellwurzel, jahr"
        ):
            je_jahr_quelle.setdefault(z["quellwurzel"], {})[z["jahr"]] = int(z["n"])
        modelle = [
            (z["kamera_modell"], z["kamera"], int(z["n"]))
            for z in v.execute(
                "SELECT kamera_modell, kamera, COUNT(*) AS n FROM dateien"
                " WHERE status = 'analysiert' AND dateityp != 'sidecar'"
                " GROUP BY kamera_modell, kamera ORDER BY n DESC, kamera_modell"
            )
        ]
        def zaehlen(sql: str) -> int:
            return int(v.execute(sql).fetchone()[0])
        return {
            "je_jahr_quelle": je_jahr_quelle,
            "modelle": modelle,
            "analysiert": zaehlen("SELECT COUNT(*) FROM dateien WHERE status = 'analysiert'"),
            "unsicher": zaehlen(
                "SELECT COUNT(*) FROM dateien WHERE status = 'analysiert' AND datum_sicher = 0"
            ),
            "zeitzone_angenommen": zaehlen(
                "SELECT COUNT(*) FROM dateien WHERE status = 'analysiert'"
                " AND datum_hinweis = 'zeitzone_angenommen'"
            ),
            "ohne_uhrzeit": zaehlen(
                "SELECT COUNT(*) FROM dateien WHERE status = 'analysiert'"
                " AND datum_hinweis = 'dateiname_ohne_uhrzeit'"
            ),
            "sidecar_ohne_haupt": zaehlen(
                "SELECT COUNT(*) FROM dateien WHERE status = 'uebersprungen'"
                " AND fehlergrund = 'Sidecar ohne Hauptdatei'"
            ),
            "fehler": zaehlen("SELECT COUNT(*) FROM dateien WHERE status = 'fehler'"),
            "offen": self.anzahl_zu_analysieren(),
            # Namenskonflikte: derselbe Zielpfad fuer mehrere Dateien. Phase 3
            # loest sie mit dem Anhang _1; hier nur die Vorschau (SPEC §4 Phase 2).
            "namenskonflikte": zaehlen(
                "SELECT COUNT(*) FROM (SELECT zielpfad FROM dateien WHERE status = 'analysiert'"
                " AND zielpfad != '' GROUP BY zielpfad HAVING COUNT(*) > 1)"
            ),
            # Schaetzung ohne Hash (SPEC §4 Phase 2): Dateien, die Groesse UND
            # Aufnahmezeit mit einer anderen teilen. Entscheidet nichts.
            "moegliche_duplikate": zaehlen(
                "SELECT COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM dateien"
                " WHERE status = 'analysiert' AND dateityp != 'sidecar' AND aufnahme_zeit != ''"
                " GROUP BY groesse, aufnahme_zeit HAVING COUNT(*) > 1)"
            ),
        }

    def analyse_zuruecksetzen_nach_modell(self, modelle: list[str]) -> int:
        """Gefuehrter Modus: Nach neu eingetragenen Aliasen die betroffenen
        analysierten Zeilen samt Gruppenmitgliedern auf 'gefunden' stellen,
        damit die Analyse Kamera-Ordner und Zielpfad neu berechnet. Nur
        Status analysiert - schon kopierte Dateien bleiben, wo sie sind."""
        if not modelle:
            return 0
        self.stapel_schreiben()
        # Vergleich ohne Gross-/Kleinschreibung in Python (SQLite kennt LOWER
        # nur fuer ASCII - ein Modell mit Umlaut fiele sonst durch).
        klein = {m.strip().lower() for m in modelle}
        genau = [
            z["kamera_modell"] for z in self.verbindung.execute(
                "SELECT DISTINCT kamera_modell FROM dateien WHERE status = 'analysiert'")
            if str(z["kamera_modell"]).strip().lower() in klein
        ]
        if not genau:
            return 0
        self._beginnen()
        platz = ",".join("?" * len(genau))
        cursor = self.verbindung.execute(
            "UPDATE dateien SET status = 'gefunden', zielpfad = '' WHERE status = 'analysiert'"
            f" AND (kamera_modell IN ({platz}) OR (gruppe != '' AND gruppe IN"
            f" (SELECT gruppe FROM dateien WHERE status = 'analysiert' AND kamera_modell IN ({platz}))))",
            genau + genau,
        )
        self.stapel_schreiben()
        return int(cursor.rowcount)

    # -- Kopieren (SPEC Abschnitt 4 Phase 3, Abschnitt 5) -----------------

    def zu_kopieren_summe(self, quellwurzeln=None) -> tuple[int, int]:
        """(Anzahl, Bytes) der anstehenden Dateien, wahlweise nur bestimmter Quellen."""
        self.stapel_schreiben()
        sql = "SELECT COUNT(*), COALESCE(SUM(groesse), 0) FROM dateien WHERE status = 'analysiert' AND zielpfad != ''"
        werte: list = []
        if quellwurzeln is not None:
            wurzeln = [pfad_text(w) for w in quellwurzeln]
            if not wurzeln:
                return 0, 0
            sql += " AND quellwurzel IN (" + ",".join("?" * len(wurzeln)) + ")"
            werte = wurzeln
        z = self.verbindung.execute(sql, werte).fetchone()
        return int(z[0]), int(z[1])

    def zu_kopieren(self, quellwurzel, ab_gruppe: str = "", ab_pfad: str = "", grenze: int = 2000) -> list[sqlite3.Row]:
        """Naechste Zeilen einer Quelle in Kopierreihenfolge (Gruppe, Pfad).

        Gruppen bleiben zusammen, weil nach gruppe sortiert wird; der
        Aufrufer traegt (gruppe, quellpfad) der letzten Zeile als Anker weiter.
        """
        self.stapel_schreiben()
        return self.verbindung.execute(
            "SELECT * FROM dateien WHERE quellwurzel = ? AND status = 'analysiert'"
            " AND zielpfad != '' AND (gruppe, quellpfad) > (?, ?)"
            " ORDER BY gruppe, quellpfad LIMIT ?",
            (pfad_text(quellwurzel), ab_gruppe, ab_pfad, int(grenze)),
        ).fetchall()

    def gruppe_zeilen(self, quellwurzel, gruppe: str) -> list[sqlite3.Row]:
        return self.verbindung.execute(
            "SELECT * FROM dateien WHERE quellwurzel = ? AND gruppe = ? ORDER BY quellpfad",
            (pfad_text(quellwurzel), gruppe),
        ).fetchall()

    def kopieren_beanspruchen(self, quellpfad, zielpfad, schreibpfad, lauf: int, umbenannt: bool = False) -> None:
        """Zielpfad beanspruchen, BEVOR geschrieben wird (SPEC §5).

        zielpfad ist der berechnete Name (ohne Anhang), schreibpfad die Datei,
        in die dieser Lauf tatsaechlich schreibt: die .part-Datei oder im
        Rueckfall der endgueltige Name mit Anhang.
        """
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'kopieren_laeuft', zielpfad = ?, schreibpfad = ?,"
            " kopiert_in_lauf = ?, umbenannt = ?, bestaetigt_in_lauf = NULL WHERE quellpfad = ?",
            (pfad_text(zielpfad), pfad_text(schreibpfad), lauf, int(bool(umbenannt)), pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def schreibpfad_setzen(self, quellpfad, schreibpfad) -> None:
        """Vor dem Umbenennen: unter welchem endgueltigen Namen die Datei gleich liegt."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET schreibpfad = ? WHERE quellpfad = ?",
            (pfad_text(schreibpfad), pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def kopiert_setzen(self, quellpfad, zielpfad, hash_: str, lauf: int) -> None:
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'kopiert', zielpfad = ?, schreibpfad = '', hash = ?,"
            " kopiert_in_lauf = ?, fehlergrund = '', bestaetigt_in_lauf = NULL, umbenannt = 0 WHERE quellpfad = ?",
            (pfad_text(zielpfad), hash_, lauf, pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def duplikat_setzen(self, quellpfad, partner_zielpfad, hash_: str, lauf: int) -> None:
        """Inhaltsgleiche Datei liegt schon im Ziel: nicht kopiert, zielpfad = Partner."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'duplikat', zielpfad = ?, schreibpfad = '', hash = ?,"
            " kopiert_in_lauf = ?, fehlergrund = '', bestaetigt_in_lauf = NULL, umbenannt = 0 WHERE quellpfad = ?",
            (pfad_text(partner_zielpfad), hash_, lauf, pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def duplikat_partner_umschreiben(self, alt, neu, lauf: int) -> int:
        """Duplikate dieses Laufs, deren Partner unter 'alt' geplant war,
        auf den tatsaechlichen Namen 'neu' umschreiben."""
        self._beginnen()
        cursor = self.verbindung.execute(
            "UPDATE dateien SET zielpfad = ? WHERE status = 'duplikat' AND zielpfad = ? AND kopiert_in_lauf = ?",
            (pfad_text(neu), pfad_text(alt), lauf),
        )
        self._vielleicht_schreiben()
        return int(cursor.rowcount)

    def duplikate_mit_partner(self, partner, lauf: int) -> list[sqlite3.Row]:
        self.stapel_schreiben()
        return self.verbindung.execute(
            "SELECT * FROM dateien WHERE status = 'duplikat' AND zielpfad = ? AND kopiert_in_lauf = ?",
            (pfad_text(partner), lauf),
        ).fetchall()

    def zurueck_auf_analysiert(self, quellpfad, zielpfad) -> None:
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'analysiert', zielpfad = ?, schreibpfad = '',"
            " kopiert_in_lauf = NULL, bestaetigt_in_lauf = NULL, umbenannt = 0 WHERE quellpfad = ?",
            (pfad_text(zielpfad), pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def zurueck_auf_gefunden(self, quellpfad, groesse: int, mtime: float) -> None:
        """Quelle hat sich veraendert: neu einordnen (SPEC §6)."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'gefunden', groesse = ?, mtime = ?, hash = '',"
            " zielpfad = '', schreibpfad = '', bestaetigt_in_lauf = NULL, kopiert_in_lauf = NULL,"
            " fehlergrund = '' WHERE quellpfad = ?",
            (int(groesse), float(mtime), pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def liegengebliebene(self, lauf: int) -> list[sqlite3.Row]:
        """Zeilen mit kopieren_laeuft aus einem anderen (abgebrochenen) Lauf."""
        self.stapel_schreiben()
        return self.verbindung.execute(
            "SELECT * FROM dateien WHERE status = 'kopieren_laeuft'"
            " AND (kopiert_in_lauf IS NULL OR kopiert_in_lauf != ?)",
            (lauf,),
        ).fetchall()

    # -- Ziel-Index (SPEC Abschnitt 6) ------------------------------------

    def ziel_index_setzen(self, zielpfad, groesse: int, mtime: float, hash_: str, lauf: int) -> None:
        self._beginnen()
        self.verbindung.execute(
            "INSERT INTO ziel_index (zielpfad, groesse, mtime, hash, zuletzt_gelesen_in_lauf)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(zielpfad) DO UPDATE SET groesse = excluded.groesse,"
            " mtime = excluded.mtime, hash = excluded.hash,"
            " zuletzt_gelesen_in_lauf = excluded.zuletzt_gelesen_in_lauf",
            (pfad_text(zielpfad), int(groesse), float(mtime), hash_, lauf),
        )
        self._vielleicht_schreiben()

    def ziel_index_nach_hash(self, hash_: str) -> list[sqlite3.Row]:
        # Kein Sammelschreiben noetig: Dieselbe Verbindung sieht ihre eigenen,
        # noch nicht festgeschriebenen Zeilen.
        return self.verbindung.execute(
            "SELECT * FROM ziel_index WHERE hash = ? ORDER BY zielpfad", (hash_,)
        ).fetchall()

    def ziel_index_nach_pfad(self, zielpfad) -> sqlite3.Row | None:
        return self.verbindung.execute(
            "SELECT * FROM ziel_index WHERE zielpfad = ?", (pfad_text(zielpfad),)
        ).fetchone()

    def ziel_index_entfernen(self, zielpfad) -> None:
        self._beginnen()
        self.verbindung.execute("DELETE FROM ziel_index WHERE zielpfad = ?", (pfad_text(zielpfad),))
        self._vielleicht_schreiben()

    def kopier_zusammenfassung(self) -> dict:
        self.stapel_schreiben()
        v = self.verbindung
        status = {z[0]: int(z[1]) for z in v.execute("SELECT status, COUNT(*) FROM dateien GROUP BY status")}
        kopiert_bytes = int(v.execute(
            "SELECT COALESCE(SUM(groesse), 0) FROM dateien WHERE status IN ('kopiert', 'geprueft')"
        ).fetchone()[0])
        je_quelle: dict[str, dict[str, int]] = {}
        for z in v.execute(
            "SELECT quellwurzel, status, COUNT(*) AS n FROM dateien GROUP BY quellwurzel, status"
        ):
            je_quelle.setdefault(z["quellwurzel"], {})[z["status"]] = int(z["n"])
        return {"status": status, "kopiert_bytes": kopiert_bytes, "je_quelle": je_quelle}

    # -- Pruefen (SPEC Abschnitt 4 Phase 4) --------------------------------

    # verschoben: nur solange der Hash noch fehlt (er wird hier nachgetragen).
    ZU_PRUEFEN_SQL = (
        "zielpfad != '' AND (status IN ('kopiert', 'duplikat')"
        " OR (status = 'verschoben' AND hash = ''))"
    )

    def zu_pruefen_summe(self) -> tuple[int, int]:
        """(Anzahl, zu lesende Bytes). Duplikate zaehlen keine Bytes: Ihre
        Partnerdatei wird ueber die Zeile gelesen, der sie gehoert."""
        self.stapel_schreiben()
        z = self.verbindung.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN status = 'duplikat' THEN 0 ELSE groesse END), 0)"
            f" FROM dateien WHERE {self.ZU_PRUEFEN_SQL}"
        ).fetchone()
        return int(z[0]), int(z[1])

    def zu_pruefen(self, ab_ziel: str = "", ab_pfad: str = "", grenze: int = 2000) -> list[sqlite3.Row]:
        """Naechste zu pruefende Zeilen, nach Zielpfad sortiert (das Ziel wird
        so moeglichst in Ordnerreihenfolge gelesen)."""
        self.stapel_schreiben()
        return self.verbindung.execute(
            f"SELECT * FROM dateien WHERE {self.ZU_PRUEFEN_SQL}"
            " AND (zielpfad, quellpfad) > (?, ?) ORDER BY zielpfad, quellpfad LIMIT ?",
            (ab_ziel, ab_pfad, int(grenze)),
        ).fetchall()

    def geprueft_setzen(self, quellpfad) -> None:
        """Zieldatei frisch gelesen, Hash stimmt mit dem Quell-Hash ueberein."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'geprueft', fehlergrund = '' WHERE quellpfad = ?",
            (pfad_text(quellpfad),),
        )
        self._vielleicht_schreiben()

    def duplikat_bestaetigt_setzen(self, quellpfad) -> None:
        """Partnerdatei im Ziel frisch gelesen, Hash stimmt (SPEC Abschnitt 5)."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'duplikat_bestaetigt', fehlergrund = '' WHERE quellpfad = ?",
            (pfad_text(quellpfad),),
        )
        self._vielleicht_schreiben()

    def verschoben_hash_setzen(self, quellpfad, hash_: str) -> None:
        """Umbenannte Datei: Hash aus der Zieldatei nachgetragen (Phase 4)."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET hash = ?, fehlergrund = '' WHERE quellpfad = ?",
            (hash_, pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def zeilen_mit_fehlergrund(self, praefix: str) -> list[sqlite3.Row]:
        """Zeilen im Status fehler, deren Grund mit praefix beginnt."""
        self.stapel_schreiben()
        return self.verbindung.execute(
            "SELECT * FROM dateien WHERE status = 'fehler' AND fehlergrund LIKE ? ESCAPE '\\'"
            " ORDER BY quellpfad",
            (praefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
        ).fetchall()

    # -- Aufraeumen und Verschieben (SPEC Abschnitt 4 Phase 5, Abschnitt 5) ---

    # Zeilen unter einem Ordner _geloescht_ sind nie Kandidaten: Der
    # Papierkorb wird vom Aufraeumen nie angefasst (SPEC §4 Phase 5).
    ZU_LOESCHEN_SQL = (
        "status IN ('geprueft', 'duplikat_bestaetigt') AND zielpfad != ''"
        " AND instr(quellpfad, '/_geloescht_') = 0 AND instr(quellpfad, '\\_geloescht_') = 0"
    )

    def zu_loeschen_summe(self, quellwurzeln=None) -> dict[str, tuple[int, int]]:
        """Je Quellwurzel (Anzahl, Bytes) der loeschberechtigten Zeilen."""
        self.stapel_schreiben()
        sql = f"SELECT quellwurzel, COUNT(*) AS n, COALESCE(SUM(groesse), 0) AS b FROM dateien WHERE {self.ZU_LOESCHEN_SQL}"
        werte: list = []
        if quellwurzeln is not None:
            wurzeln = [pfad_text(w) for w in quellwurzeln]
            if not wurzeln:
                return {}
            sql += " AND quellwurzel IN (" + ",".join("?" * len(wurzeln)) + ")"
            werte = wurzeln
        return {z["quellwurzel"]: (int(z["n"]), int(z["b"])) for z in self.verbindung.execute(sql + " GROUP BY quellwurzel", werte)}

    def zu_loeschen(self, quellwurzel, ab: str = "", grenze: int = 2000) -> list[sqlite3.Row]:
        self.stapel_schreiben()
        return self.verbindung.execute(
            f"SELECT * FROM dateien WHERE quellwurzel = ? AND {self.ZU_LOESCHEN_SQL} AND quellpfad > ?"
            " ORDER BY quellpfad LIMIT ?",
            (pfad_text(quellwurzel), ab, int(grenze)),
        ).fetchall()

    def bestaetigt_setzen(self, quellpfad, lauf: int, papierkorb_pfad=None) -> None:
        """Quelle und Ziel wurden in diesem Lauf frisch gelesen und stimmen.
        Wird VOR dem Entfernen festgeschrieben (SPEC Abschnitt 5, 6)."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET bestaetigt_in_lauf = ?, schreibpfad = ? WHERE quellpfad = ?",
            (lauf, pfad_text(papierkorb_pfad) if papierkorb_pfad else "", pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def quelle_geloescht_setzen(self, quellpfad, lauf: int, neuer_pfad=None) -> None:
        """Nach dem Entfernen. schreibpfad: wo die Datei im Papierkorb liegt, sonst leer."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'quelle_geloescht', schreibpfad = ?, fehlergrund = ''"
            " WHERE quellpfad = ?",
            (pfad_text(neuer_pfad) if neuer_pfad else "", pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def zurueck_auf_analysiert_ohne_hash(self, quellpfad) -> None:
        """Quelle seit dem Kopieren geaendert: neu kopieren (SPEC Abschnitt 5).
        Hash und Lauf-Kennung werden geleert, der Zielpfad bleibt."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'analysiert', hash = '', bestaetigt_in_lauf = NULL,"
            " schreibpfad = '', kopiert_in_lauf = NULL, fehlergrund = '' WHERE quellpfad = ?",
            (pfad_text(quellpfad),),
        )
        self._vielleicht_schreiben()

    def verschoben_setzen(self, quellpfad, zielpfad, lauf: int) -> None:
        """Durch Umbenennen ins Ziel gebracht; Hash traegt die Pruef-Phase nach."""
        self._beginnen()
        self.verbindung.execute(
            "UPDATE dateien SET status = 'verschoben', zielpfad = ?, schreibpfad = '', hash = '',"
            " kopiert_in_lauf = ?, fehlergrund = '' WHERE quellpfad = ?",
            (pfad_text(zielpfad), lauf, pfad_text(quellpfad)),
        )
        self._vielleicht_schreiben()

    def echter_typ_bekannt(self, quellpfad) -> bool:
        """Steht die Datei mit echtem Dateityp in der Datenbank? (Reste-Regel, SPEC §5)"""
        self.stapel_schreiben()
        z = self.verbindung.execute(
            "SELECT 1 FROM dateien WHERE quellpfad = ? AND dateityp IN ('foto', 'raw', 'video', 'sidecar')",
            (pfad_text(quellpfad),),
        ).fetchone()
        return z is not None

    # -- Bericht (SPEC Abschnitt 10) ----------------------------------------

    def bericht_zahlen(self) -> dict[str, dict[str, int]]:
        """Zahlen je Quelle und gesamt: gefunden (echter Dateityp), kopiert,
        verschoben, geprueft, duplikate, ohne_datum, fehler, geloescht,
        uebersprungen, bytes."""
        self.stapel_schreiben()
        leer = lambda: {k: 0 for k in (
            "gefunden", "kopiert", "verschoben", "geprueft", "duplikate", "ohne_datum",
            "fehler", "geloescht", "uebersprungen", "sonstiges", "bytes",
        )}
        ergebnis: dict[str, dict[str, int]] = {"gesamt": leer()}
        for z in self.verbindung.execute(
            "SELECT quellwurzel, status, datum_sicher, dateityp, (zielpfad != '') AS eingeordnet,"
            " COUNT(*) AS n, COALESCE(SUM(groesse), 0) AS b"
            " FROM dateien GROUP BY quellwurzel, status, datum_sicher, dateityp, eingeordnet"
        ):
            for schluessel in (z["quellwurzel"], "gesamt"):
                e = ergebnis.setdefault(schluessel, leer())
                n = int(z["n"])
                if z["dateityp"] not in ("foto", "raw", "video", "sidecar"):
                    e["sonstiges"] += n   # uebersprungen nach Typ (SPEC §3)
                    continue
                e["gefunden"] += n
                e["bytes"] += int(z["b"])
                st = z["status"]
                if st in ("kopiert", "geprueft", "quelle_geloescht"):
                    e["kopiert"] += n
                if st == "verschoben":
                    e["verschoben"] += n
                if st in ("geprueft", "quelle_geloescht"):
                    e["geprueft"] += n
                if st in ("duplikat", "duplikat_bestaetigt"):
                    e["duplikate"] += n
                if st == "fehler":
                    e["fehler"] += n
                if st == "quelle_geloescht":
                    e["geloescht"] += n
                if st == "uebersprungen":
                    e["uebersprungen"] += n
                # "ohne Datum": analysiert (Zielpfad berechnet), Datum nur aus
                # dem Aenderungsdatum - unabhaengig davon, was spaeter mit der
                # Datei geschah (auch eine fehlgeschlagene Pruefung).
                if z["datum_sicher"] == 0 and z["eingeordnet"]:
                    e["ohne_datum"] += n
        return ergebnis

    def dateien_seite(self, bedingung: str, werte: tuple, seite: int, groesse: int = 100) -> tuple[list[sqlite3.Row], int]:
        """Eine Seite (1-basiert) einer Dateiliste plus Gesamtzahl - die
        Oberflaeche zeigt nie alle Zeilen auf einmal (SPEC Abschnitt 8)."""
        self.stapel_schreiben()
        gesamt = int(self.verbindung.execute(f"SELECT COUNT(*) FROM dateien WHERE {bedingung}", werte).fetchone()[0])
        seiten = max(1, (gesamt + int(groesse) - 1) // int(groesse))
        seite = max(1, min(int(seite), seiten))   # hinter der letzten Seite: die letzte
        zeilen = self.verbindung.execute(
            f"SELECT * FROM dateien WHERE {bedingung} ORDER BY quellpfad LIMIT ? OFFSET ?",
            (*werte, int(groesse), (seite - 1) * int(groesse)),
        ).fetchall()
        return zeilen, gesamt

    def dateien_liste(self, bedingung: str = "1", werte: tuple = ()) -> sqlite3.Cursor:
        """Zeilen als Cursor (nicht alles auf einmal in den Speicher)."""
        self.stapel_schreiben()
        return self.verbindung.execute(
            f"SELECT * FROM dateien WHERE {bedingung} ORDER BY quellwurzel, quellpfad", werte
        )

    def ereignisse_liste(self, art: str | None = None, lauf: int | None = None) -> list[sqlite3.Row]:
        self.stapel_schreiben()
        sql = "SELECT rowid, * FROM lauf_ereignisse WHERE 1"
        werte: list = []
        if art is not None:
            sql += " AND art = ?"
            werte.append(art)
        if lauf is not None:
            sql += " AND lauf_nummer = ?"
            werte.append(lauf)
        return self.verbindung.execute(sql + " ORDER BY lauf_nummer, rowid", werte).fetchall()

    def ereignisse_summen(self) -> dict[str, int]:
        """Anzahl je Ereignisart ueber alle Laeufe."""
        self.stapel_schreiben()
        return {
            z["art"]: int(z["n"])
            for z in self.verbindung.execute(
                "SELECT art, COALESCE(SUM(anzahl), 0) AS n FROM lauf_ereignisse GROUP BY art"
            )
        }

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
        """Bytes der erfassten Dateien (Foto, RAW, Video, Sidecar)."""
        zeile = self.verbindung.execute(
            f"SELECT COALESCE(SUM(groesse), 0) AS s FROM dateien WHERE dateityp IN {self.ECHTE_TYPEN_SQL}"
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
