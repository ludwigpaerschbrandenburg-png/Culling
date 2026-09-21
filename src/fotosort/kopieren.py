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

from . import FotosortFehler, db, hashes, meldungen, pfade
from .scan import ART_QUELLE_NICHT_ERREICHBAR, ART_QUELLE_VERAENDERT, TEXT_QUELLE_VERAENDERT

# Ereignisarten dieses Moduls (SPEC Abschnitt 6).
ART_DUPLIKAT = "duplikat"
ART_NAMENSKONFLIKT = "namenskonflikt"
ART_PART_AUFGERAEUMT = "part_aufgeraeumt"
ART_ANGEFANGENE_ENTFERNT = "angefangene_zieldatei_entfernt"
ART_NACHTRAEGLICH_BESTAETIGT = "kopie_nachtraeglich_bestaetigt"
ART_EXFAT_RUECKFALL = "rueckfall_kopieren"

GRUND_QUELLE_FEHLT = "Quelldatei nicht gefunden"
GRUND_QUELLE_WAEHREND_KOPIE = "Quelle hat sich waehrend des Kopierens veraendert"
GRUND_KOPIE = "Kopieren fehlgeschlagen"
GRUND_PART_BELEGT = "Zwischendatei (.part) ist von einem anderen Vorgang belegt"

PART = ".part"
PROFILE: dict[str, int] = {"hdd": 2, "netzwerk": 4, "ssd": 8}
SEITE = 2000
_STILLE_SEKUNDEN = 5.0


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
    zukunft: Future | None = None
    ziel_hash: Future | None = None  # Hash einer schon vorhandenen Datei am Zielnamen
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


def _kopieren_worker(quelle: Path, schreibziel: Path, groesse: int, mtime: float, stop: threading.Event) -> _Kopie:
    """Laeuft im Kopier-Worker. Fasst nur das Dateisystem an."""
    try:
        st = os.stat(_L(quelle))
    except FileNotFoundError:
        return _Kopie("fehlt")
    except OSError as fehler:
        return _Kopie("fehler", grund=f"{GRUND_KOPIE}: {fehler.strerror or fehler}")
    if st.st_size != int(groesse) or not db._gleiche_zeit(st.st_mtime, mtime):
        return _Kopie("veraendert", bytes=st.st_size, mtime_ns=st.st_mtime_ns)
    try:
        _L(schreibziel.parent).mkdir(parents=True, exist_ok=True)
        h, n = hashes.kopieren_mit_hash(_L(quelle), _L(schreibziel), stop)
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
    return _Kopie("ok", hash=h, bytes=n, mtime_ns=st.st_mtime_ns)


# ------------------------------------------------------------- Ablauf ----


