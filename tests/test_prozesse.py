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
