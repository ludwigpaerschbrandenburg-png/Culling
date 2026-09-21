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
