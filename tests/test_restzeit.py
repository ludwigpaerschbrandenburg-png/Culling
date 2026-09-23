"""Restzeit (restzeit.py) nach dem Test von v0.5: erst nach 60 s und 3 %,
gleitender Durchschnitt der letzten 60 s, hoechstens alle 5 s neu, abgerundet.
Alles mit einer kuenstlichen Uhr - kein Test wartet wirklich."""

from __future__ import annotations

import pytest

from fotosort import meldungen, restzeit, steuerung
from fotosort.restzeit import GESCHAETZT, UNBEKANNT, WIRD_BERECHNET, Restzeit


class Uhr:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _lauf(r: Restzeit, uhr: Uhr, bis: float, tempo: float, erledigt: float, gesamt: float, schritt: float = 0.5):
    """Von jetzt bis 'bis' Sekunden (aktive Zeit seit Beginn) mit festem Tempo melden."""
    ergebnis = None
    start = uhr.t
    while uhr.t - start < bis - 1e-9:
        uhr.t += schritt
        erledigt += tempo * schritt
        ergebnis = r.melden(erledigt, gesamt)
    return erledigt, ergebnis


def test_abrunden():
    assert restzeit.abrunden(11.7 * 60) == 11 * 60           # ganze Minuten
    assert restzeit.abrunden(2 * 60 + 59) == 2 * 60
    assert restzeit.abrunden(119) == 110                      # unter 2 min: 10-s-Schritte
    assert restzeit.abrunden(107) == 100
    assert restzeit.abrunden(9.9) == 0
    assert restzeit.abrunden(-5) == 0


def test_texte():
    assert meldungen.restzeit_kurz(660) == "11 min"
    assert meldungen.restzeit_kurz(100) == "1 min 40 s"
    assert meldungen.restzeit_kurz(60) == "1 min"
    assert meldungen.restzeit_kurz(50) == "50 s"
    assert meldungen.restzeit_kurz(0) == "unter 10 s"
    assert meldungen.restzeit_kurz(2 * 3600 + 5 * 60) == "2 h 5 min"
    assert meldungen.ob_restzeit(None, WIRD_BERECHNET) == "wird berechnet"
    assert meldungen.ob_restzeit(660, GESCHAETZT) == "11 min"
    assert meldungen.ob_restzeit(None, UNBEKANNT) == ""
    assert meldungen.restzeit(None, WIRD_BERECHNET) == "Restzeit wird berechnet"
    assert meldungen.restzeit(660, GESCHAETZT) == "noch etwa 11 min"


def test_in_der_ersten_minute_nur_wird_berechnet():
    uhr = Uhr()
    r = Restzeit(uhr)
    assert r.melden(0, 6000) == (None, WIRD_BERECHNET)          # hier beginnt die Minute
    # Die Haelfte ist nach 30 s geschafft - trotzdem noch keine Zahl.
    erledigt, (wert, zustand) = _lauf(r, uhr, 59.5, tempo=50, erledigt=0, gesamt=6000)
    assert (wert, zustand) == (None, WIRD_BERECHNET) and erledigt > 0.03 * 6000
    uhr.t += 0.5                                                 # genau 60 s
    wert, zustand = r.melden(erledigt + 25, 6000)
    assert zustand == GESCHAETZT and wert == restzeit.abrunden((6000 - erledigt - 25) / 50)


def test_unter_drei_prozent_nur_wird_berechnet():
    uhr = Uhr()
    r = Restzeit(uhr)
    # 2 Minuten, aber erst 2 % geschafft.
    erledigt, ergebnis = _lauf(r, uhr, 120, tempo=0.2, erledigt=0, gesamt=1200)
    assert ergebnis == (None, WIRD_BERECHNET) and erledigt < 0.03 * 1200
    erledigt, (wert, zustand) = _lauf(r, uhr, 60, tempo=0.2, erledigt=erledigt, gesamt=1200)
    assert zustand == GESCHAETZT and erledigt >= 0.03 * 1200


def test_schneller_anfang_zaehlt_nach_einer_minute_nicht_mehr():
    """Der Fall aus dem Test: Die ersten Sekunden kommen aus dem
    Zwischenspeicher (schnell), dann liest die Platte (langsam)."""
    uhr = Uhr()
    r = Restzeit(uhr)
    gesamt = 100_000.0
    erledigt, _ = _lauf(r, uhr, 10, tempo=1000, erledigt=0, gesamt=gesamt)      # Zwischenspeicher
    erledigt, _ = _lauf(r, uhr, 130, tempo=50, erledigt=erledigt, gesamt=gesamt)  # Platte
    wert, zustand = r.melden(erledigt, gesamt)
    assert zustand == GESCHAETZT
    # Die letzten 60 s liefen mit 50/s: das und nur das zaehlt.
    erwartet = restzeit.abrunden((gesamt - erledigt) / 50)
    assert abs(wert - erwartet) <= 60
    # Der alte Durchschnitt seit dem Start haette viel weniger geschaetzt.
    alt = (gesamt - erledigt) / (erledigt / 140)
    assert wert > alt * 1.3


