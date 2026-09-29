"""Tests fuer pfade.py."""

from __future__ import annotations

import sys
from pathlib import Path, PureWindowsPath

import pytest

from fotosort import pfade


def test_netz_dateisysteme_vollstaendig():
    # SPEC Abschnitt 6 zaehlt genau diese Typen auf.
    assert pfade.NETZ_DATEISYSTEME == frozenset(
        {"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "9p", "virtiofs"}
    )


def test_aufloesen_loest_verknuepfungen_auf(tmp_path):
    echt = tmp_path / "echt"
    echt.mkdir()
    link = tmp_path / "link"
    link.symlink_to(echt, target_is_directory=True)
    assert pfade.aufloesen(link) == pfade.aufloesen(echt)


def test_aufloesen_vertraegt_fehlende_pfade(tmp_path):
    fehlt = tmp_path / "gibt" / "es" / "nicht"
    assert pfade.aufloesen(fehlt).is_absolute()


def test_lang_unter_linux_unveraendert(tmp_path):
    if sys.platform.startswith("win"):  # pragma: no cover
        return
    assert pfade.lang(tmp_path) == Path(tmp_path)


_NUR_LINUX = pytest.mark.skipif(sys.platform.startswith("win"), reason="Linux-Mechanismus (/proc/mounts)")
_NUR_WINDOWS = pytest.mark.skipif(not sys.platform.startswith("win"), reason="nur unter Windows pruefbar")


@_NUR_LINUX
def test_dateisystem_typ_findet_etwas(tmp_path):
    typ = pfade.dateisystem_typ(tmp_path)
    assert typ  # unter Linux ist immer ein Einhaengepunkt zustaendig
    assert typ not in pfade.NETZ_DATEISYSTEME


def test_ist_netzpfad_fuer_lokalen_ordner_falsch(tmp_path):
    assert pfade.ist_netzpfad(tmp_path) is False


@_NUR_LINUX
def test_ist_netzpfad_bei_unbekanntem_typ_wahr(tmp_path, monkeypatch):
    # Laesst sich der Typ nicht bestimmen, ist die vorsichtige Antwort
    # "Netzpfad" (docs/architektur.md Abschnitt 2).
    monkeypatch.setattr(pfade, "_mountpunkte", lambda: [])
    assert pfade.ist_netzpfad(tmp_path) is True


@_NUR_LINUX
def test_ist_netzpfad_erkennt_netz_dateisystem(tmp_path, monkeypatch):
    monkeypatch.setattr(pfade, "_mountpunkte", lambda: [(str(tmp_path), "cifs")])
    assert pfade.ist_netzpfad(tmp_path) is True


@_NUR_WINDOWS
def test_windows_unc_pfad_gilt_als_netzpfad():
    assert pfade.ist_netzpfad(Path(r"\\server\freigabe\Fotos")) is True
    assert pfade.ist_netzpfad(Path(r"\\?\UNC\server\freigabe\Fotos")) is True


@_NUR_WINDOWS
def test_windows_netzlaufwerk_ueber_drive_type(tmp_path, monkeypatch):
    """Ein verbundener Laufwerksbuchstabe gilt als Netz, sobald GetDriveType DRIVE_REMOTE liefert."""
    import ctypes

    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda wurzel: pfade._DRIVE_REMOTE)
    assert pfade.ist_netzpfad(tmp_path) is True


@_NUR_WINDOWS
def test_windows_laufwerk_kennung_ist_der_buchstabe(tmp_path):
    kennung = pfade.laufwerk_kennung(tmp_path)
    assert kennung.startswith("laufwerk:") or kennung.startswith("server:")
    assert pfade.laufwerk_kennung(Path(r"\\server\freigabe\a")) == "server:server"


