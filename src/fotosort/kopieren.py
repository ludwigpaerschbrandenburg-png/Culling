"""Phase 3: Uebertragen im Kopier-Modus (SPEC Abschnitt 4 Phase 3, 5, 7).

Ablauf je Datei:
  1. Zielpfad in der Datenbank beanspruchen (Status kopieren_laeuft).
  2. In <Zielname>.part kopieren, dabei BLAKE3 der Quelle mitrechnen.
  3. Entscheiden: inhaltsgleich schon im Ziel -> duplikat, .part entfernen;
     Zielname belegt mit anderem Inhalt -> Anhang _1, _2 ... fuer die ganze
     Gruppe; sonst der berechnete Name.
  4. Nicht ueberschreibend an den endgueltigen Namen bringen, Status kopiert,
     Ziel-Index nachtragen.

Kann das Ziel-Dateisystem kein nicht ueberschreibendes Umbenennen (exFAT,
FAT32), entfaellt die .part-Datei: Die Zieldatei wird direkt exklusiv unter
ihrem endgueltigen Namen angelegt (SPEC Abschnitt 5, "Rueckfall").

Straenge: Die Kopier-Worker fassen nur das Dateisystem an. Alle
Entscheidungen, alles Umbenennen und jeder Datenbankzugriff geschehen im
Hauptstrang. Quellen auf verschiedenen Laufwerken werden abwechselnd
bedient, innerhalb eines Laufwerks in Ordnerreihenfolge (SPEC Abschnitt 7).

Es wird in dieser Phase NICHTS in der Quelle geloescht oder veraendert.
Geloescht wird im Ziel ausschliesslich, was dieser Lauf selbst angelegt hat
(eine eigene .part-Datei oder eine im Rueckfall selbst exklusiv angelegte
Datei), sowie liegengebliebene .part-Dateien nach SPEC Abschnitt 5.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from . import FotosortFehler, db, fortschritt, hashes, loeschen, meldungen, pfade
from .scan import ART_QUELLE_NICHT_ERREICHBAR, ART_QUELLE_VERAENDERT, TEXT_QUELLE_VERAENDERT

# Ereignisarten dieses Moduls (SPEC Abschnitt 6).
ART_DUPLIKAT = "duplikat"
ART_NAMENSKONFLIKT = "namenskonflikt"
ART_PART_AUFGERAEUMT = "part_aufgeraeumt"
ART_ANGEFANGENE_ENTFERNT = "angefangene_zieldatei_entfernt"
ART_NACHTRAEGLICH_BESTAETIGT = "kopie_nachtraeglich_bestaetigt"
ART_EXFAT_RUECKFALL = "rueckfall_kopieren"
ART_NEU_NACH_PRUEFUNG = "neu_nach_pruefung"
ART_ANHANG_ABWEICHEND = "anhang_abweichend"

# Deutsche Texte, die in die Datenbank gelangen, stehen in meldungen.py.
GRUND_QUELLE_FEHLT = meldungen.GRUND_QUELLE_FEHLT
GRUND_QUELLE_WAEHREND_KOPIE = meldungen.GRUND_QUELLE_WAEHREND_KOPIE
GRUND_KOPIE = meldungen.GRUND_KOPIE
GRUND_PART_BELEGT = meldungen.GRUND_PART_BELEGT

PART = ".part"
PROFILE: dict[str, int] = {"hdd": 2, "netzwerk": 4, "ssd": 8}
SEITE = 2000


# ----------------------------------------------------------- Ergebnis ----


@dataclass
class Ergebnis:
    geplant: int = 0                 # zu Beginn (nach dem Aufraeumen) anstehend
    geplant_bytes: int = 0
    bearbeitet: int = 0
    kopiert: int = 0
    duplikate: int = 0               # inhaltsgleich schon im Ziel, nicht kopiert
    namenskonflikte: int = 0         # mit Anhang _1, _2 ... abgelegt
    fehler: int = 0
    quelle_veraendert: int = 0       # zurueck auf gefunden
    quellen_nicht_erreichbar: list[str] = field(default_factory=list)
    part_aufgeraeumt: int = 0
    angefangene_entfernt: int = 0
    nachtraeglich_bestaetigt: int = 0
    bytes_kopiert: int = 0
    sekunden: float = 0.0
    abgebrochen: bool = False
    kopier_worker: int = 0
    hash_worker: int = 0
    profil: str = ""
    exfat_rueckfall: bool = False
    neu_nach_pruefung: int = 0       # nach fehlgeschlagener Pruefung neu zu kopieren
    # Verschieben-Modus (SPEC Abschnitt 4 Phase 3, Phase 5):
    verschieben: bool = False
    verschoben: int = 0              # durch Umbenennen ins Ziel gebracht
    quelle_geloescht: int = 0        # kopiert, beide Seiten frisch gelesen, Quelle geloescht
    quelle_seit_kopieren: int = 0    # Quelle hat sich nach dem Kopieren geaendert: nicht geloescht
    loeschung_verweigert: int = 0
    anhang_abweichend: int = 0        # Gruppenmitglied mit anderem Anhang (Fremdprozess dazwischen)


@dataclass
class Plan:
    """Ergebnis von --dry-run: nur Zahlen, nichts angefasst."""
    dateien: int = 0
    bytes: int = 0
    je_quelle: dict[str, tuple[int, int]] = field(default_factory=dict)
    zielname_belegt: int = 0
    quellen_nicht_erreichbar: list[str] = field(default_factory=list)
    liegengeblieben: int = 0


# ----------------------------------------------------- Worker-Zahlen ----


def worker_zahlen(konf, profil=None, kopier=None, hash_=None) -> tuple[int, int, str]:
    """(Kopier-Worker, Hash-Worker, Profil) aus Befehlszeile und config.toml.

    Befehlszeile vor Konfiguration; 0 in der Konfiguration heisst
    automatisch (SPEC Abschnitt 9).
    """
    profil = (profil or str(konf.wert("leistung.profil") or "hdd")).strip().lower()
    if profil not in PROFILE:
        raise FotosortFehler(meldungen.profil_ungueltig(profil, sorted(PROFILE)))
    k = int(kopier or 0) or int(konf.wert("leistung.kopier_worker") or 0) or PROFILE[profil]
    h = int(hash_ or 0) or int(konf.wert("leistung.hash_worker") or 0) or max(1, os.cpu_count() or 1)
    return max(1, k), max(1, h), profil


# --------------------------------------------------------- Bausteine ----


def part_pfad(zielpfad: Path) -> Path:
    """Vollstaendiger Zielname plus .part (SPEC Abschnitt 5)."""
    return zielpfad.with_name(zielpfad.name + PART)


def mit_anhang(zielpfad: Path, k: int, stamm: str = "") -> Path:
    """Anhang _k einfuegen; 0 -> unveraendert.

    Der Anhang kommt hinter den Stammnamen der HAUPTDATEI der Gruppe, damit
    Sidecars weiter zu ihr passen (SPEC Abschnitt 3, drei Formen):
      DSC01234.ARW      -> DSC01234_1.ARW
      DSC01234.xmp      -> DSC01234_1.xmp
      DSC01234.ARW.xmp  -> DSC01234_1.ARW.xmp
      C0001M01.XML      -> C0001_1M01.XML   (Hauptdatei C0001.MP4)
    """
    if k <= 0:
        return zielpfad
    name = zielpfad.name
    if stamm and name.startswith(stamm) and len(name) > len(stamm):
        return zielpfad.with_name(f"{stamm}_{k}{name[len(stamm):]}")
    return zielpfad.with_name(f"{zielpfad.stem}_{k}{zielpfad.suffix}")


def _stamm(zeile) -> str:
    """Stammname der Hauptdatei der Gruppe (gruppe = Quellpfad der Hauptdatei)."""
    gruppe = zeile["gruppe"] or zeile["quellpfad"]
    return Path(db.text_pfad(gruppe)).stem


def _L(p: Path) -> Path:
    return pfade.lang(p)


def _stat(p: Path):
    try:
        return os.stat(_L(p))
    except OSError:
        return None


def _entfernen_eigene(p: Path) -> None:
    """Nur fuer Dateien, die dieser Lauf selbst angelegt hat."""
    try:
        os.unlink(_L(p))
    except FileNotFoundError:
        pass


@dataclass
class _Quelle:
    wurzel: str            # Text wie in der Datenbank
    pfad: Path
    laufwerk: str
    ab_gruppe: str = ""
    ab_pfad: str = ""
    seite: deque = field(default_factory=deque)
    erschoepft: bool = False
    rest: list = field(default_factory=list)   # angefangene Gruppe am Seitenende

    def naechste_gruppe(self, dbank: db.Datenbank) -> list | None:
        while True:
            if self.seite:
                gruppe = [self.seite.popleft()]
                while self.seite and self.seite[0]["gruppe"] == gruppe[0]["gruppe"]:
                    gruppe.append(self.seite.popleft())
                if self.seite or self.erschoepft:
                    return gruppe
                # Die Gruppe koennte auf der naechsten Seite weitergehen.
                self.rest = gruppe
            if self.erschoepft:
                if self.rest:
                    gruppe, self.rest = self.rest, []
                    return gruppe
                return None
            zeilen = dbank.zu_kopieren(self.wurzel, self.ab_gruppe, self.ab_pfad, SEITE)
            if len(zeilen) < SEITE:
                self.erschoepft = True
            if zeilen:
                self.ab_gruppe, self.ab_pfad = zeilen[-1]["gruppe"], zeilen[-1]["quellpfad"]
            if self.rest:
                # Fortsetzung der angefangenen Gruppe vorn anfuegen.
                zeilen = self.rest + list(zeilen)
                self.rest = []
            self.seite.extend(zeilen)
            if not self.seite and self.erschoepft:
                return None


@dataclass
class _Auftrag:
    zeile: object                    # sqlite3.Row der Quelldatei
    quelle: Path
    ziel: Path                       # berechneter Zielpfad (ohne Anhang)
    schreibziel: Path                # .part oder (Rueckfall) der endgueltige Name
    stamm: str = ""                  # Stammname der Hauptdatei (fuer den Anhang)
    anhang: int = 0                  # nur im Rueckfall vorab bestimmt
    fd: int | None = None            # Rueckfall: vom Hauptstrang exklusiv angelegt
    zukunft: Future | None = None
    ziel_hash: Future | None = None  # Hash einer schon vorhandenen Datei am Zielnamen
    ziel_da: bool | None = None      # beim Einreichen: lag schon eine Datei am Zielnamen?
    ergebnis: object = None


@dataclass
class _Kopie:
    """Was ein Kopier-Worker zurueckgibt."""
    art: str                         # ok | fehlt | veraendert | belegt | fehler | abgebrochen
    hash: str = ""
    bytes: int = 0
    mtime_ns: int = 0
    grund: str = ""


# ------------------------------------------------------------- Worker ----


def _kopieren_worker(quelle: Path, schreibziel: Path, groesse: int, mtime: float,
                     stop: threading.Event, fd: int | None = None) -> _Kopie:
    """Laeuft im Kopier-Worker. Fasst nur das Dateisystem an.

    fd: im Rueckfall ohne .part der vom Hauptstrang schon exklusiv angelegte
    Dateigriff. Gibt der Worker vorher auf, ist die leere Datei seine eigene
    und wird entfernt.
    """
    def aufgeben(k: _Kopie) -> _Kopie:
        if fd is not None:
            os.close(fd)
            _entfernen_eigene(schreibziel)
        return k

    try:
        st = os.stat(_L(quelle))
    except FileNotFoundError:
        return aufgeben(_Kopie("fehlt"))
    except OSError as fehler:
        return aufgeben(_Kopie("fehler", grund=f"{GRUND_KOPIE}: {fehler.strerror or fehler}"))
    if st.st_size != int(groesse) or not db._gleiche_zeit(st.st_mtime, mtime):
        return aufgeben(_Kopie("veraendert", bytes=st.st_size, mtime_ns=st.st_mtime_ns))
    try:
        if fd is None:
            _L(schreibziel.parent).mkdir(parents=True, exist_ok=True)
        h, n = hashes.kopieren_mit_hash(_L(quelle), _L(schreibziel), stop, fd)
    except FileExistsError:
        return _Kopie("belegt")
    except hashes.Abgebrochen:
        return _Kopie("abgebrochen")
    except OSError as fehler:
        return _Kopie("fehler", grund=f"{GRUND_KOPIE}: {fehler.strerror or fehler}")
    st2 = _stat(quelle)
    if n != st.st_size or st2 is None or st2.st_size != st.st_size or st2.st_mtime_ns != st.st_mtime_ns:
        _entfernen_eigene(schreibziel)
        return _Kopie("veraendert", bytes=st2.st_size if st2 else 0,
                      mtime_ns=st2.st_mtime_ns if st2 else 0, grund=GRUND_QUELLE_WAEHREND_KOPIE)
    try:
        os.utime(_L(schreibziel), ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass  # Aenderungsdatum ist Komfort, kein Verlust
    # Fuer den Ziel-Index zaehlt die Zeit, die die geschriebene Datei WIRKLICH
    # traegt (utime kann scheitern, FAT/SMB runden) - ein stat im Worker.
    try:
        mtime_ns = os.stat(_L(schreibziel)).st_mtime_ns
    except OSError:
        mtime_ns = st.st_mtime_ns
    return _Kopie("ok", hash=h, bytes=n, mtime_ns=mtime_ns)


# ------------------------------------------------------------- Ablauf ----


class _Lauf:
    """Zustand eines Kopierlaufs; nur der Hauptstrang fasst ihn an."""

    def __init__(self, ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole,
                 kopier_worker: int, hash_worker: int, direkt: bool, verschieben: bool = False) -> None:
        self.ziel = ziel
        self.konf = konf
        self.dbank = dbank
        self.lauf = lauf
        self.konsole = konsole
        self.direkt = direkt                   # Rueckfall ohne .part
        self.verschieben = verschieben
        self.byte_vergleich = bool(konf.wert("sicherheit.byte_vergleich_vor_loeschen"))
        self.umbenennen_je_wurzel: dict[str, bool] = {}
        self.nachpruefung: deque = deque()     # (Auftrag, Endname, Future) im Verschieben-Modus
        self.stop = threading.Event()
        self.kopierer = ThreadPoolExecutor(max_workers=kopier_worker, thread_name_prefix="kopie")
        self.hasher = ThreadPoolExecutor(max_workers=hash_worker, thread_name_prefix="hash")
        self.max_offen = max(4, kopier_worker * 4)
        self.in_arbeit: set[str] = set()       # Zielnamen (Text), die gerade entstehen
        self.offen: list[list[_Auftrag]] = []  # eingereichte Gruppen
        self.bereit: list[list[_Auftrag]] = [] # beansprucht, Anspruch noch nicht festgeschrieben
        # Hash -> (Endname, Bytes) der Dateien, deren Umbenennen in dieser
        # Runde noch aussteht: Ein inhaltsgleiches Duplikat aus derselben
        # Runde findet seinen Partner so auch vor dem Eintrag im Ziel-Index.
        self.hash_anstehend: dict[str, tuple[Path, int]] = {}
        self.wartend: deque[tuple[_Quelle, list]] = deque()
        self.ergebnis = Ergebnis()
        self.anzeige: fortschritt.Fortschritt | None = None

    # -- Namen -----------------------------------------------------------

    def belegt(self, p: Path, eigene_dateien: frozenset[str] = frozenset(),
               eigene_namen: frozenset[str] = frozenset(),
               bekannt_frei: frozenset[str] = frozenset()) -> bool:
        """Name im Ziel vergeben: gerade in Arbeit oder schon auf der Platte.

        eigene_dateien: Dateien, die die fragende Gruppe selbst gerade
        schreibt (.part) - zaehlen gar nicht. eigene_namen: die berechneten
        Zielnamen der Gruppe - sie stehen zwar in "in Arbeit", aber ob der
        Name auf der Platte belegt ist, muss trotzdem geprueft werden.
        bekannt_frei: Namen, die beim Einreichen nachweislich frei waren -
        kein zweiter stat; legt ein Fremdprozess sie dazwischen an, faengt
        das nicht ueberschreibende Umbenennen das ab (FileExistsError).
        """
        t = db.pfad_text(p)
        if t in eigene_dateien:
            return False
        if t in self.in_arbeit and t not in eigene_namen:
            return True
        if t in bekannt_frei:
            return False
        return _stat(p) is not None

    def hash_von_vorhandener(self, p: Path) -> Future:
        """Hash einer Datei im Ziel: aus dem Ziel-Index, wenn Groesse und
        Zeit noch stimmen, sonst frisch gelesen (Hash-Worker)."""
        st = _stat(p)
        eintrag = self.dbank.ziel_index_nach_pfad(p)
        if st is not None and eintrag is not None and int(eintrag["groesse"]) == st.st_size \
                and db._gleiche_zeit(eintrag["mtime"], st.st_mtime) and eintrag["hash"]:
            f: Future = Future()
            f.set_result(eintrag["hash"])
            return f
        return self.hasher.submit(hashes.blake3_datei, _L(p))

    def index_nachtragen(self, p: Path, h: str) -> None:
        if not h:
            return
        st = _stat(p)
        if st is not None:
            self.dbank.ziel_index_setzen(p, st.st_size, st.st_mtime, h, self.lauf)

    # -- Aufraeumen (SPEC Abschnitt 5) ------------------------------------

    def liegengebliebene_aufraeumen(self) -> None:
        """Reste eines abgebrochenen Laufs (SPEC Abschnitt 5).

        Je Zeile mit kopieren_laeuft aus einem anderen Lauf: Die .part-Datei
        zum beanspruchten Zielnamen wird entfernt (die Zeile beansprucht sie,
        sie wird neu geschrieben). Unter dem "schreibpfad" - dem Namen, unter
        dem der abgebrochene Lauf tatsaechlich geschrieben hat - wird
        nachgesehen: vollstaendig und inhaltsgleich mit der Quelle -> die Kopie
        war fertig, Status kopiert; unvollstaendig -> nur im Rueckfall ohne
        .part entfernen, denn nur dort hat das Programm die Datei selbst
        exklusiv angelegt, bevor es den Anspruch festgeschrieben hat.
        """
        e = self.ergebnis
        for z in self.dbank.liegengebliebene(self.lauf):
            quelle = Path(db.text_pfad(z["quellpfad"]))
            ziel = Path(db.text_pfad(z["zielpfad"]))
            part = part_pfad(ziel)
            schreib = Path(db.text_pfad(z["schreibpfad"])) if z["schreibpfad"] else None
            if _stat(part) is not None:
                _entfernen_eigene(part)
                e.part_aufgeraeumt += 1
                self.dbank.ereignis(self.lauf, ART_PART_AUFGERAEUMT, part, 1, meldungen.EREIGNIS_PART_AUFGERAEUMT)
            st = _stat(schreib) if schreib is not None and db.pfad_text(schreib) != db.pfad_text(part) else None
            if st is not None and int(z["umbenannt"] or 0) and _stat(quelle) is None:
                # Verschieben durch Umbenennen: Der Name war vorher beansprucht
                # und nachweislich frei (nicht ueberschreibendes Umbenennen);
                # die Quelle ist weg, die Datei liegt unter dem Endnamen. Das
                # Umbenennen war fertig, nur der Status nicht festgeschrieben.
                if st.st_size == int(z["groesse"]):
                    self.dbank.verschoben_setzen(z["quellpfad"], schreib, self.lauf)
                    e.nachtraeglich_bestaetigt += 1
                    self.dbank.ereignis(self.lauf, ART_NACHTRAEGLICH_BESTAETIGT, quelle, 1,
                                        meldungen.EREIGNIS_VERSCHOBEN_NACHGETRAGEN)
                else:
                    self.dbank.verschoben_setzen(z["quellpfad"], schreib, self.lauf)
                    self.dbank.status_setzen(z["quellpfad"], "fehler", meldungen.GRUND_VERSCHIEBEN_GROESSE)
                    e.fehler += 1
                continue
            if st is not None:
                if st.st_size == int(z["groesse"]) and _stat(quelle) is not None:
                    h_ziel = self.hasher.submit(hashes.blake3_datei, _L(schreib))
                    h_quelle = self.hasher.submit(hashes.blake3_datei, _L(quelle))
                    try:
                        hz, hq = h_ziel.result(), h_quelle.result()
                    except OSError:
                        hz, hq = "", ""
                    if hz and hz == hq:
                        self.dbank.kopiert_setzen(z["quellpfad"], schreib, hq, self.lauf)
                        self.index_nachtragen(schreib, hz)
                        e.nachtraeglich_bestaetigt += 1
                        self.dbank.ereignis(self.lauf, ART_NACHTRAEGLICH_BESTAETIGT, quelle, 1,
                                            meldungen.EREIGNIS_NACHTRAEGLICH)
                        continue
                    self.index_nachtragen(schreib, hz)   # spart das zweite Lesen gleich
                elif self.direkt and st.st_size < int(z["groesse"]):
                    _entfernen_eigene(schreib)
                    e.angefangene_entfernt += 1
                    self.dbank.ereignis(self.lauf, ART_ANGEFANGENE_ENTFERNT, schreib, 1,
                                        meldungen.EREIGNIS_ANGEFANGENE_ENTFERNT)
            self.dbank.zurueck_auf_analysiert(z["quellpfad"], ziel)
        self.dbank.stapel_schreiben()

    # -- Einreichen ------------------------------------------------------

    def gruppe_einreichen(self, q: _Quelle, zeilen: list) -> bool:
        """False, wenn ein Zielname gerade in Arbeit ist (spaeter noch einmal)."""
        auftraege: list[_Auftrag] = []
        for z in zeilen:
            ziel = Path(db.text_pfad(z["zielpfad"]))
            if db.pfad_text(ziel) in self.in_arbeit or db.pfad_text(part_pfad(ziel)) in self.in_arbeit:
                return False
            auftraege.append(_Auftrag(z, Path(db.text_pfad(z["quellpfad"])), ziel, part_pfad(ziel), _stamm(z)))
        if self.verschieben and self.umbenennen_moeglich(zeilen[0]["quellwurzel"]):
            # Gleiches Laufwerk, nachweislich: umbenennen statt kopieren.
            # Was sich nicht umbenennen laesst, geht den Kopierweg.
            auftraege = self._gruppe_umbenennen(auftraege)
            if not auftraege:
                return True
        if self.direkt and not self._exklusiv_anlegen(auftraege):
            return True   # als Fehler verbucht, nichts mehr zu tun
        for a in auftraege:
            self.dbank.kopieren_beanspruchen(a.zeile["quellpfad"], a.ziel, a.schreibziel, self.lauf)
            self.in_arbeit.add(db.pfad_text(a.ziel))
            self.in_arbeit.add(db.pfad_text(a.schreibziel))
            if db.pfad_text(a.ziel) != db.pfad_text(a.schreibziel):
                a.ziel_da = _stat(a.ziel) is not None
                if a.ziel_da:
                    a.ziel_hash = self.hash_von_vorhandener(a.ziel)   # parallel zur Kopie
        # Der Anspruch muss VOR dem ersten Schreiben festgeschrieben sein
        # (SPEC §5): Nur dann erkennt der naechste Start nach einem Absturz,
        # wem eine liegengebliebene Datei gehoert. Festgeschrieben und
        # abgeschickt wird in bereit_abschicken() - fuer alle Gruppen einer
        # Runde mit EINEM Commit (Tempo, Phase 6).
        self.bereit.append(auftraege)
        if self.direkt:
            # Rueckfall ohne .part: Die Dateien liegen schon exklusiv unter
            # ihrem Endnamen. Nicht bis zu einer Runde davon ohne festgeschriebenen
            # Anspruch liegen lassen - hier je Gruppe festschreiben wie vorher.
            self.bereit_abschicken()
        return True

    def bereit_abschicken(self) -> None:
        """Ansprueche aller vorbereiteten Gruppen festschreiben, dann erst
        die Kopien starten (SPEC §5: Anspruch vor dem ersten Schreiben)."""
        if not self.bereit:
            return
        self.dbank.stapel_schreiben()
        for auftraege in self.bereit:
            for a in auftraege:
                a.zukunft = self.kopierer.submit(
                    _kopieren_worker, a.quelle, a.schreibziel, a.zeile["groesse"],
                    a.zeile["mtime"], self.stop, a.fd
                )
            self.offen.append(auftraege)
        self.bereit.clear()

    def umbenennen_moeglich(self, quellwurzel: str) -> bool:
        """Verschieben durch Umbenennen nur, wenn Quelle und Ziel NACHWEISLICH
        auf demselben Laufwerk liegen (nie bei Netzpfaden, SPEC §4 Phase 3)
        und das Ziel nicht ueberschreibendes Umbenennen kann (SPEC §5)."""
        if quellwurzel not in self.umbenennen_je_wurzel:
            self.umbenennen_je_wurzel[quellwurzel] = (
                not self.direkt and pfade.gleiches_laufwerk(Path(db.text_pfad(quellwurzel)), self.ziel)
            )
        return self.umbenennen_je_wurzel[quellwurzel]

    def _gruppe_umbenennen(self, auftraege: list[_Auftrag]) -> list[_Auftrag]:
        """Verschieben auf demselben Laufwerk: nicht ueberschreibend umbenennen.
        Liefert die Auftraege, die doch kopiert werden muessen (KeinNoReplace)."""
        e = self.ergebnis
        rest: list[_Auftrag] = []
        for a in auftraege:
            st = _stat(a.quelle)
            if st is None:
                self._quelle_fehlt(a)
                continue
            if st.st_size != int(a.zeile["groesse"]) or not db._gleiche_zeit(st.st_mtime, a.zeile["mtime"]):
                self._quelle_veraendert(a, st.st_size, st.st_mtime_ns)
                continue
            if _stat(a.ziel) is not None:
                # Zielname belegt: gleicher Inhalt? Dafuer muss die Quelle einmal gelesen werden.
                try:
                    hq = hashes.blake3_datei(_L(a.quelle))
                    hz = self.hash_von_vorhandener(a.ziel).result()
                except OSError as fehler:
                    self._fehler(a, f"{GRUND_KOPIE}: {fehler.strerror or fehler}")
                    continue
                self.index_nachtragen(a.ziel, hz)
                if hq == hz:
                    self.dbank.duplikat_setzen(a.zeile["quellpfad"], a.ziel, hq, self.lauf)
                    self.dbank.ereignis(self.lauf, ART_DUPLIKAT, a.quelle, 1, db.pfad_text(a.ziel))
                    e.duplikate += 1
                    e.bearbeitet += 1
                    if self.anzeige:
                        self.anzeige.weiter(1, 0)
                    continue
            rest.append(a)
        if not rest:
            return []
        anhang = self._freier_anhang(rest, ab=0)
        kopieren_stattdessen: list[_Auftrag] = []
        for a in rest:
            k = anhang
            while True:
                endname = mit_anhang(a.ziel, k, a.stamm)
                # Anspruch VOR dem Umbenennen festschreiben (SPEC §5).
                self.dbank.kopieren_beanspruchen(a.zeile["quellpfad"], a.ziel, endname, self.lauf, umbenannt=True)
                self.dbank.stapel_schreiben()
                try:
                    _L(endname.parent).mkdir(parents=True, exist_ok=True)
                    pfade.umbenennen_ohne_ueberschreiben(a.quelle, endname)
                except FileExistsError:
                    k += 1
                    continue
                except pfade.KeinNoReplace:
                    # Dieses Verzeichnis kann es doch nicht: Kopierweg fuer diese Datei.
                    self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
                    kopieren_stattdessen.append(a)
                    break
                except OSError as fehler:
                    self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
                    self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", f"{GRUND_KOPIE}: {fehler.strerror or fehler}")
                    e.fehler += 1
                    e.bearbeitet += 1
                    if self.anzeige:
                        self.anzeige.weiter(1, 0)
                    break
                # Danach: Existenz und Groesse pruefen (SPEC §4 Phase 3).
                st2 = _stat(endname)
                groesse = int(a.zeile["groesse"])
                self.dbank.verschoben_setzen(a.zeile["quellpfad"], endname, self.lauf)
                if st2 is None or st2.st_size != groesse:
                    self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", meldungen.GRUND_VERSCHIEBEN_GROESSE)
                    e.fehler += 1
                else:
                    e.verschoben += 1
                    e.bytes_kopiert += groesse
                    if k > 0:
                        e.namenskonflikte += 1
                        self.dbank.ereignis(self.lauf, ART_NAMENSKONFLIKT, a.quelle, 1, db.pfad_text(endname))
                e.bearbeitet += 1
                if self.anzeige:
                    self.anzeige.weiter(1, groesse)
                break
        return kopieren_stattdessen

    def _quelle_fehlt(self, a: _Auftrag) -> None:
        e = self.ergebnis
        e.fehler += 1
        e.bearbeitet += 1
        self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", GRUND_QUELLE_FEHLT)
        if self.anzeige:
            self.anzeige.weiter(1, 0)

    def _quelle_veraendert(self, a: _Auftrag, groesse: int, mtime_ns: int) -> None:
        e = self.ergebnis
        e.quelle_veraendert += 1
        e.bearbeitet += 1
        self.dbank.zurueck_auf_gefunden(a.zeile["quellpfad"], groesse, mtime_ns / 1e9)
        self.dbank.ereignis(self.lauf, ART_QUELLE_VERAENDERT, a.quelle, 1, TEXT_QUELLE_VERAENDERT)
        if self.anzeige:
            self.anzeige.weiter(1, 0)

    # -- Verschieben ueber Kopieren: Frischlesung, dann Quelle entfernen -------

    def nachpruefung_einreihen(self, a: _Auftrag, endname: Path) -> None:
        zukunft = self.hasher.submit(loeschen.frisch_lesen, a.quelle, endname, self.byte_vergleich, self.stop, self.lauf)
        self.nachpruefung.append((a, endname, zukunft))

    def nachpruefungen_verbuchen(self, alle: bool) -> None:
        while self.nachpruefung:
            a, endname, zukunft = self.nachpruefung[0]
            if not zukunft.done():
                if not alle:
                    return
                wait([zukunft], timeout=1.0)
                continue
            self.nachpruefung.popleft()
            self._quelle_freigeben(a, endname, zukunft.result())

    def _quelle_freigeben(self, a: _Auftrag, endname: Path, L: loeschen.Lesung) -> None:
        """Nach dem Kopieren: Ziel UND Quelle wurden frisch gelesen. Stimmen
        beide mit dem beim Kopieren berechneten Hash ueberein, wird die Quelle
        ueber die einzige Loeschstelle entfernt (SPEC §4 Phase 3, §5)."""
        e = self.ergebnis
        quellpfad = a.zeile["quellpfad"]
        h = a.ergebnis.hash
        if L.art == "abgebrochen":
            return
        if L.art == "ok" and L.ziel_hash == h and L.quell_hash != h:
            self.dbank.zurueck_auf_analysiert_ohne_hash(quellpfad)
            self.dbank.ereignis(self.lauf, loeschen.ART_QUELLE_SEIT_KOPIEREN_GEAENDERT, quellpfad, 1,
                                meldungen.GRUND_QUELLE_ABWEICHUNG)
            e.quelle_seit_kopieren += 1
            return
        if L.art == "ok" and L.ziel_hash == h and L.quell_hash == h:
            self.dbank.geprueft_setzen(quellpfad)
            try:
                loeschen.quelldatei_entfernen(self.dbank, self.lauf, quellpfad, L, loeschen.WEISE_ENDGUELTIG, self.byte_vergleich)
            except OSError as fehler:
                grund = f"{meldungen.EREIGNIS_LOESCHFEHLER}: {fehler.strerror or fehler}"
                self.dbank.status_setzen(quellpfad, "fehler", grund)
                self.dbank.ereignis(self.lauf, loeschen.ART_LOESCHUNG_VERWEIGERT, quellpfad, 1, grund)
                e.loeschung_verweigert += 1
                return
            except loeschen.Verweigert as v:
                if str(v) == meldungen.GRUND_QUELLE_ABWEICHUNG:
                    # Quelle hat sich zwischen Lesung und Loeschung geaendert:
                    # nicht loeschen, neu kopieren (SPEC §5).
                    self.dbank.zurueck_auf_analysiert_ohne_hash(quellpfad)
                    self.dbank.ereignis(self.lauf, loeschen.ART_QUELLE_SEIT_KOPIEREN_GEAENDERT, quellpfad, 1, str(v))
                    e.quelle_seit_kopieren += 1
                    return
                self.dbank.status_setzen(quellpfad, "fehler", str(v))
                self.dbank.ereignis(self.lauf, loeschen.ART_LOESCHUNG_VERWEIGERT, quellpfad, 1, str(v))
                e.loeschung_verweigert += 1
                return
            e.quelle_geloescht += 1
            return
        grund = L.grund or (meldungen.grund_lesung(L.art) if L.art != "ok" else meldungen.GRUND_ZIEL_ABWEICHUNG)
        self.dbank.status_setzen(quellpfad, "fehler", grund)
        self.dbank.ereignis(self.lauf, loeschen.ART_LOESCHUNG_VERWEIGERT, quellpfad, 1, grund)
        e.loeschung_verweigert += 1

    def _exklusiv_anlegen(self, auftraege: list[_Auftrag]) -> bool:
        """Rueckfall ohne .part: Dateien unter dem endgueltigen Namen exklusiv
        anlegen, BEVOR der Anspruch festgeschrieben wird.

        So ist nach einem Absturz bewiesen, dass die Datei unter dem
        beanspruchten Pfad vom Programm stammt (SPEC §5) - eine fremde Datei
        haette das exklusive Anlegen scheitern lassen. Der Anhang steht damit
        vor der Duplikat-Entscheidung fest. False: als Fehler verbucht.
        """
        k = 0
        while True:
            k = self._freier_anhang(auftraege, ab=k)
            angelegt: list[_Auftrag] = []
            try:
                for a in auftraege:
                    name = mit_anhang(a.ziel, k, a.stamm)
                    _L(name.parent).mkdir(parents=True, exist_ok=True)
                    a.fd = hashes.exklusiv_anlegen(_L(name))
                    a.schreibziel = name
                    a.anhang = k
                    angelegt.append(a)
                return True
            except FileExistsError:
                # Jemand war schneller: Eigenes zuruecknehmen, naechster Anhang.
                self._zuruecknehmen(angelegt)
                k += 1
            except OSError as fehler:
                self._zuruecknehmen(angelegt)
                grund = f"{GRUND_KOPIE}: {fehler.strerror or fehler}"
                for a in auftraege:
                    self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", grund)
                    self.ergebnis.fehler += 1
                    self.ergebnis.bearbeitet += 1
                    if self.anzeige:
                        self.anzeige.weiter(1, 0)
                return False

    @staticmethod
    def _zuruecknehmen(angelegt: list[_Auftrag]) -> None:
        for a in angelegt:
            if a.fd is not None:
                os.close(a.fd)
                a.fd = None
            _entfernen_eigene(a.schreibziel)
            a.schreibziel = part_pfad(a.ziel)

    def _freier_anhang(self, auftraege: list[_Auftrag], ab: int) -> int:
        """Kleinster Anhang, unter dem KEIN Name der Gruppe vergeben ist.

        Die eigenen, gerade entstehenden Dateien der Gruppe (.part) zaehlen
        dabei nicht als vergeben.
        """
        dateien = frozenset(db.pfad_text(a.schreibziel) for a in auftraege)
        namen = frozenset(db.pfad_text(a.ziel) for a in auftraege)
        frei = frozenset(db.pfad_text(a.ziel) for a in auftraege if a.ziel_da is False)
        k = ab
        while True:
            if not any(
                self.belegt(mit_anhang(a.ziel, k, a.stamm), dateien, namen, frei)
                or self.belegt(part_pfad(mit_anhang(a.ziel, k, a.stamm)), dateien, namen)
                for a in auftraege
            ):
                return k
            k += 1

    # -- Abschliessen ----------------------------------------------------

    def gruppe_abschliessen(self, auftraege: list[_Auftrag]) -> tuple[list[_Auftrag], int] | None:
        """Ergebnisse verbuchen, Duplikate erkennen, Anhang bestimmen und den
        endgueltigen Namen je Mitglied vormerken (schreibpfad). Liefert
        (Rest, Anhang) fuer gruppe_fertigstellen - erst NACH dem gemeinsamen
        Commit der Runde wird umbenannt (SPEC §5: Name vor dem Umbenennen
        festgeschrieben; Tempo: ein Commit je Runde statt je Datei)."""
        e = self.ergebnis
        bleiben: list[_Auftrag] = []
        for a in auftraege:
            k: _Kopie = a.zukunft.result()
            a.ergebnis = k
            self.in_arbeit.discard(db.pfad_text(a.schreibziel))
            if k.art == "ok":
                if self.anzeige:
                    self.anzeige.weiter(1, k.bytes)
                bleiben.append(a)
                continue
            self.in_arbeit.discard(db.pfad_text(a.ziel))
            if k.art == "belegt":
                # Der Schreibname war belegt. Im Rueckfall der endgueltige Name
                # (jemand war schneller): naechster freier Name beim zweiten
                # Versuch. Sonst eine .part-Datei, die keine Zeile beansprucht:
                # Die darf weg (SPEC §5), dann zweiter Versuch.
                self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
                if self.direkt:
                    self.wartend.append((None, [a.zeile]))
                elif self._part_unbeansprucht(a):
                    _entfernen_eigene(a.schreibziel)
                    e.part_aufgeraeumt += 1
                    self.dbank.ereignis(self.lauf, ART_PART_AUFGERAEUMT, a.schreibziel, 1,
                                        meldungen.EREIGNIS_PART_AUFGERAEUMT)
                    self.wartend.append((None, [a.zeile]))
                else:
                    self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", GRUND_PART_BELEGT)
                    e.fehler += 1
                    e.bearbeitet += 1
                    if self.anzeige:
                        self.anzeige.weiter(1, 0)
                continue
            e.bearbeitet += 1
            if self.anzeige:
                self.anzeige.weiter(1, 0)
            if k.art == "abgebrochen":
                self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
            elif k.art == "fehlt":
                e.fehler += 1
                self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
                self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", GRUND_QUELLE_FEHLT)
            elif k.art == "veraendert":
                e.quelle_veraendert += 1
                self.dbank.zurueck_auf_gefunden(a.zeile["quellpfad"], k.bytes, k.mtime_ns / 1e9)
                self.dbank.ereignis(self.lauf, ART_QUELLE_VERAENDERT, a.quelle, 1, k.grund or TEXT_QUELLE_VERAENDERT)
            else:
                e.fehler += 1
                self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
                self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", k.grund or GRUND_KOPIE)

        # 1. Inhaltsgleich schon im Ziel? -> duplikat, eigene Kopie weg.
        rest: list[_Auftrag] = []
        for a in bleiben:
            partner = self._duplikat_partner(a)
            if partner is not None:
                _entfernen_eigene(a.schreibziel)
                self.in_arbeit.discard(db.pfad_text(a.ziel))
                self.dbank.duplikat_setzen(a.zeile["quellpfad"], partner, a.ergebnis.hash, self.lauf)
                self.dbank.ereignis(self.lauf, ART_DUPLIKAT, a.quelle, 1, db.pfad_text(partner))
                e.duplikate += 1
                e.bearbeitet += 1
                continue
            rest.append(a)

        # 2. Endgueltiger Name: gemeinsamer Anhang fuer die ganze Gruppe.
        if not rest:
            return None
        if self.direkt:
            anhang = rest[0].anhang
        else:
            anhang = self._freier_anhang(rest, ab=0)
            for a in rest:
                self.dbank.schreibpfad_setzen(a.zeile["quellpfad"], mit_anhang(a.ziel, anhang, a.stamm))
        for a in rest:
            if a.zeile["dateityp"] != "sidecar":
                self.hash_anstehend.setdefault(
                    a.ergebnis.hash, (mit_anhang(a.ziel, anhang, a.stamm), a.ergebnis.bytes, id(a)))
        return rest, anhang

    def gruppe_fertigstellen(self, rest: list[_Auftrag], anhang: int) -> None:
        """Nach dem Commit der Runde: umbenennen und 'kopiert' verbuchen."""
        for a in rest:
            self._endgueltig(a, anhang, vorgemerkt=True)

    def _part_unbeansprucht(self, a: _Auftrag) -> bool:
        """Beansprucht eine andere Zeile den Zielnamen dieser .part-Datei?"""
        for z in self.dbank.verbindung.execute(
            "SELECT quellpfad FROM dateien WHERE zielpfad = ? AND status = 'kopieren_laeuft'",
            (db.pfad_text(a.ziel),),
        ):
            if z["quellpfad"] != a.zeile["quellpfad"]:
                return False
        return True

    def _duplikat_partner(self, a: _Auftrag) -> Path | None:
        h = a.ergebnis.hash
        # a) Der berechnete Zielname ist belegt: gleicher Inhalt?
        if a.ziel_hash is None and a.ziel_da is not False and _stat(a.ziel) is not None \
                and db.pfad_text(a.ziel) != db.pfad_text(a.schreibziel):
            a.ziel_hash = self.hash_von_vorhandener(a.ziel)
        if a.ziel_hash is not None:
            try:
                vorhanden = a.ziel_hash.result()
            except OSError:
                vorhanden = ""
            if vorhanden:
                self.index_nachtragen(a.ziel, vorhanden)
                if vorhanden == h:
                    return a.ziel
        # b) Gleicher Inhalt unter anderem Namen (Ziel-Index, auch aus diesem
        #    Lauf). Sidecars nicht: Leere XMP-Dateien gleichen sich oft, und
        #    jede gehoert zu ihrer Hauptdatei.
        if a.zeile["dateityp"] == "sidecar":
            return None
        anstehend = self.hash_anstehend.get(h)
        if anstehend is not None and anstehend[1] == a.ergebnis.bytes \
                and db.pfad_text(anstehend[0]) != db.pfad_text(a.schreibziel):
            return anstehend[0]
        for eintrag in self.dbank.ziel_index_nach_hash(h):
            p = Path(db.text_pfad(eintrag["zielpfad"]))
            if db.pfad_text(p) == db.pfad_text(a.schreibziel):
                continue
            st = _stat(p)
            if st is None:
                self.dbank.ziel_index_entfernen(p)   # Eintrag ohne Datei: nur ein Kandidat
                continue
            if st.st_size == a.ergebnis.bytes:
                return p
        return None

    def _endgueltig(self, a: _Auftrag, anhang: int, vorgemerkt: bool = False) -> None:
        e = self.ergebnis
        endname = mit_anhang(a.ziel, anhang, a.stamm)
        if not self.direkt:
            k = anhang
            while True:
                endname = mit_anhang(a.ziel, k, a.stamm)
                # Vor dem Umbenennen festhalten, wo die Datei gleich liegt:
                # Nach einem Absturz zwischen Umbenennen und "kopiert" findet
                # der naechste Start sie so wieder (SPEC §5). Fuer den
                # vorgemerkten Anhang hat das die Runde schon festgeschrieben.
                if not vorgemerkt or k != anhang:
                    self.dbank.schreibpfad_setzen(a.zeile["quellpfad"], endname)
                    self.dbank.stapel_schreiben()
                try:
                    pfade.umbenennen_ohne_ueberschreiben(a.schreibziel, endname)
                    break
                except FileExistsError:
                    k += 1      # jemand war schneller: naechster freier Name
                    continue
                except pfade.KeinNoReplace:
                    # Dieses Ziel-Verzeichnis kann kein nicht ueberschreibendes
                    # Umbenennen: Inhalt exklusiv an den Zielnamen kopieren.
                    stand = self._part_ohne_umbenennen(a, endname)
                    if stand == "belegt":
                        k += 1
                        continue
                    if stand != "ok":
                        self._fehler(a, stand)
                        return
                    break
                except OSError as fehler:
                    self._fehler(a, f"{GRUND_KOPIE}: {fehler.strerror or fehler}")
                    return
            if k != anhang:
                # Ein Fremdprozess hat den Gruppennamen dazwischen belegt: Dieses
                # Mitglied traegt einen anderen Anhang als die Gruppe. Nichts
                # geht verloren; der Bericht zeigt es (SPEC §5, docs/todo.md).
                self.dbank.ereignis(self.lauf, ART_ANHANG_ABWEICHEND, a.quelle, 1,
                                    f"{meldungen.EREIGNIS_ANHANG_ABWEICHEND}: {db.pfad_text(endname)}")
                e.anhang_abweichend += 1
            anhang = k
        self.in_arbeit.discard(db.pfad_text(a.ziel))
        self.dbank.kopiert_setzen(a.zeile["quellpfad"], endname, a.ergebnis.hash, self.lauf)
        # Groesse und Zeit der eben geschriebenen Datei liefert der Worker:
        # kein stat je Datei im Hauptstrang noetig.
        self.dbank.ziel_index_setzen(endname, a.ergebnis.bytes, a.ergebnis.mtime_ns / 1e9, a.ergebnis.hash, self.lauf)
        self._anstehend_erledigt(a, endname)
        e.kopiert += 1
        e.bearbeitet += 1
        e.bytes_kopiert += a.ergebnis.bytes
        if anhang > 0:
            e.namenskonflikte += 1
            self.dbank.ereignis(self.lauf, ART_NAMENSKONFLIKT, a.quelle, 1, db.pfad_text(endname))
        if self.verschieben:
            self.nachpruefung_einreihen(a, endname)

    def _anstehend_erledigt(self, a: _Auftrag, endname: Path | None) -> None:
        """Den Eintrag in hash_anstehend abschliessen, den DIESER Auftrag
        gesetzt hat. endname: wo die Datei jetzt wirklich liegt (im
        Ziel-Index) - weicht er vom geplanten Namen ab (Fremdprozess hat den
        Namen belegt), werden die Duplikate dieser Runde umgeschrieben; None:
        die Datei kam nicht an, ihre Duplikate muessen neu kopiert werden
        (Pruefbefund Phase 6)."""
        if a.ergebnis is None:
            return
        eintrag = self.hash_anstehend.get(a.ergebnis.hash)
        if eintrag is None or eintrag[2] != id(a):
            return
        geplant = eintrag[0]
        self.hash_anstehend.pop(a.ergebnis.hash, None)
        if endname is not None:
            if db.pfad_text(endname) != db.pfad_text(geplant):
                self.dbank.duplikat_partner_umschreiben(geplant, endname, self.lauf)
            return
        from . import analyse
        from . import ziel as ziel_modul
        struktur = ziel_modul.Zielstruktur(self.ziel)
        for z in self.dbank.duplikate_mit_partner(geplant, self.lauf):
            self.dbank.zurueck_auf_analysiert(z["quellpfad"], analyse.zielpfad_aus_zeile(struktur, z, self.konf))
            self.ergebnis.duplikate -= 1
            self.ergebnis.bearbeitet -= 1
            self.wartend.append((None, [z]))

    def _part_ohne_umbenennen(self, a: _Auftrag, endname: Path) -> str:
        """Rueckfall mitten im Lauf: .part -> Zielname als exklusive Kopie.

        Liefert "ok", "belegt" (Name inzwischen vergeben) oder einen
        Fehlergrund. Wirft nie - ein Fehler einer Datei bricht den Lauf nicht ab.
        """
        try:
            h, _n = hashes.kopieren_mit_hash(_L(a.schreibziel), _L(endname), self.stop)
        except FileExistsError:
            return "belegt"
        except hashes.Abgebrochen:
            return f"{GRUND_KOPIE}: abgebrochen"
        except OSError as fehler:
            return f"{GRUND_KOPIE}: {fehler.strerror or fehler}"
        if h != a.ergebnis.hash:
            _entfernen_eigene(endname)
            return meldungen.GRUND_PART_INHALT
        _entfernen_eigene(a.schreibziel)
        if not self.ergebnis.exfat_rueckfall:
            self.ergebnis.exfat_rueckfall = True
            self.dbank.ereignis(self.lauf, ART_EXFAT_RUECKFALL, endname.parent, 1,
                                meldungen.EREIGNIS_RUECKFALL_ORDNER)
        return "ok"

    def _fehler(self, a: _Auftrag, grund: str) -> None:
        _entfernen_eigene(a.schreibziel)
        self._anstehend_erledigt(a, None)
        self.in_arbeit.discard(db.pfad_text(a.ziel))
        self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
        self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", grund)
        self.ergebnis.fehler += 1
        self.ergebnis.bearbeitet += 1

    # -- Abbruch ---------------------------------------------------------

    def abbrechen(self) -> None:
        self.stop.set()
        self.kopierer.shutdown(wait=True, cancel_futures=True)
        for auftraege in [*self.offen, *self.bereit]:
            for a in auftraege:
                if a.zukunft is not None and a.zukunft.done() and not a.zukunft.cancelled():
                    k = a.zukunft.result()
                    # "ok" und "abgebrochen": die Schreibdatei hat dieser Lauf
                    # selbst angelegt. Bei "belegt" gehoert sie jemand anderem.
                    if k.art in ("ok", "abgebrochen"):
                        _entfernen_eigene(a.schreibziel)
                elif a.fd is not None:
                    # Rueckfall ohne .part: exklusiv angelegt, aber nie
                    # geschrieben - keine leere Datei unter einem echten Namen
                    # zuruecklassen (Pruefbefund).
                    self._zuruecknehmen([a])
                self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
        self.offen.clear()
        self.bereit.clear()
        self.nachpruefung.clear()   # Zeilen bleiben "kopiert"; aufraeumen holt sie nach
        self.hasher.shutdown(wait=True, cancel_futures=True)

    def schliessen(self) -> None:
        self.kopierer.shutdown(wait=True)
        self.hasher.shutdown(wait=True)


# ----------------------------------------------------------- Einstieg ----


def _quellen(dbank: db.Datenbank, lauf: int, ergebnis) -> dict[str, list[_Quelle]]:
    """Erreichbare Quellen, gruppiert nach Laufwerk."""
    je_laufwerk: dict[str, list[_Quelle]] = {}
    for z in dbank.quellen_liste():
        pfad = Path(db.text_pfad(z["wurzel"]))
        if not pfad.is_dir():
            ergebnis.quellen_nicht_erreichbar.append(z["wurzel"])
            if lauf:
                dbank.ereignis(lauf, ART_QUELLE_NICHT_ERREICHBAR, pfad, 1, meldungen.EREIGNIS_QUELLE_UEBERSPRUNGEN)
            continue
        laufwerk = z["laufwerk"] or pfade.laufwerk_kennung(pfad)
        je_laufwerk.setdefault(laufwerk, []).append(_Quelle(z["wurzel"], pfad, laufwerk))
    return je_laufwerk


def _nach_pruefung_zuruecksetzen(ziel: Path, konf, dbank: db.Datenbank, lauf: int) -> int:
    """Zeilen, deren Zielpruefung fehlschlug (Phase 4), wieder zum Kopieren
    freigeben. Ihr zielpfad zeigt auf die fehlerhafte Zieldatei oder die
    Partnerdatei eines Duplikats; der berechnete Name wird aus den
    gespeicherten Feldern neu bestimmt. Die fehlerhafte Zieldatei bleibt
    liegen ("Niemals ueberschreiben"): Die frische Kopie bekommt bei
    belegtem Namen den Anhang _1.
    """
    from . import analyse
    from . import ziel as ziel_modul

    zeilen = dbank.zeilen_mit_fehlergrund(meldungen.GRUND_PRUEFUNG)
    if not zeilen:
        return 0
    struktur = ziel_modul.Zielstruktur(ziel)
    freigegeben = 0
    for z in zeilen:
        if _stat(Path(db.text_pfad(z["quellpfad"]))) is None:
            # Keine Quelle mehr (verschoben oder verschwunden): Es gibt nichts,
            # was neu kopiert werden koennte. Bleibt Fehler, steht im Bericht.
            continue
        neu = analyse.zielpfad_aus_zeile(struktur, z, konf)
        dbank.zurueck_auf_analysiert(z["quellpfad"], neu)
        dbank.ereignis(lauf, ART_NEU_NACH_PRUEFUNG, z["quellpfad"], 1, meldungen.EREIGNIS_NEU_NACH_PRUEFUNG)
        freigegeben += 1
    dbank.stapel_schreiben()
    return freigegeben


def planen(ziel: Path, dbank: db.Datenbank) -> Plan:
    """--dry-run: nur zaehlen, nichts anfassen, kein Lauf."""
    plan = Plan()
    plan.liegengeblieben = len(dbank.liegengebliebene(-1))
    je_laufwerk = _quellen(dbank, 0, plan)
    for quellen in je_laufwerk.values():
        for q in quellen:
            n = b = 0
            while True:
                gruppe = q.naechste_gruppe(dbank)
                if gruppe is None:
                    break
                for z in gruppe:
                    n += 1
                    b += int(z["groesse"])
                    if _stat(Path(db.text_pfad(z["zielpfad"]))) is not None:
                        plan.zielname_belegt += 1
            plan.je_quelle[q.wurzel] = (n, b)
            plan.dateien += n
            plan.bytes += b
    return plan


def ausfuehren(ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole=None,
               kopier_worker: int | None = None, hash_worker: int | None = None,
               profil: str | None = None, verschieben: bool = False) -> Ergebnis:
    begonnen = time.monotonic()
    kw, hw, prof = worker_zahlen(konf, profil, kopier_worker, hash_worker)
    direkt = not pfade.kann_ohne_ueberschreiben(ziel)
    lauf_zustand = _Lauf(ziel, konf, dbank, lauf, konsole, kw, hw, direkt, verschieben)
    e = lauf_zustand.ergebnis
    e.kopier_worker, e.hash_worker, e.profil = kw, hw, prof
    e.verschieben = verschieben
    if direkt:
        e.exfat_rueckfall = True
        dbank.ereignis(lauf, ART_EXFAT_RUECKFALL, ziel, 1, meldungen.EREIGNIS_RUECKFALL_ZIEL)
    try:
        # 1. Reste eines abgebrochenen Laufs (SPEC Abschnitt 5).
        lauf_zustand.liegengebliebene_aufraeumen()
        e.neu_nach_pruefung = _nach_pruefung_zuruecksetzen(ziel, konf, dbank, lauf)
        if e.neu_nach_pruefung and konsole is not None:
            konsole.print(meldungen.kopieren_neu_nach_pruefung(e.neu_nach_pruefung))

        # 2. Vorpruefungen. Gezaehlt wird nur, was aus erreichbaren Quellen
        #    ansteht - sonst waeren Platzpruefung und Anzeige zu hoch.
        je_laufwerk = _quellen(dbank, lauf, e)
        erreichbar = [q.wurzel for quellen in je_laufwerk.values() for q in quellen]
        e.geplant, e.geplant_bytes = dbank.zu_kopieren_summe(erreichbar)
        if e.geplant == 0:
            return e
        frei = pfade.freier_platz(ziel)
        if frei < e.geplant_bytes:
            raise FotosortFehler(meldungen.zu_wenig_platz(ziel, e.geplant_bytes, frei))
        if konsole is not None:
            konsole.print(meldungen.kopieren_beginnt(e.geplant, e.geplant_bytes, kw, hw, prof, direkt))
            if verschieben:
                for quellen in je_laufwerk.values():
                    for q in quellen:
                        konsole.print(f"  {q.wurzel}: " + meldungen.verschieben_hinweis(
                            lauf_zustand.umbenennen_moeglich(q.wurzel), direkt))
        lauf_zustand.anzeige = fortschritt.Fortschritt(konsole, e.geplant, e.geplant_bytes, meldungen.kopieren_laeuft)

        # 3. Kopieren: Laufwerke abwechselnd, je Laufwerk in Ordnerreihenfolge.
        _schleife(lauf_zustand, je_laufwerk)
    except KeyboardInterrupt:
        e.abgebrochen = True
        lauf_zustand.abbrechen()
    finally:
        if lauf_zustand.anzeige:
            lauf_zustand.anzeige.stop()
        lauf_zustand.schliessen()
        dbank.stapel_schreiben()
    e.sekunden = time.monotonic() - begonnen
    return e


def _schleife(L: _Lauf, je_laufwerk: dict[str, list[_Quelle]]) -> None:
    reihe: deque[list[_Quelle]] = deque(je_laufwerk.values())   # ein Eintrag je Laufwerk
    while True:
        # Auffuellen, bis genug in Arbeit ist. Gruppen, deren Zielname gerade
        # entsteht (gleicher Name aus zwei Quellen), warten bis zur naechsten
        # Runde - und werden in DIESER Runde nicht noch einmal gezogen.
        zurueckgestellt: list[tuple] = []
        while len(L.offen) + len(L.bereit) < L.max_offen:
            gruppe = _naechste(L, reihe)
            if gruppe is None:
                break
            if not L.gruppe_einreichen(*gruppe):
                zurueckgestellt.append(gruppe)
        L.bereit_abschicken()
        L.wartend.extend(zurueckgestellt)
        L.nachpruefungen_verbuchen(alle=False)
        if not L.offen:
            if not L.wartend:
                L.nachpruefungen_verbuchen(alle=True)
                break
            # Nichts mehr in Arbeit, also kann auch kein Name mehr "in Arbeit"
            # sein: Merkliste leeren und die Wartenden einreihen.
            L.in_arbeit.clear()
            continue
        # Auf die naechste fertige Gruppe warten (mit Zeitgrenze, damit
        # Strg+C jederzeit ankommt).
        wait([a.zukunft for g in L.offen for a in g], timeout=1.0, return_when=FIRST_COMPLETED)
        fertig = [g for g in L.offen if all(a.zukunft.done() for a in g)]
        vorbereitet: list[tuple[list[_Auftrag], int]] = []
        for g in fertig:
            L.offen.remove(g)
            v = L.gruppe_abschliessen(g)
            if v is not None:
                vorbereitet.append(v)
        if vorbereitet:
            L.dbank.stapel_schreiben()      # ein Commit fuer alle Namen dieser Runde
            for rest, anhang in vorbereitet:
                L.gruppe_fertigstellen(rest, anhang)


def _naechste(L: _Lauf, reihe: deque) -> tuple[_Quelle, list] | None:
    while L.wartend:
        q, zeilen = L.wartend.popleft()
        if q is None:
            # Ein einzelner Wiederholungsversuch: Zeile frisch aus der Datenbank.
            z = L.dbank.zeile(zeilen[0]["quellpfad"])
            if z is None or z["status"] != "analysiert":
                continue
            return _Quelle(z["quellwurzel"], Path(db.text_pfad(z["quellwurzel"])), ""), [z]
        return q, zeilen
    while reihe:
        quellen = reihe[0]
        reihe.rotate(-1)            # dieses Laufwerk liegt jetzt hinten
        while quellen:
            gruppe = quellen[0].naechste_gruppe(L.dbank)
            if gruppe is not None:
                return quellen[0], gruppe
            quellen.pop(0)
        reihe.pop()                 # erschoepft: das hintere Laufwerk entfernen
    return None
