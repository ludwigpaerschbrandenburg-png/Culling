"""BLAKE3 und Kopieren mit Hash (SPEC Abschnitt 5 und 7)."""

from __future__ import annotations

import threading

import blake3
import pytest

from fotosort import hashes


def test_blake3_datei_stimmt_mit_bibliothek_ueberein(tmp_path):
    p = tmp_path / "a.bin"
    inhalt = bytes(range(256)) * 5000  # groesser als ein Block
    p.write_bytes(inhalt)
    assert hashes.blake3_datei(p) == blake3.blake3(inhalt).hexdigest()


def test_kopieren_mit_hash_liefert_hash_der_quelle_und_gleichen_inhalt(tmp_path):
    q = tmp_path / "q.bin"
    inhalt = b"x" * (hashes.BLOCK * 2 + 17)
    q.write_bytes(inhalt)
    z = tmp_path / "z.bin"
    h, n = hashes.kopieren_mit_hash(q, z)
    assert n == len(inhalt)
    assert z.read_bytes() == inhalt
    assert h == blake3.blake3(inhalt).hexdigest() == hashes.blake3_datei(z)


def test_kopieren_mit_hash_ueberschreibt_nie(tmp_path):
    """Die Zieldatei wird exklusiv angelegt: belegt heisst Fehler, nicht Ersetzen."""
    q = tmp_path / "q.bin"
    q.write_bytes(b"neu")
    z = tmp_path / "z.bin"
    z.write_bytes(b"schon da")
    with pytest.raises(FileExistsError):
        hashes.kopieren_mit_hash(q, z)
    assert z.read_bytes() == b"schon da"


def test_kopieren_mit_hash_raeumt_bei_abbruch_auf(tmp_path):
    q = tmp_path / "q.bin"
    q.write_bytes(b"y" * (hashes.BLOCK * 3))
    z = tmp_path / "z.bin"
    stop = threading.Event()
    stop.set()
    with pytest.raises(hashes.Abgebrochen):
        hashes.kopieren_mit_hash(q, z, stop)
    assert not z.exists()
    assert q.read_bytes() == b"y" * (hashes.BLOCK * 3)


def test_kopieren_mit_hash_raeumt_bei_lesefehler_auf(tmp_path):
    z = tmp_path / "z.bin"
    with pytest.raises(FileNotFoundError):
        hashes.kopieren_mit_hash(tmp_path / "gibtsnicht", z)
    assert not z.exists()


def test_gleich_byteweise(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    a.write_bytes(b"abc" * 1000)
    b.write_bytes(b"abc" * 1000)
    c.write_bytes(b"abc" * 999 + b"abd")
    assert hashes.gleich_byteweise(a, b)
    assert not hashes.gleich_byteweise(a, c)