class _Lauf:
    """Zustand eines Kopierlaufs; nur der Hauptstrang fasst ihn an."""

    def __init__(self, ziel: Path, konf, dbank: db.Datenbank, lauf: int, konsole,
                 kopier_worker: int, hash_worker: int, direkt: bool) -> None:
        self.ziel = ziel
        self.konf = konf
        self.dbank = dbank
        self.lauf = lauf
        self.konsole = konsole
        self.direkt = direkt                   # Rueckfall ohne .part
        self.stop = threading.Event()
        self.kopierer = ThreadPoolExecutor(max_workers=kopier_worker, thread_name_prefix="kopie")
        self.hasher = ThreadPoolExecutor(max_workers=hash_worker, thread_name_prefix="hash")
        self.max_offen = max(2, kopier_worker * 2)
        self.in_arbeit: set[str] = set()       # Zielnamen (Text), die gerade entstehen
        self.eigene: set[str] = set()          # Dateien, die dieser Lauf angelegt hat
        self.offen: list[list[_Auftrag]] = []  # eingereichte Gruppen
        self.wartend: deque[tuple[_Quelle, list]] = deque()
        self.ergebnis = Ergebnis()
        self.anzeige: _Anzeige | None = None

    # -- Namen -----------------------------------------------------------

    def belegt(self, p: Path, eigene_dateien: frozenset[str] = frozenset(),
               eigene_namen: frozenset[str] = frozenset()) -> bool:
        """Name im Ziel vergeben: gerade in Arbeit oder schon auf der Platte.

        eigene_dateien: Dateien, die die fragende Gruppe selbst gerade
        schreibt (.part) - zaehlen gar nicht. eigene_namen: die berechneten
        Zielnamen der Gruppe - sie stehen zwar in "in Arbeit", aber ob der
        Name auf der Platte belegt ist, muss trotzdem geprueft werden.
        """
        t = db.pfad_text(p)
        if t in eigene_dateien:
            return False
        if t in self.in_arbeit and t not in eigene_namen:
            return True
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
        st = _stat(p)
        if st is not None:
            self.dbank.ziel_index_setzen(p, st.st_size, st.st_mtime, h, self.lauf)

    # -- Aufraeumen (SPEC Abschnitt 5) ------------------------------------

    def liegengebliebene_aufraeumen(self) -> None:
        for z in self.dbank.liegengebliebene(self.lauf):
            quelle = Path(db.text_pfad(z["quellpfad"]))
            ziel = Path(db.text_pfad(z["zielpfad"]))
            part = part_pfad(ziel)
            if _stat(part) is not None:
                # Diese Zeile beansprucht die .part-Datei; sie wird neu geschrieben.
                _entfernen_eigene(part)
                self.ergebnis.part_aufgeraeumt += 1
                self.dbank.ereignis(self.lauf, ART_PART_AUFGERAEUMT, part, 1, "liegengebliebene .part-Datei entfernt")
            st = _stat(ziel)
            if st is not None:
                if st.st_size == int(z["groesse"]) and _stat(quelle) is not None:
                    # Vollstaendig? Dann beide frisch lesen und vergleichen.
                    h_ziel = self.hasher.submit(hashes.blake3_datei, _L(ziel))
                    h_quelle = self.hasher.submit(hashes.blake3_datei, _L(quelle))
                    try:
                        hz, hq = h_ziel.result(), h_quelle.result()
                    except OSError:
                        hz, hq = "", "x"
                    if hz == hq:
                        self.dbank.kopiert_setzen(z["quellpfad"], ziel, hq, self.lauf)
                        self.index_nachtragen(ziel, hz)
                        self.ergebnis.nachtraeglich_bestaetigt += 1
                        self.dbank.ereignis(self.lauf, ART_NACHTRAEGLICH_BESTAETIGT, quelle, 1,
                                            "Kopie aus abgebrochenem Lauf war vollstaendig")
                        continue
                    self.index_nachtragen(ziel, hz)   # spart das zweite Lesen gleich
                elif self.direkt and st.st_size < int(z["groesse"]):
                    # Nur im Rueckfall ohne .part kann unter dem endgueltigen
                    # Namen etwas Unvollstaendiges von uns liegen. SPEC §5:
                    # Zeile beansprucht genau diesen Pfad, Status
                    # kopieren_laeuft, Lauf nicht der laufende - und zusaetzlich
                    # kleiner als die Quelle.
                    _entfernen_eigene(ziel)
                    self.ergebnis.angefangene_entfernt += 1
                    self.dbank.ereignis(self.lauf, ART_ANGEFANGENE_ENTFERNT, ziel, 1,
                                        "angefangene Zieldatei aus abgebrochenem Lauf entfernt")
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
        anhang = 0
        if self.direkt:
            # Ohne .part muss der endgueltige Name vor dem Schreiben feststehen.
            anhang = self._freier_anhang(auftraege, ab=0)
        for a in auftraege:
            a.anhang = anhang
            if self.direkt:
                a.schreibziel = mit_anhang(a.ziel, anhang, a.stamm)
            self.dbank.kopieren_beanspruchen(a.zeile["quellpfad"], a.ziel, self.lauf)
            self.in_arbeit.add(db.pfad_text(a.ziel))
            self.in_arbeit.add(db.pfad_text(a.schreibziel))
            if _stat(a.ziel) is not None:
                a.ziel_hash = self.hash_von_vorhandener(a.ziel)   # parallel zur Kopie
        # Der Anspruch muss VOR dem ersten Schreiben festgeschrieben sein
        # (SPEC §5): Nur dann erkennt der naechste Start nach einem Absturz,
        # wem eine liegengebliebene Datei gehoert.
        self.dbank.stapel_schreiben()
        for a in auftraege:
            a.zukunft = self.kopierer.submit(
                _kopieren_worker, a.quelle, a.schreibziel, a.zeile["groesse"], a.zeile["mtime"], self.stop
            )
        self.offen.append(auftraege)
        return True

    def _freier_anhang(self, auftraege: list[_Auftrag], ab: int) -> int:
        """Kleinster Anhang, unter dem KEIN Name der Gruppe vergeben ist.

        Die eigenen, gerade entstehenden Dateien der Gruppe (.part) zaehlen
        dabei nicht als vergeben.
        """
        dateien = frozenset(db.pfad_text(a.schreibziel) for a in auftraege)
        namen = frozenset(db.pfad_text(a.ziel) for a in auftraege)
        k = ab
        while True:
            if not any(
                self.belegt(mit_anhang(a.ziel, k, a.stamm), dateien, namen)
                or self.belegt(part_pfad(mit_anhang(a.ziel, k, a.stamm)), dateien, namen)
                for a in auftraege
            ):
                return k
            k += 1

    # -- Abschliessen ----------------------------------------------------

    def gruppe_abschliessen(self, auftraege: list[_Auftrag]) -> None:
        e = self.ergebnis
        bleiben: list[_Auftrag] = []
        for a in auftraege:
            k: _Kopie = a.zukunft.result()
            a.ergebnis = k
            self.in_arbeit.discard(db.pfad_text(a.schreibziel))
            if k.art == "ok":
                self.eigene.add(db.pfad_text(a.schreibziel))
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
                                        "liegengebliebene .part-Datei entfernt")
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
                self.eigene.discard(db.pfad_text(a.schreibziel))
                self.in_arbeit.discard(db.pfad_text(a.ziel))
                self.dbank.duplikat_setzen(a.zeile["quellpfad"], partner, a.ergebnis.hash, self.lauf)
                self.dbank.ereignis(self.lauf, ART_DUPLIKAT, a.quelle, 1, db.pfad_text(partner))
                e.duplikate += 1
                e.bearbeitet += 1
                continue
            rest.append(a)

        # 2. Endgueltiger Name: gemeinsamer Anhang fuer die ganze Gruppe.
        if rest:
            if self.direkt:
                anhang = rest[0].anhang
            else:
                anhang = self._freier_anhang(rest, ab=0)
            for a in rest:
                self._endgueltig(a, anhang)

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
        if a.ziel_hash is None and _stat(a.ziel) is not None and db.pfad_text(a.ziel) != db.pfad_text(a.schreibziel):
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

    def _endgueltig(self, a: _Auftrag, anhang: int) -> None:
        e = self.ergebnis
        endname = mit_anhang(a.ziel, anhang, a.stamm)
        if not self.direkt:
            k = anhang
            while True:
                endname = mit_anhang(a.ziel, k, a.stamm)
                try:
                    pfade.umbenennen_ohne_ueberschreiben(a.schreibziel, endname)
                    break
                except FileExistsError:
                    k += 1      # jemand war schneller: naechster freier Name
                    continue
                except pfade.KeinNoReplace:
                    # Dieses Ziel-Verzeichnis kann kein nicht ueberschreibendes
                    # Umbenennen: Inhalt exklusiv an den Zielnamen kopieren.
                    if not self._part_ohne_umbenennen(a, endname):
                        k += 1
                        continue
                    break
                except OSError as fehler:
                    self._fehler(a, f"{GRUND_KOPIE}: {fehler.strerror or fehler}")
                    return
            if k != anhang:
                anhang = k
            self.eigene.discard(db.pfad_text(a.schreibziel))
        self.eigene.add(db.pfad_text(endname))
        self.in_arbeit.discard(db.pfad_text(a.ziel))
        self.dbank.kopiert_setzen(a.zeile["quellpfad"], endname, a.ergebnis.hash, self.lauf)
        self.index_nachtragen(endname, a.ergebnis.hash)
        e.kopiert += 1
        e.bearbeitet += 1
        e.bytes_kopiert += a.ergebnis.bytes
        if anhang > 0:
            e.namenskonflikte += 1
            self.dbank.ereignis(self.lauf, ART_NAMENSKONFLIKT, a.quelle, 1, db.pfad_text(endname))

    def _part_ohne_umbenennen(self, a: _Auftrag, endname: Path) -> bool:
        """Rueckfall mitten im Lauf: .part -> Zielname als exklusive Kopie."""
        try:
            h, _n = hashes.kopieren_mit_hash(_L(a.schreibziel), _L(endname), self.stop)
        except FileExistsError:
            return False
        if h != a.ergebnis.hash:
            _entfernen_eigene(endname)
            raise OSError(0, "Inhalt der .part-Datei stimmt nicht mehr")
        _entfernen_eigene(a.schreibziel)
        if not self.ergebnis.exfat_rueckfall:
            self.ergebnis.exfat_rueckfall = True
            self.dbank.ereignis(self.lauf, ART_EXFAT_RUECKFALL, endname.parent, 1,
                                "Dateisystem kann kein nicht ueberschreibendes Umbenennen")
        return True

    def _fehler(self, a: _Auftrag, grund: str) -> None:
        _entfernen_eigene(a.schreibziel)
        self.eigene.discard(db.pfad_text(a.schreibziel))
        self.in_arbeit.discard(db.pfad_text(a.ziel))
        self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
        self.dbank.status_setzen(a.zeile["quellpfad"], "fehler", grund)
        self.ergebnis.fehler += 1
        self.ergebnis.bearbeitet += 1

    # -- Abbruch ---------------------------------------------------------

    def abbrechen(self) -> None:
        self.stop.set()
        self.kopierer.shutdown(wait=True, cancel_futures=True)
        for auftraege in self.offen:
            for a in auftraege:
                if a.zukunft is not None and a.zukunft.done() and not a.zukunft.cancelled():
                    k = a.zukunft.result()
                    # "ok" und "abgebrochen": die Schreibdatei hat dieser Lauf
                    # selbst angelegt. Bei "belegt" gehoert sie jemand anderem.
                    if k.art in ("ok", "abgebrochen"):
                        _entfernen_eigene(a.schreibziel)
                self.dbank.zurueck_auf_analysiert(a.zeile["quellpfad"], a.ziel)
        self.offen.clear()
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
                dbank.ereignis(lauf, ART_QUELLE_NICHT_ERREICHBAR, pfad, 1, "nicht erreichbar, uebersprungen")
            continue
        laufwerk = z["laufwerk"] or pfade.laufwerk_kennung(pfad)
        je_laufwerk.setdefault(laufwerk, []).append(_Quelle(z["wurzel"], pfad, laufwerk))
    return je_laufwerk


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
               profil: str | None = None) -> Ergebnis:
    begonnen = time.monotonic()
    kw, hw, prof = worker_zahlen(konf, profil, kopier_worker, hash_worker)
    direkt = not pfade.kann_ohne_ueberschreiben(ziel)
    lauf_zustand = _Lauf(ziel, konf, dbank, lauf, konsole, kw, hw, direkt)
    e = lauf_zustand.ergebnis
    e.kopier_worker, e.hash_worker, e.profil = kw, hw, prof
    if direkt:
        e.exfat_rueckfall = True
        dbank.ereignis(lauf, ART_EXFAT_RUECKFALL, ziel, 1,
                       "Ziel kann kein nicht ueberschreibendes Umbenennen: ohne .part, exklusiv angelegt")
    try:
        # 1. Reste eines abgebrochenen Laufs (SPEC Abschnitt 5).
        lauf_zustand.liegengebliebene_aufraeumen()

        # 2. Vorpruefungen.
        e.geplant, e.geplant_bytes = dbank.zu_kopieren_summe()
        je_laufwerk = _quellen(dbank, lauf, e)
        if e.geplant == 0:
            return e
        frei = pfade.freier_platz(ziel)
        if frei < e.geplant_bytes:
            raise FotosortFehler(meldungen.zu_wenig_platz(ziel, e.geplant_bytes, frei))
        if konsole is not None:
            konsole.print(meldungen.kopieren_beginnt(e.geplant, e.geplant_bytes, kw, hw, prof, direkt))
        lauf_zustand.anzeige = _Anzeige(konsole, e.geplant, e.geplant_bytes)

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
        while len(L.offen) < L.max_offen:
            gruppe = _naechste(L, reihe)
            if gruppe is None:
                break
            if not L.gruppe_einreichen(*gruppe):
                zurueckgestellt.append(gruppe)
        L.wartend.extend(zurueckgestellt)
        if not L.offen:
            if not L.wartend:
                break
            # Nichts mehr in Arbeit, also kann auch kein Name mehr "in Arbeit"
            # sein: Merkliste leeren und die Wartenden einreihen.
            L.in_arbeit.clear()
            continue
        # Auf die naechste fertige Gruppe warten (mit Zeitgrenze, damit
        # Strg+C jederzeit ankommt).
        wait([a.zukunft for g in L.offen for a in g], timeout=1.0, return_when=FIRST_COMPLETED)
        fertig = [g for g in L.offen if all(a.zukunft.done() for a in g)]
        for g in fertig:
            L.offen.remove(g)
            L.gruppe_abschliessen(g)


