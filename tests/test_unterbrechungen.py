"""Unterbrechungen ueber die Oberflaeche (Nacht-Auftrag Teil 3).

Abbrechen, Fenster schliessen, neu oeffnen, Weitermachen, Pause, "Sofort
beenden" und ein harter Abschuss des Arbeitsprozesses mitten im Kopieren -
in jeder Kombination. Massstab ist ein ungestoerter Referenzlauf auf
dieselbe Quelle: Am Ende muss das Ziel Datei fuer Datei gleich aussehen
(nichts doppelt, nichts verloren, keine .part-Reste), die Datenbank dieselben
Zaehler haben und die Anzeige der Oberflaeche den Stand richtig nennen.

"Fenster schliessen und neu oeffnen" heisst hier: das Ablauf-Objekt wird
weggeworfen und ein neues auf denselben Ordner der Oberflaeche gebaut - genau
das tut ein neues Fenster.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

import testbaum
from fotosort import cli, db
from fotosort.oberflaeche import ablauf as ablauf_modul

ENDE = {"fertig", "abgebrochen", "fehler", "abgestuerzt"}
VIELE = 2000
FUELLUNG = 20 * 1024     # Bytes je Datei hinter dem JPEG-Ende: eindeutig und nicht winzig


@pytest.fixture(scope="module")
def grosse_quelle(tmp_path_factory) -> Path:
    """Der Testbaum plus VIELE eindeutige JPEGs, damit Kopieren lang genug
    dauert, um mittendrin zu unterbrechen. Wird von allen Tests nur gelesen."""
    baum = testbaum.erzeugen(tmp_path_factory.mktemp("baum"))
    bild = baum["jpg"].read_bytes()
    ordner = baum["quelle"] / "Viele"
    ordner.mkdir()
    for i in range(VIELE):
        # Nach dem JPEG-Ende angehaengte Bytes aendern den Fingerabdruck,
        # nicht die Metadaten: jede Datei ist ein eigenes Bild.
        (ordner / f"DSC{i:05d}.JPG").write_bytes(bild + b"\n" + (str(i).encode() + b" ") * (FUELLUNG // 6))
    return baum["quelle"]


def _zielbaum(ziel: Path) -> list[tuple[str, int]]:
    return sorted(
        (p.relative_to(ziel).as_posix(), p.stat().st_size)
        for p in ziel.rglob("*") if p.is_file() and ".fotosortierer" not in p.parts
    )


@pytest.fixture(scope="module")
def referenz(grosse_quelle, tmp_path_factory) -> tuple[list[tuple[str, int]], dict[str, int]]:
    """Ungestoerter Lauf ueber die Befehle: Zielbaum und Zaehler je Status."""
    ziel = tmp_path_factory.mktemp("referenz") / "Ziel"
    ziel.mkdir()
    basis = tmp_path_factory.mktemp("referenz_db")
    alt = os.environ.get("FOTOSORT_DATENBANK")
    os.environ["FOTOSORT_DATENBANK"] = str(basis)
    try:
        assert cli.main(["scan", "--quelle", str(grosse_quelle), "--ziel", str(ziel)]) == cli.OK
        assert cli.main(["analyse", "--ziel", str(ziel)]) in (cli.OK, cli.FEHLER)
        assert cli.main(["kopieren", "--ziel", str(ziel)]) in (cli.OK, cli.FEHLER)
        kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
        d = db.Datenbank.oeffnen(basis / kennung)
        try:
            zaehler = d.zaehler_je_status()
        finally:
            d.schliessen()
    finally:
        if alt is None:
            os.environ.pop("FOTOSORT_DATENBANK", None)
        else:
            os.environ["FOTOSORT_DATENBANK"] = alt
    baum = _zielbaum(ziel)
    assert len(baum) > VIELE and not any(n.endswith(".part") for n, _ in baum)
    return baum, zaehler


def _neu(tmp_path: Path, ziel: Path | None = None) -> ablauf_modul.Ablauf:
    """Ein 'neues Fenster': frisches Ablauf-Objekt auf denselben Ordner."""
    return ablauf_modul.Ablauf(ziel=str(ziel) if ziel else None, ordner=tmp_path / "oberflaeche")


def _bis_ende(ab: ablauf_modul.Ablauf, sekunden: float = 240.0) -> dict:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        l = ab.lauf_status()
        if l["zustand"] in ENDE:
            return l
        time.sleep(0.05)
    raise AssertionError("Schritt nicht zu Ende: " + str(ab.lauf_status()))


def _bis(bedingung, sekunden: float = 120.0, abstand: float = 0.005) -> None:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return
        time.sleep(abstand)
    raise AssertionError("Bedingung nicht eingetreten")


def _kopierte(ziel: Path) -> int:
    return sum(1 for p in ziel.rglob("*.JPG") if p.is_file())


def _vorbereitet(tmp_path: Path, quelle: Path, ziel: Path) -> ablauf_modul.Ablauf:
    """Scan und Analyse sind durch; der naechste Schritt ist Kopieren."""
    ab = _neu(tmp_path, ziel)
    ab.quelle_hinzufuegen(str(quelle))
    assert ab.los()["gestartet"] == "scan"
    assert _bis_ende(ab)["zustand"] == "fertig"
    assert ab.schritt("analyse")["gestartet"] == "analyse"
    assert _bis_ende(ab)["zustand"] == "fertig"
    assert ab.naechster()["schritt"] == "kopieren"
    return ab


def _pruefen_gleich(ab: ablauf_modul.Ablauf, ziel: Path, referenz, nachschauen) -> None:
    baum, zaehler = referenz
    assert _zielbaum(ziel) == baum
    assert not list(ziel.rglob("*.part"))
    with nachschauen(ziel) as d:
        assert d.zaehler_je_status() == zaehler
        # Kein Zielpfad zweimal, kein Anspruch offen.
        doppelt = d.verbindung.execute(
            "SELECT zielpfad, COUNT(*) n FROM dateien WHERE zielpfad != '' AND status IN ('kopiert', 'geprueft')"
            " GROUP BY zielpfad HAVING n > 1").fetchall()
        assert not doppelt
        assert d.verbindung.execute("SELECT COUNT(*) n FROM dateien WHERE status = 'kopieren_laeuft'").fetchone()["n"] == 0
    assert ab.naechster()["schritt"] == "pruefen"
    z = ab.zustand()
    assert z["archiv"]["naechster"] == "pruefen" and z["lauf"]["zustand"] == "fertig" and z["lauf"]["schritt"] == "kopieren"


def _hart_beenden(pid: int) -> None:
    """Wie der Task-Manager: ohne Signalbehandlung, ohne Aufraeumen."""
    if sys.platform.startswith("win"):
        ablauf_modul.prozess_beenden(pid)
    else:
        os.kill(pid, signal.SIGKILL)


# --------------------------------------------------------------- Tests --


def test_abbrechen_fenster_zu_neu_oeffnen_weitermachen(tmp_path, grosse_quelle, ziel, referenz, nachschauen):
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    _bis(lambda: _kopierte(ziel) >= 100)
    ab.steuern("abbrechen")
    l = _bis_ende(ab)
    assert l["zustand"] == "abgebrochen" and l["schritt"] == "kopieren" and l["aktiv"] is False
    teilweise = _kopierte(ziel)
    assert 0 < teilweise < VIELE

    # Fenster zu, neu auf: Der Stand steht da, "Weitermachen" bietet Kopieren an.
    del ab
    ab = _neu(tmp_path)
    z = ab.zustand()
    assert z["ziel"] == str(ziel) and z["lauf"]["zustand"] == "abgebrochen" and z["lauf"]["schritt"] == "kopieren"
    assert z["archiv"]["da"] and z["archiv"]["naechster"] == "kopieren"
    n = ab.naechster()
    assert n["schritt"] == "kopieren" and 0 < n["n"] < VIELE + 20
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    assert _bis_ende(ab)["zustand"] == "fertig"
    _pruefen_gleich(ab, ziel, referenz, nachschauen)


def test_harter_abschuss_mitten_im_kopieren(tmp_path, grosse_quelle, ziel, referenz, nachschauen):
    """Task-Manager, Stromausfall: dreimal an verschiedenen Stellen abgeschossen,
    jedes Mal neu geoeffnet und weitergemacht."""
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    for schwelle in (10, 300, 900):
        assert ab.schritt("kopieren")["gestartet"] == "kopieren"
        pid = ab.lauf.pid
        _bis(lambda: _kopierte(ziel) >= schwelle, abstand=0.001)
        _hart_beenden(pid)
        l = _bis_ende(ab, 30)
        assert l["zustand"] == "abgestuerzt" and l["aktiv"] is False and l["log"], l
        # Neues Fenster sieht denselben Absturz und bietet Weitermachen an.
        del ab
        ab = _neu(tmp_path)
        z = ab.zustand()
        assert z["lauf"]["zustand"] == "abgestuerzt" and z["archiv"]["naechster"] == "kopieren"
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    assert _bis_ende(ab)["zustand"] == "fertig"
    _pruefen_gleich(ab, ziel, referenz, nachschauen)


def test_sofort_beenden_und_weitermachen(tmp_path, grosse_quelle, ziel, referenz, nachschauen):
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    _bis(lambda: _kopierte(ziel) >= 100)
    a = ab.steuern("sofort")
    assert a["ok"] and "beendet" in a["text"].lower() or a["ok"]
    l = _bis_ende(ab, 30)
    assert l["zustand"] in ("abgebrochen", "abgestuerzt") and l["aktiv"] is False
    ab = _neu(tmp_path)
    assert ab.zustand()["archiv"]["naechster"] == "kopieren"
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    assert _bis_ende(ab)["zustand"] == "fertig"
    _pruefen_gleich(ab, ziel, referenz, nachschauen)


def test_pause_fenster_zu_neu_oeffnen_fortsetzen(tmp_path, grosse_quelle, ziel, referenz, nachschauen):
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    _bis(lambda: _kopierte(ziel) >= 50)
    ab.steuern("pause")
    _bis(lambda: ab.lauf_status()["zustand"] == "pause", 30, 0.05)
    stand = _kopierte(ziel)
    time.sleep(1.0)
    assert _kopierte(ziel) <= stand + 1                     # in der Pause passiert nichts mehr
    del ab
    ab = _neu(tmp_path)                                     # neues Fenster uebernimmt den pausierten Lauf
    l = ab.lauf_status()
    assert l["zustand"] == "pause" and l["aktiv"] is True and l["schritt"] == "kopieren"
    ab.steuern("weiter")
    assert _bis_ende(ab)["zustand"] == "fertig"
    _pruefen_gleich(ab, ziel, referenz, nachschauen)


def test_fenster_zu_waehrend_scan_und_abbruch_in_der_analyse(tmp_path, grosse_quelle, ziel, referenz, nachschauen):
    ab = _neu(tmp_path, ziel)
    ab.quelle_hinzufuegen(str(grosse_quelle))
    assert ab.los()["gestartet"] == "scan"
    del ab                                                  # Fenster zu, waehrend der Scan laeuft
    ab = _neu(tmp_path)
    l = ab.lauf_status()
    assert l["schritt"] == "scan"
    assert _bis_ende(ab)["zustand"] == "fertig"
    assert ab.zustand()["archiv"]["naechster"] == "analyse"
    assert ab.schritt("analyse")["gestartet"] == "analyse"
    ab.steuern("abbrechen")                                 # sofort abbrechen
    l = _bis_ende(ab)
    assert l["zustand"] in ("abgebrochen", "fertig")
    ab = _neu(tmp_path)
    if l["zustand"] == "abgebrochen":
        assert ab.zustand()["archiv"]["naechster"] == "analyse"
        assert ab.schritt("analyse")["gestartet"] == "analyse"
        assert _bis_ende(ab)["zustand"] == "fertig"
    assert ab.naechster()["schritt"] == "kopieren"
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    assert _bis_ende(ab)["zustand"] == "fertig"
    _pruefen_gleich(ab, ziel, referenz, nachschauen)


def test_zweites_fenster_kann_nichts_doppelt_starten(tmp_path, grosse_quelle, ziel):
    ab = _vorbereitet(tmp_path, grosse_quelle, ziel)
    assert ab.schritt("kopieren")["gestartet"] == "kopieren"
    zweites = _neu(tmp_path)
    l = zweites.lauf_status()
    assert l["aktiv"] is True and l["schritt"] == "kopieren"
    from fotosort import FotosortFehler
    with pytest.raises(FotosortFehler):
        zweites.schritt("kopieren")
    with pytest.raises(FotosortFehler):
        zweites.los()
    with pytest.raises(FotosortFehler):
        zweites.archiv_verwerfen("verwerfen")
    assert _bis_ende(ab)["zustand"] == "fertig"
    assert zweites.lauf_status()["zustand"] == "fertig"
