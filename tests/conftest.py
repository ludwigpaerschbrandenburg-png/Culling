"""Gemeinsame Vorrichtungen fuer alle Tests.

Nie mit echten Fotos testen - ausschliesslich der kuenstliche Testbaum
aus SPEC Abschnitt 11.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

import testbaum
from fotosort import config, db


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch, tmp_path):
    """Keine Umgebungsvariable des Entwicklungsrechners faellt in die Tests.

    Der Archiv-Ordner landet unter tmp_path, nie im echten Benutzerprofil.
    """
    basis = tmp_path / "archive"
    monkeypatch.setenv("FOTOSORT_DATENBANK", str(basis))
    monkeypatch.delenv("FOTOSORT_ZIEL", raising=False)
    monkeypatch.delenv("FOTOSORT_EXIFTOOL", raising=False)
    return basis


@pytest.fixture
def archiv_basis(saubere_umgebung) -> Path:
    return saubere_umgebung


@pytest.fixture
def konf() -> config.Konfiguration:
    """Konfiguration mit reinen Standardwerten."""
    return config.Konfiguration()


@pytest.fixture
def baum(tmp_path) -> dict[str, Path]:
    """Der kuenstliche Testbaum, frisch je Test."""
    return testbaum.erzeugen(tmp_path / "baum")


@pytest.fixture
def quelle(baum) -> Path:
    return baum["quelle"]


@pytest.fixture
def ziel(tmp_path) -> Path:
    ordner = tmp_path / "Ziel"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


@contextlib.contextmanager
def datenbank_von(ziel: Path, archiv_basis: Path):
    """Die Datenbank eines Ziels zum Nachschauen oeffnen."""
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    datenbank = db.Datenbank.oeffnen(archiv_basis / kennung)
    try:
        yield datenbank
    finally:
        datenbank.schliessen()


@pytest.fixture
def nachschauen(archiv_basis):
    def oeffnen(ziel: Path):
        return datenbank_von(ziel, archiv_basis)

    return oeffnen