def _naechste(L: _Lauf, reihe: deque) -> tuple[_Quelle, list] | None:
    if L.wartend:
        q, zeilen = L.wartend.popleft()
        if q is None:
            # Ein einzelner Wiederholungsversuch: Zeile frisch aus der Datenbank.
            z = L.dbank.zeile(zeilen[0]["quellpfad"])
            if z is None or z["status"] != "analysiert":
                return _naechste(L, reihe)
            return _Quelle(z["quellwurzel"], Path(db.text_pfad(z["quellwurzel"])), ""), [z]
        return q, zeilen
    versuche = len(reihe)
    while versuche and reihe:
        quellen = reihe[0]
        reihe.rotate(-1)
        versuche -= 1
        while quellen:
            gruppe = quellen[0].naechste_gruppe(L.dbank)
            if gruppe is not None:
                return quellen[0], gruppe
            quellen.pop(0)
        reihe.remove(quellen)
        versuche = len(reihe)
    return None


# --------------------------------------------------------- Fortschritt ----


class _Anzeige:
    """Fortschritt: Dateien und MB, MB/s, Restzeit; hoechstens 2 Aktualisierungen je Sekunde."""

    def __init__(self, konsole, gesamt: int, gesamt_bytes: int) -> None:
        self.konsole = konsole
        self.gesamt = gesamt
        self.gesamt_bytes = gesamt_bytes
        self.dateien = 0
        self.bytes = 0
        self.begonnen = time.monotonic()
        self._zuletzt = self.begonnen
        self.balken = None
        self.aufgabe = None
        if konsole is not None and getattr(konsole, "is_terminal", False):
            from rich.progress import BarColumn, Progress, TextColumn

            self.balken = Progress(
                TextColumn("{task.description}"), BarColumn(bar_width=None),
                TextColumn("{task.fields[rest]}"),
                console=konsole, refresh_per_second=2, transient=True,
            )
            self.aufgabe = self.balken.add_task(self._text(), total=gesamt_bytes or None, rest="")
            self.balken.start()

    def _text(self) -> str:
        return meldungen.kopieren_laeuft(self.dateien, self.gesamt, self.bytes, self.gesamt_bytes,
                                         self.bytes / max(1e-9, time.monotonic() - self.begonnen))

    def _rest(self) -> str:
        verstrichen = time.monotonic() - self.begonnen
        if self.bytes <= 0 or verstrichen <= 0:
            return ""
        rest = (self.gesamt_bytes - self.bytes) * verstrichen / self.bytes
        return meldungen.restzeit(rest)

    def weiter(self, dateien: int, bytes_: int) -> None:
        self.dateien += dateien
        self.bytes += bytes_
        jetzt = time.monotonic()
        if jetzt - self._zuletzt < (0.5 if self.balken else _STILLE_SEKUNDEN):
            return
        self._zuletzt = jetzt
        if self.balken is not None:
            self.balken.update(self.aufgabe, completed=self.bytes, description=self._text(), rest=self._rest())
        elif self.konsole is not None:
            self.konsole.print(self._text())

    def stop(self) -> None:
        if self.balken is not None:
            self.balken.stop()
