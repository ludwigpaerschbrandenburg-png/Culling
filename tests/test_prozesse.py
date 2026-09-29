"""Hilfsprozesse ohne Konsolenfenster (Teil 2 nach dem ersten echten Testlauf).

Im ersten Lauf unter Windows oeffnete jeder ExifTool-Prozess ein schwarzes
Fenster. Jeder Start eines Hilfsprogramms bekommt deshalb die Argumente aus
prozesse.unsichtbar(); der Arbeitsprozess der Oberflaeche die aus
prozesse.losgeloest(). Unter Windows werden die echten Flaggen geprueft, auf
anderen Systemen, dass die Argumente wirklich bis zu Popen/run durchkommen.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import testbaum
from fotosort import cli, metadaten, prozesse
from fotosort.oberflaeche import ablauf

WINDOWS = sys.platform.startswith("win")


@pytest.mark.skipif(not WINDOWS, reason="Flaggen gibt es nur unter Windows")
def test_unter_windows_kein_fenster():
    u = prozesse.unsichtbar()
    assert u["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert u["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert u["startupinfo"].wShowWindow == subprocess.SW_HIDE
    l = prozesse.losgeloest()
    assert l["creationflags"] & subprocess.DETACHED_PROCESS
    assert l["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert l["startupinfo"].wShowWindow == subprocess.SW_HIDE


@pytest.mark.skipif(WINDOWS, reason="auf anderen Systemen gibt es nichts zu verstecken")
def test_ausserhalb_von_windows_nichts_zu_verstecken():
    assert prozesse.unsichtbar() == {}
    assert prozesse.losgeloest() == {"start_new_session": True}
    assert ablauf._losgeloest() == {"start_new_session": True}


def _mitschreiben(monkeypatch, modul, name: str) -> list[dict]:
    """Popen bzw. run des Moduls so umhuellen, dass die Argumente sichtbar werden."""
    aufrufe: list[dict] = []
    echt = getattr(subprocess, name)

    def umhuellt(*a, **kw):
        aufrufe.append(dict(kw))
        return echt(*a, **kw)

    monkeypatch.setattr(modul.subprocess, name, umhuellt)
    return aufrufe


def test_exiftool_prozess_bekommt_die_argumente(monkeypatch):
    # Ein harmloser Marker statt der Windows-Flaggen: creationflags=0 und
    # startupinfo=None nimmt Popen auf jedem System an.
    monkeypatch.setattr(prozesse, "unsichtbar", lambda: {"creationflags": 0, "startupinfo": None})
    aufrufe = _mitschreiben(monkeypatch, metadaten, "Popen")
    p = metadaten._Prozess(testbaum.exiftool_pfad())
    try:
        assert aufrufe and "creationflags" in aufrufe[0] and "startupinfo" in aufrufe[0]
    finally:
        p.beenden()


def test_exiftool_pruefung_bekommt_die_argumente(monkeypatch):
    monkeypatch.setattr(prozesse, "unsichtbar", lambda: {"creationflags": 0, "startupinfo": None})
    monkeypatch.setattr(cli, "_exiftool_startbar_gemerkt", set())   # ein frueherer Test hat schon gestartet
    aufrufe = _mitschreiben(monkeypatch, cli, "run")
    assert cli.exiftool_startbar(testbaum.exiftool_pfad()) is True
    assert aufrufe and "creationflags" in aufrufe[0] and "startupinfo" in aufrufe[0]


def test_arbeitsprozess_bekommt_die_argumente(monkeypatch, tmp_path):
    monkeypatch.setattr(prozesse, "losgeloest", lambda: {"start_new_session": True, "creationflags": 0})
    aufrufe = _mitschreiben(monkeypatch, ablauf, "Popen")
    ab = ablauf.Ablauf(ordner=tmp_path / "ob")
    ab.ziel_setzen(str(tmp_path / "Ziel"))
    a = ab.schritt_starten("scan", quellen=[], ziel_anlegen=False)
    assert a["gestartet"] == "scan"
    assert aufrufe and aufrufe[0]["creationflags"] == 0 and aufrufe[0]["start_new_session"] is True
    ablauf.prozess_beenden(a["pid"])


def test_startzeit_erkennt_wiederverwendete_prozessnummer():
    import os
    import subprocess
    import sys
    import time

    from fotosort import prozesse
    from fotosort.oberflaeche import ablauf as ablauf_modul

    eigene = prozesse.startzeit(os.getpid())
    if eigene is None:
        import pytest
        pytest.skip("Startzeit auf diesem System nicht feststellbar")
    time.sleep(0.05)
    kind = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        start = prozesse.startzeit(kind.pid)
        assert start is not None and start >= eigene
        assert ablauf_modul.pid_lebt(kind.pid, start) is True
        # Dieselbe Nummer, aber ein anderer (frueherer) Prozess: nicht unserer.
        assert ablauf_modul.pid_lebt(kind.pid, start - 600) is False
        assert ablauf_modul.pid_lebt(kind.pid) is True      # ohne Startzeit wie bisher
    finally:
        kind.kill()
        kind.wait()


_HAENGT_MIT_KIND = """
import signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)   # wie ein Prozess, der in einem Netzlaufwerk feststeckt
kind = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(kind.pid, flush=True)
time.sleep(120)
"""


@pytest.mark.skipif(WINDOWS, reason="Prozessgruppen gibt es so nur unter Linux/macOS")
def test_sofort_beenden_nimmt_haengenden_prozess_samt_kindern(tmp_path):
    """"Sofort beenden" bittet erst (SIGTERM an die ganze Gruppe, also auch an
    ExifTool) und fasst nach kurzer Zeit hart nach. Frueher blieb ein haengender
    Arbeitsprozess stehen, und seine ExifTool-Prozesse liefen ohne Eltern weiter."""
    import os
    import time

    p = subprocess.Popen([sys.executable, "-c", _HAENGT_MIT_KIND], stdout=subprocess.PIPE,
                         **prozesse.losgeloest())
    kind = int(p.stdout.readline())
    try:
        start = prozesse.startzeit(p.pid)
        ablauf.prozess_beenden(p.pid, start, nachsetzen=0.5)
        p.wait(timeout=15)
        ende = time.monotonic() + 15
        while ablauf.pid_lebt(kind) and time.monotonic() < ende:
            time.sleep(0.1)
        assert not ablauf.pid_lebt(kind)
    finally:
        for pid in (p.pid, kind):
            try:
                os.kill(pid, 9)
            except OSError:
                pass


@pytest.mark.skipif(WINDOWS, reason="Prozessgruppen gibt es so nur unter Linux/macOS")
def test_sofort_beenden_trifft_nie_die_eigene_gruppe():
    """Ein Prozess ohne eigene Gruppe (nicht losgeloest gestartet) wird allein
    beendet - nie die Gruppe, in der auch das Fenster selbst laeuft."""
    import os

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert os.getpgid(p.pid) == os.getpgid(0)
        ablauf.prozess_beenden(p.pid, prozesse.startzeit(p.pid), nachsetzen=0.2)
        p.wait(timeout=15)
    finally:
        p.kill()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc gibt es nur unter Linux")
def test_startzeit_haengt_nicht_an_der_uhr(monkeypatch):
    """Unter Linux rechnete die Startzeit mit der Bootzeit aus /proc/stat, und
    die verschiebt sich bei jedem Stellen der Uhr (Zeitabgleich nach dem
    Aufwachen): Danach hielt ein neu geoeffnetes Fenster den eigenen, lebenden
    Arbeitsprozess fuer abgestuerzt, und "Sofort beenden" griff nicht mehr."""
    import builtins
    import io
    import os

    vorher = prozesse.startzeit(os.getpid())
    echt = builtins.open

    def uhr_gestellt(pfad, *a, **k):
        if str(pfad) == "/proc/stat":
            with echt(pfad, "rb") as f:
                zeilen = f.read().split(b"\n")
            return io.BytesIO(b"\n".join(
                b"btime %d" % (int(z.split()[1]) + 5) if z.startswith(b"btime ") else z for z in zeilen))
        return echt(pfad, *a, **k)

    monkeypatch.setattr(builtins, "open", uhr_gestellt)
    assert prozesse.startzeit(os.getpid()) == vorher
    assert ablauf.pid_lebt(os.getpid(), vorher)


def test_baum_nimmt_nur_echte_nachkommen():
    """Windows merkt sich den Elternprozess nur als Nummer und vergibt Nummern
    neu. Das Fenster, dessen laengst beendeter Starter (start.bat) zufaellig
    dieselbe Nummer hatte wie jetzt der Arbeitsprozess, ist nicht dessen Kind:
    Es entstand VOR ihm. taskkill /T haette es mitbeendet - "Sofort beenden"
    darf nur den Arbeitsprozess und seine ExifTool-Prozesse treffen."""
    eintraege = [            # (Nummer, Eltern-Nummer, erstellt)
        (100, 4, 50.0),      # Arbeitsprozess
        (200, 100, 10.0),    # Fenster: Eltern-Nummer 100 gehoerte seinem alten Starter
        (300, 100, 60.0),    # exiftool.exe, Kind des Arbeitsprozesses
        (400, 300, 61.0),    # perl.exe, Enkel
        (500, 200, 70.0),    # Kind des Fensters
        (600, 100, None),    # Startzeit nicht lesbar: nicht anfassen
        (700, 700, 80.0),    # zeigt auf sich selbst
    ]
    assert sorted(prozesse._nachkommen(eintraege, 100, 50.0)) == [300, 400]
    assert prozesse._nachkommen(eintraege, 999, None) == []


_MIT_KIND = """
import subprocess, sys, time
kind = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(kind.pid, flush=True)
time.sleep(120)
"""


@pytest.mark.skipif(not WINDOWS, reason="der eigene Prozessbaum wird nur unter Windows gebraucht")
def test_windows_baum_beenden_nimmt_die_kinder_mit():
    """exiftool.exe startet perl.exe: Beendet wird der ganze Baum, ohne taskkill."""
    import time

    p = subprocess.Popen([sys.executable, "-c", _MIT_KIND], stdout=subprocess.PIPE)
    kind = int(p.stdout.readline())
    try:
        prozesse.baum_beenden_pid(p.pid)
        p.wait(timeout=15)
        ende = time.monotonic() + 15
        while ablauf.pid_lebt(kind) and time.monotonic() < ende:
            time.sleep(0.1)
        assert not ablauf.pid_lebt(kind)
    finally:
        p.kill()
        subprocess.run(["taskkill", "/F", "/PID", str(kind)], capture_output=True, check=False)