def test_gleiches_laufwerk_lokal(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert pfade.gleiches_laufwerk(a, b) is True


def test_gleiches_laufwerk_bei_netz_immer_falsch(tmp_path, monkeypatch):
    # SPEC Abschnitt 4 Phase 3: Ein Netzlaufwerk gilt nie als gleiches Laufwerk.
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setattr(pfade, "ist_netzpfad", lambda p: str(p) == str(a))
    assert pfade.gleiches_laufwerk(a, b) is False


def test_liegt_in(tmp_path):
    eltern = tmp_path / "eltern"
    kind = eltern / "kind" / "enkel"
    kind.mkdir(parents=True)
    assert pfade.liegt_in(kind, eltern) is True
    assert pfade.liegt_in(eltern, eltern) is True
    assert pfade.liegt_in(eltern, kind) is False


def test_liegt_in_folgt_verknuepfungen(tmp_path):
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    link = quelle / "abkuerzung"
    link.symlink_to(ziel, target_is_directory=True)
    # Ein reiner Textvergleich saehe hier nichts.
    assert pfade.liegt_in(link, ziel) is True


def test_lage_pruefen_alle_vier_faelle(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert pfade.lage_pruefen(a, a) == "gleich"
    assert pfade.lage_pruefen(a, b) == "getrennt"
    innen = a / "innen"
    innen.mkdir()
    assert pfade.lage_pruefen(a, innen) == "ziel_in_quelle"
    assert pfade.lage_pruefen(innen, a) == "quelle_in_ziel"


# ------------------------------------------- Langes Windows-Praefix ----
#
# Diese Tests laufen unter Linux. Geprueft wird die reine Textrechnung mit
# PureWindowsPath-Schreibweisen; dafuer braucht es kein Windows.


def test_lang_text_setzt_das_praefix():
    assert pfade.lang_text(r"C:\Chaos\2024") == "\\\\?\\" + r"C:\Chaos\2024"


def test_lang_text_setzt_unc_praefix():
    assert pfade.lang_text(r"\\truenas\Daten\Medien") == "\\\\?\\UNC\\" + r"truenas\Daten\Medien"


def test_lang_text_laesst_ein_vorhandenes_praefix_stehen():
    schon = "\\\\?\\" + r"C:\Chaos"
    assert pfade.lang_text(schon) == schon


def test_lang_text_laesst_relative_pfade_in_ruhe():
    assert pfade.lang_text(r"Unterordner\bild.jpg") == r"Unterordner\bild.jpg"


@pytest.mark.parametrize(
    "roh",
    [r"C:\Chaos\2024\a.jpg", r"\\truenas\Daten\Medien\a.jpg", r"C:\Ziel"],
)
def test_kurz_text_macht_lang_text_rueckgaengig(roh):
    assert pfade.kurz_text(pfade.lang_text(roh)) == roh


def test_kurz_text_ohne_praefix_unveraendert():
    assert pfade.kurz_text(r"C:\Chaos\a.jpg") == r"C:\Chaos\a.jpg"


def test_praefix_wuerde_die_vergleiche_zerstoeren():
    """Genau deshalb wird das Praefix nach os.scandir wieder abgenommen.

    Mit Praefix ist ein Eintrag weder "relativ zur Quellwurzel" noch
    "gleich dem Ziel" - die Ausschlussmuster und die Ziel-Pruefung liefen
    unter Windows ins Leere.
    """
    mit = PureWindowsPath(pfade.lang_text(r"C:\Chaos\2024\a.jpg"))
    assert mit.is_relative_to(PureWindowsPath(r"C:\Chaos")) is False
    assert PureWindowsPath(pfade.lang_text(r"C:\Ziel")) != PureWindowsPath(r"C:\Ziel")

    # Nach kurz_text passt wieder alles zusammen.
    ohne = PureWindowsPath(pfade.kurz_text(str(mit)))
    assert ohne.is_relative_to(PureWindowsPath(r"C:\Chaos")) is True


# ------------------------------- nicht ueberschreibendes Umbenennen (SPEC §5) ----


def test_umbenennen_ohne_ueberschreiben_bewegt_die_datei(tmp_path):
    a = tmp_path / "a.part"
    b = tmp_path / "a.jpg"
    a.write_bytes(b"inhalt")
    pfade.umbenennen_ohne_ueberschreiben(a, b)
    assert not a.exists() and b.read_bytes() == b"inhalt"


def test_umbenennen_ohne_ueberschreiben_ersetzt_nie(tmp_path):
    """Pflichttest aus SPEC Abschnitt 11: belegter Zielname, nichts geht verloren."""
    a = tmp_path / "a.part"
    b = tmp_path / "a.jpg"
    a.write_bytes(b"neu")
    b.write_bytes(b"schon da")
    with pytest.raises(FileExistsError):
        pfade.umbenennen_ohne_ueberschreiben(a, b)
    assert b.read_bytes() == b"schon da"
    assert a.read_bytes() == b"neu"


def test_kann_ohne_ueberschreiben_laesst_keine_probe_liegen(tmp_path):
    assert pfade.kann_ohne_ueberschreiben(tmp_path) is True
    assert list(tmp_path.iterdir()) == []


def test_freier_platz_ist_positiv(tmp_path):
    assert pfade.freier_platz(tmp_path) > 0
    assert pfade.freier_platz(tmp_path / "gibt" / "es" / "nicht") > 0


def test_umbenennen_ist_atomar_ohne_zweiten_namen(tmp_path):
    """Linux: renameat2 mit RENAME_NOREPLACE - kein Zwischenzustand mit zwei Namen."""
    a = tmp_path / "a.jpg"
    a.write_bytes(b"bild")
    b = tmp_path / "b.jpg"
    pfade.umbenennen_ohne_ueberschreiben(a, b)
    assert not a.exists() and b.read_bytes() == b"bild"
    assert b.stat().st_nlink == 1


def test_rueckfall_nimmt_den_zweiten_namen_zurueck(tmp_path, monkeypatch):
    """Scheitert im Rueckfall link+unlink das Entfernen des alten Namens,
    wird der neue wieder entfernt: Quelle und Archiv teilen sich nie eine Datei."""
    import os as _os

    if sys.platform.startswith("win"):
        pytest.skip("Windows nutzt MoveFileEx")
    monkeypatch.setattr(pfade, "_renameat2_noreplace", lambda von, nach: False)
    a = tmp_path / "a.jpg"
    a.write_bytes(b"bild")
    b = tmp_path / "b.jpg"
    echt = _os.unlink

    def unlink(pfad, *args, **kw):
        if str(pfad) == str(pfade.lang(a)):
            raise PermissionError(13, "verweigert", str(pfad))
        return echt(pfad, *args, **kw)

    monkeypatch.setattr(pfade.os, "unlink", unlink)
    with pytest.raises(PermissionError):
        pfade.umbenennen_ohne_ueberschreiben(a, b)
    assert a.read_bytes() == b"bild" and not b.exists()
    assert a.stat().st_nlink == 1


def test_rueckfall_entfernt_nie_den_letzten_namen(tmp_path, monkeypatch):
    """Ist der alte Name zwischen link und unlink schon weg (anderes Programm,
    oder NFS meldet eine wiederholte Anfrage als "nicht gefunden", obwohl die
    erste wirkte), traegt nur noch der neue Name die Datei. Ihn zu entfernen
    hiesse, das Bild zu loeschen - der Umzug ist dann einfach erledigt."""
    import os as _os

    if sys.platform.startswith("win"):
        pytest.skip("Windows nutzt MoveFileEx")
    monkeypatch.setattr(pfade, "_renameat2_noreplace", lambda von, nach: False)
    a = tmp_path / "a.part"
    a.write_bytes(b"bild")
    b = tmp_path / "a.jpg"
    echt = _os.unlink

    def unlink_wirkt_meldet_aber_fehlt(pfad, *args, **kw):
        echt(pfad, *args, **kw)
        if str(pfad) == str(pfade.lang(a)):
            raise FileNotFoundError(2, "nicht gefunden", str(pfad))

    monkeypatch.setattr(pfade.os, "unlink", unlink_wirkt_meldet_aber_fehlt)
    pfade.umbenennen_ohne_ueberschreiben(a, b)
    assert b.read_bytes() == b"bild" and not a.exists()


def test_rueckfall_laesst_eine_zwischendurch_ersetzte_quelle_stehen(tmp_path, monkeypatch):
    """Wird der alte Name zwischen link und unlink durch eine ANDERE Datei
    ersetzt, darf das unlink sie nicht treffen - und der neue Name, der jetzt
    der einzige der alten Datei ist, bleibt auch. Beide bleiben, Fehler."""
    import os as _os

    if sys.platform.startswith("win"):
        pytest.skip("Windows nutzt MoveFileEx")
    monkeypatch.setattr(pfade, "_renameat2_noreplace", lambda von, nach: False)
    a = tmp_path / "a.jpg"
    a.write_bytes(b"alt")
    b = tmp_path / "b.jpg"
    echt_link = _os.link

    def link_dann_ersetzt(von, nach, *args, **kw):
        echt_link(von, nach, *args, **kw)
        echt = _os.unlink
        echt(von)
        Path(von).write_bytes(b"neu")

    monkeypatch.setattr(pfade.os, "link", link_dann_ersetzt)
    with pytest.raises(OSError):
        pfade.umbenennen_ohne_ueberschreiben(a, b)
    assert a.read_bytes() == b"neu" and b.read_bytes() == b"alt"


def test_rueckfall_ohne_schreibrecht_im_quellordner_faellt_aufs_kopieren(tmp_path, monkeypatch):
    if sys.platform.startswith("win"):
        pytest.skip("Windows nutzt MoveFileEx")
    monkeypatch.setattr(pfade, "_renameat2_noreplace", lambda von, nach: False)
    monkeypatch.setattr(pfade.os, "access", lambda pfad, modus: False)
    a = tmp_path / "a.jpg"
    a.write_bytes(b"bild")
    with pytest.raises(pfade.KeinNoReplace):
        pfade.umbenennen_ohne_ueberschreiben(a, tmp_path / "b.jpg")
    assert a.exists() and not (tmp_path / "b.jpg").exists()


def _archiv_marke(ordner: Path, kennung: str) -> None:
    (ordner / ".fotosortierer").mkdir(parents=True, exist_ok=True)
    (ordner / ".fotosortierer" / "archiv-id.txt").write_text(kennung + "\n", encoding="utf-8")


def test_lage_erkennt_das_ziel_an_seiner_kennung(tmp_path):
    """Dieselbe Netzfreigabe zweimal eingehaengt: Pfade und Geraetenummern
    unterscheiden sich, die Archiv-Kennung nicht."""
    kennung = "a" * 32
    ziel = tmp_path / "mnt_ziel"
    zweiter_weg = tmp_path / "mnt_quelle" / "Archiv"      # steht fuer dieselbe Freigabe
    for o in (ziel, zweiter_weg):
        o.mkdir(parents=True)
        _archiv_marke(o, kennung)
    (zweiter_weg / "2024").mkdir()
    assert pfade.lage_pruefen(zweiter_weg, ziel) == "gleich"
    assert pfade.lage_pruefen(zweiter_weg / "2024", ziel) == "quelle_in_ziel"
    anderes = tmp_path / "Altes Archiv"
    anderes.mkdir()
    _archiv_marke(anderes, "b" * 32)                     # ein anderes Archiv als Quelle ist erlaubt
    assert pfade.lage_pruefen(anderes, ziel) == "getrennt"


# ------------------------------------------- Schreibschutz (Windows) ----


def _unlink_einmal_verweigert(monkeypatch, wie_oft: int = 1) -> list:
    import os as _os
    echt = _os.unlink
    aufrufe: list = []

    def unlink(pfad, *a, **k):
        aufrufe.append(pfad)
        if len(aufrufe) <= wie_oft:
            raise PermissionError(13, "Zugriff verweigert")
        echt(pfad, *a, **k)

    monkeypatch.setattr(pfade.os, "unlink", unlink)
    return aufrufe


def test_schreibgeschuetzte_datei_wird_nach_allen_pruefungen_trotzdem_entfernt(tmp_path, monkeypatch):
    """Unter Windows laesst sich eine Datei mit dem Attribut "Schreibgeschuetzt"
    (haeufig bei Kopien von Speicherkarten und CDs) nicht loeschen. Frueher endete
    jede solche Datei beim Aufraeumen als Fehler; jetzt wird das Attribut fuer
    genau diese eine, schon gepruefte Datei aufgehoben."""
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    aufrufe = _unlink_einmal_verweigert(monkeypatch)
    monkeypatch.setattr(pfade, "_schreibgeschuetzt", lambda pfad: True)
    aufgehoben: list = []
    monkeypatch.setattr(pfade, "_schreibschutz_setzen", lambda pfad, an: aufgehoben.append(an))
    pfade.datei_entfernen(p)
    assert not p.exists() and len(aufrufe) == 2 and aufgehoben == [False]


def test_ohne_schreibschutz_bleibt_der_fehler_ein_fehler(tmp_path, monkeypatch):
    """Fehlende Rechte (nicht der Schreibschutz) werden nicht umgangen."""
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    _unlink_einmal_verweigert(monkeypatch)
    monkeypatch.setattr(pfade, "_schreibgeschuetzt", lambda pfad: False)
    aufgehoben: list = []
    monkeypatch.setattr(pfade, "_schreibschutz_setzen", lambda pfad, an: aufgehoben.append(an))
    with pytest.raises(PermissionError):
        pfade.datei_entfernen(p)
    assert p.exists() and aufgehoben == []


def test_schreibschutz_kommt_zurueck_wenn_das_entfernen_trotzdem_scheitert(tmp_path, monkeypatch):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    _unlink_einmal_verweigert(monkeypatch, wie_oft=2)
    monkeypatch.setattr(pfade, "_schreibgeschuetzt", lambda pfad: True)
    aufgehoben: list = []
    monkeypatch.setattr(pfade, "_schreibschutz_setzen", lambda pfad, an: aufgehoben.append(an))
    with pytest.raises(PermissionError):
        pfade.datei_entfernen(p)
    assert p.exists() and aufgehoben == [False, True]


class _Gesperrt(PermissionError):
    """Wie Windows' Sharing Violation (Fehler 32): ein Virenscanner prueft die Datei gerade."""
    winerror = 32


def test_kurz_gesperrte_datei_wird_nach_kurzer_wartezeit_entfernt(tmp_path, monkeypatch):
    """Virenscanner und Suchindex halten frisch geschriebene Dateien unter
    Windows kurz offen. Frueher endete das Entfernen dann sofort als Fehler."""
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    import os as _os
    echt = _os.unlink
    versuche = []

    def unlink(pfad, *a, **k):
        versuche.append(1)
        if len(versuche) <= 2:
            raise _Gesperrt(13, "Der Prozess kann nicht auf die Datei zugreifen")
        echt(pfad, *a, **k)

    monkeypatch.setattr(pfade.os, "unlink", unlink)
    monkeypatch.setattr(pfade, "GEDULD_PAUSE", 0.001)
    pfade.datei_entfernen(p)
    assert not p.exists() and len(versuche) == 3


def test_geduld_reicht_fuer_einen_langsamen_virenscanner(monkeypatch):
    """SPEC §5: zusammen gut 15 s. Ein Virenscanner prueft ein grosses Video
    laenger als ein paar Sekunden; frueher gab das Programm nach 4,5 s auf."""
    pausen: list = []
    monkeypatch.setattr(pfade.time, "sleep", pausen.append)

    def immer_gesperrt():
        raise _Gesperrt(13, "gesperrt")

    with pytest.raises(PermissionError):
        pfade.geduldig(immer_gesperrt)
    assert 14.0 <= sum(pausen) <= 20.0


def test_geduld_prueft_vor_jedem_weiteren_versuch(monkeypatch):
    monkeypatch.setattr(pfade, "GEDULD_PAUSE", 0.0)
    ablauf: list = []

    def gesperrt():
        ablauf.append("versuch")
        raise _Gesperrt(13, "gesperrt")

    def pruefen():
        ablauf.append("pruefen")
        if ablauf.count("pruefen") == 2:
            raise RuntimeError("Datei hat sich veraendert")

    with pytest.raises(RuntimeError):
        pfade.geduldig(gesperrt, vor_wiederholung=pruefen)
    assert ablauf == ["versuch", "pruefen", "versuch", "pruefen"]


def test_geduld_hat_ein_ende_und_gilt_nur_fuer_sperren(monkeypatch):
    monkeypatch.setattr(pfade, "GEDULD_PAUSE", 0.001)
    aufrufe = []

    def immer_gesperrt():
        aufrufe.append(1)
        raise _Gesperrt(13, "gesperrt")

    with pytest.raises(PermissionError):
        pfade.geduldig(immer_gesperrt)
    assert len(aufrufe) == pfade.GEDULD_VERSUCHE
    aufrufe.clear()

    def keine_rechte():
        aufrufe.append(1)
        raise PermissionError(13, "keine Rechte")

    with pytest.raises(PermissionError):
        pfade.geduldig(keine_rechte)
    assert len(aufrufe) == 1


# --- Windows-Zweige, unter Linux mit nachgebautem kernel32 geprueft --------


class _Kernel32:
    """Antwortet auf MoveFileExW mit einer vorgegebenen Folge von Fehlernummern
    (0 = Erfolg); danach immer Erfolg."""

    def __init__(self, folge):
        self.folge = list(folge)
        self.aufrufe: list = []
        self.letzter = 0
        aussen = self

        class _Funktion:
            argtypes = restype = None

            def __call__(self, von, nach, flaggen):
                aussen.aufrufe.append((von, nach, flaggen))
                nummer = aussen.folge.pop(0) if aussen.folge else 0
                aussen.letzter = nummer
                return 0 if nummer else 1

        self.MoveFileExW = _Funktion()


@pytest.fixture
def windows_umbenennen(monkeypatch):
    import ctypes

    pausen: list = []
    monkeypatch.setattr(pfade, "_IST_WINDOWS", True)
    monkeypatch.setattr(pfade.time, "sleep", pausen.append)

    def mit(folge):
        k = _Kernel32(folge)
        monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: k, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: k.letzter, raising=False)
        return k, pausen

    return mit


def test_windows_umbenennen_wartet_bei_sperre_und_ersetzt_nie(windows_umbenennen):
    k, pausen = windows_umbenennen([32, 33, 5])
    pfade.umbenennen_ohne_ueberschreiben(Path("/x/a.part"), Path("/x/a.jpg"))
    assert len(k.aufrufe) == 4 and len(pausen) == 3
    # Flagge 8 (auf die Platte schreiben), nie 1 (vorhandene Datei ersetzen).
    assert all(flaggen == 8 for _von, _nach, flaggen in k.aufrufe)


@pytest.mark.parametrize("nummer, fehler", [(80, FileExistsError), (183, FileExistsError),
                                            (2, FileNotFoundError), (3, FileNotFoundError)])
def test_windows_umbenennen_fehlernummern(windows_umbenennen, nummer, fehler):
    k, pausen = windows_umbenennen([nummer])
    with pytest.raises(fehler):
        pfade.umbenennen_ohne_ueberschreiben(Path("/x/a.part"), Path("/x/a.jpg"))
    assert len(k.aufrufe) == 1 and not pausen


def test_windows_umbenennen_gibt_nach_der_wartezeit_auf(windows_umbenennen):
    k, pausen = windows_umbenennen([5] * 50)
    with pytest.raises(OSError):
        pfade.umbenennen_ohne_ueberschreiben(Path("/x/a.part"), Path("/x/a.jpg"))
    assert len(k.aufrufe) == pfade.GEDULD_VERSUCHE and 14.0 <= sum(pausen) <= 20.0


def test_schreibschutz_wird_am_windows_attribut_erkannt(tmp_path, monkeypatch):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")

    class _Stat:
        def __init__(self, attribute):
            self.st_file_attributes = attribute

    monkeypatch.setattr(pfade.sys, "platform", "win32")
    monkeypatch.setattr(pfade.os, "stat", lambda pfad, follow_symlinks=True: _Stat(0x1 | 0x20))
    assert pfade._schreibgeschuetzt(p) is True
    monkeypatch.setattr(pfade.os, "stat", lambda pfad, follow_symlinks=True: _Stat(0x20))
    assert pfade._schreibgeschuetzt(p) is False

    def weg(pfad, follow_symlinks=True):
        raise FileNotFoundError(2, "weg")

    monkeypatch.setattr(pfade.os, "stat", weg)
    assert pfade._schreibgeschuetzt(p) is False
    monkeypatch.setattr(pfade.sys, "platform", "linux")
    assert pfade._schreibgeschuetzt(p) is False