def test_hoechstens_alle_fuenf_sekunden_neu():
    uhr = Uhr()
    r = Restzeit(uhr)
    gesamt = 100_000.0
    erledigt, (erste, _) = _lauf(r, uhr, 70, tempo=100, erledigt=0, gesamt=gesamt)
    werte = []
    for _ in range(9):                       # 4,5 s lang ploetzlich zehnmal langsamer
        uhr.t += 0.5
        erledigt += 5
        werte.append(r.melden(erledigt, gesamt)[0])
    assert set(werte) == {erste}             # steht still bis zum naechsten 5-s-Takt
    uhr.t += 1.0
    erledigt += 10
    assert r.melden(erledigt, gesamt)[0] != erste


def test_pause_zaehlt_nicht_mit():
    uhr = Uhr()
    r = Restzeit(uhr)
    gesamt = 100_000.0
    erledigt, (vorher, _) = _lauf(r, uhr, 90, tempo=100, erledigt=0, gesamt=gesamt)
    r.pause()
    for _ in range(300):                     # 10 Minuten Pause, Herzschlag meldet weiter
        uhr.t += 2
        assert r.melden(erledigt, gesamt) == (vorher, GESCHAETZT)
    r.weiter()
    erledigt, (nachher, zustand) = _lauf(r, uhr, 6, tempo=100, erledigt=erledigt, gesamt=gesamt)
    # Gleiches Tempo wie vor der Pause: die Schaetzung sinkt nur um die geschaffte Menge.
    assert zustand == GESCHAETZT and nachher <= vorher and vorher - nachher <= 60


def test_stillstand_behaelt_die_letzte_zahl_und_unbekannte_menge():
    uhr = Uhr()
    r = Restzeit(uhr)
    gesamt = 100_000.0
    erledigt, (wert, _) = _lauf(r, uhr, 80, tempo=100, erledigt=0, gesamt=gesamt)
    for _ in range(100):                     # eine riesige Datei: 100 s ohne Fortschritt
        uhr.t += 1
        assert r.melden(erledigt, gesamt)[1] == GESCHAETZT
    assert r.melden(erledigt, gesamt)[0] is not None
    assert Restzeit(uhr).melden(5, 0) == (None, UNBEKANNT)     # Scan: Gesamtmenge unbekannt


def test_uhr_beginnt_mit_der_ersten_meldung():
    """Vorbereitung (Datenbank oeffnen, Plan bilden) zaehlt nicht zur Minute."""
    uhr = Uhr()
    r = Restzeit(uhr)
    uhr.t += 300                              # fuenf Minuten Vorbereitung
    assert r.melden(10, 1000) == (None, WIRD_BERECHNET)
    uhr.t += 30
    assert r.melden(500, 1000) == (None, WIRD_BERECHNET)


def test_statusdatei_der_oberflaeche(tmp_path, monkeypatch):
    """Der Arbeitsprozess schreibt Restzeit und ihren Zustand in die Statusdatei;
    die Oberflaeche macht daraus "wird berechnet" bzw. "11 min"."""
    monkeypatch.setattr(steuerung, "SCHREIB_ABSTAND", 0.0)
    uhr = Uhr()
    st = steuerung.Steuerung(tmp_path / "status.json", tmp_path / "steuer.json", "kopieren")
    st.restzeit = Restzeit(uhr)
    st.melden(5, 100, 500, 100_000)
    d = steuerung.json_lesen(tmp_path / "status.json")
    assert d["restzeit_s"] is None and d["restzeit_zustand"] == WIRD_BERECHNET
    for i in range(140):
        uhr.t += 0.5
        st.melden(5 + i, 100, 500 + 100 * i, 100_000)
    d = steuerung.json_lesen(tmp_path / "status.json")
    assert d["restzeit_zustand"] == GESCHAETZT and d["restzeit_s"] % 60 == 0
    assert meldungen.ob_restzeit(d["restzeit_s"], d["restzeit_zustand"]).endswith("min")
    # Ohne Gesamtmenge (Scan): keine Restzeit, auch kein "wird berechnet".
    scan = steuerung.Steuerung(tmp_path / "s2.json", tmp_path / "st2.json", "scan")
    scan.melden(50, 0, 1000, 0)
    d = steuerung.json_lesen(tmp_path / "s2.json")
    assert d["restzeit_s"] is None and d["restzeit_zustand"] == UNBEKANNT


@pytest.mark.parametrize("zustand,erwartet", [(WIRD_BERECHNET, "wird berechnet"), (GESCHAETZT, "12 min"), (UNBEKANNT, "")])
def test_anzeige_im_fenster(tmp_path, zustand, erwartet):
    from fotosort.oberflaeche import ablauf as ablauf_modul
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    steuerung.json_schreiben(ab.status_datei, {
        "schritt": "kopieren", "zustand": "fertig", "pid": 0, "dateien": 3, "gesamt": 10, "bytes": 30,
        "gesamt_bytes": 100, "restzeit_s": 720 if zustand == GESCHAETZT else None, "restzeit_zustand": zustand,
    })
    assert ab.lauf_status()["text"]["restzeit"] == erwartet
