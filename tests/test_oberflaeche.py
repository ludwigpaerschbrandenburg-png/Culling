"""Phase 7: die Oberflaeche (SPEC Abschnitt 8) - Schnittstelle, Arbeitsprozess,
Steuerung. Die Schritte laufen als echte eigene Prozesse am kuenstlichen
Testbaum; die Seite wird ueber dieselbe Schnittstelle befragt wie im Fenster.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import testbaum
from fotosort import cli, db, steuerung
from fotosort.oberflaeche import ablauf as ablauf_modul
from fotosort.oberflaeche import server as server_modul
from test_kopieren import _zeilen

ENDE = {"fertig", "abgebrochen", "fehler", "abgestuerzt"}


@pytest.fixture
def ob(tmp_path, monkeypatch):
    """Ablauf mit eigenem Ordner unter tmp_path, dazu der Client der Seite.
    Bericht und Einstellungen werden nie wirklich im System geoeffnet: Unter
    Windows ginge sonst Notepad auf, und eine CSV ohne zugeordnetes Programm
    haelt den Test mit einem "Oeffnen mit"-Dialog an."""
    geoeffnet: list = []
    monkeypatch.setattr(cli, "_editor_oeffnen", lambda pfad: geoeffnet.append(Path(pfad)) or False)
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "oberflaeche")
    ab.geoeffnet = geoeffnet
    client = TestClient(server_modul.app_bauen(ab))
    return ab, client


def _warten(client, sekunden: float = 240.0) -> dict:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        l = client.get("/api/lauf").json()
        if l["zustand"] in ENDE:
            return l
        time.sleep(0.2)
    raise AssertionError("der Schritt ist nicht zu Ende gekommen: " + json.dumps(client.get("/api/lauf").json()))


def _post(client, pfad: str, daten: dict | None = None):
    r = client.post(pfad, json=daten or {})
    assert r.status_code == 200, r.text
    return r.json()


def _fehler(client, pfad: str, daten: dict | None = None) -> str:
    r = client.post(pfad, json=daten or {})
    assert r.status_code == 400, r.text
    return r.json()["fehler"]


def _echte(zeilen: dict) -> dict:
    return {k: v for k, v in zeilen.items() if v["dateityp"] in ("foto", "raw", "video", "sidecar")}


# ------------------------------------------------------------ Startseite --


def test_zustand_liefert_alles_fuer_die_startseite(ob):
    ab, client = ob
    z = client.get("/api/zustand").json()
    assert z["version"] and z["ziel"] == "" and z["quellen_neu"] == []
    assert z["verschieben"] is False and z["profil"] == "hdd"
    assert [p["name"] for p in z["profile"]] == ["hdd", "ssd", "netzwerk"]
    assert all(p["text"] for p in z["profile"])
    assert z["archiv"] == {"da": False}
    assert z["lauf"]["aktiv"] is False
    assert set(z["schritte"]) == set(ablauf_modul.SCHRITTE)
    seite = client.get("/").text
    assert 'id="seite-start"' in seite and 'id="seite-haupt"' in seite and 'class="titlebar"' in seite
    assert 'class="statusleiste' in seite and 'class="phasen-liste"' in seite
    for name in ("app.js", "app.css", "styles.css", "fonts.css"):
        assert client.get("/static/" + name).status_code == 200, name
    css = client.get("/static/styles.css").text
    assert "@import" not in css and "https://" not in css      # nichts aus dem Internet
    assert "@font-face" in client.get("/static/fonts.css").text
    schrift = client.get("/static/fonts/Inter-latin.woff2")
    assert schrift.status_code == 200 and schrift.headers["content-type"].startswith("font/woff2")
    assert client.get("/static/fonts/gibt-es-nicht.woff2").status_code == 404
    assert client.get("/static/geheim.txt").status_code == 404


def test_ziel_und_einstellungen_werden_gemerkt(ob, tmp_path, ziel):
    ab, client = ob
    a = _post(client, "/api/ziel", {"ziel": str(ziel)})
    assert a["ziel"] == str(ziel) and a["archiv"] == {"da": False, "ziel_existiert": True}
    _post(client, "/api/einstellungen", {"verschieben": True, "profil": "ssd"})
    assert _fehler(client, "/api/einstellungen", {"profil": "turbo"})
    # Ein neues Fenster liest denselben Stand.
    neu = ablauf_modul.Ablauf(ordner=ab.ordner)
    assert neu.ziel == str(ziel) and neu.verschieben is True and neu.profil == "ssd"


def test_quelle_wird_geprueft_wie_im_gefuehrten_modus(ob, quelle, ziel, tmp_path):
    ab, client = ob
    _post(client, "/api/ziel", {"ziel": str(ziel)})
    assert "eintragen" in _fehler(client, "/api/quelle", {"pfad": "   "})
    assert _fehler(client, "/api/quelle", {"pfad": str(tmp_path / "gibt_es_nicht")})
    assert _fehler(client, "/api/quelle", {"pfad": str(ziel)})          # Quelle = Ziel
    unter = ziel / "unter"
    unter.mkdir()
    assert _fehler(client, "/api/quelle", {"pfad": str(unter)})         # Quelle im Ziel
    a = _post(client, "/api/quelle", {"pfad": str(quelle)})
    assert a["quellen_neu"] == [str(quelle)]
    assert "schon" in _fehler(client, "/api/quelle", {"pfad": str(quelle)}).lower()
    a = _post(client, "/api/quelle", {"pfad": str(quelle), "entfernen": True})
    assert a["quellen_neu"] == []


def test_los_verlangt_quelle_und_fragt_vor_dem_anlegen(ob, quelle, tmp_path):
    ab, client = ob
    assert "Ziel" in _fehler(client, "/api/los")            # kein Ziel
    neu = tmp_path / "NeuesZiel"
    _post(client, "/api/ziel", {"ziel": str(neu)})
    assert "Quellordner" in _fehler(client, "/api/los")
    _post(client, "/api/quelle", {"pfad": str(quelle)})
    a = _post(client, "/api/los")
    assert a["frage"] == "ziel_anlegen" and str(neu) in a["text"]
    assert not neu.exists()
    a = _post(client, "/api/los", {"ziel_anlegen": True})
    assert a["gestartet"] == "scan"
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    assert neu.is_dir() and db.archiv_id_vorhanden(neu)


def test_fremde_herkunft_wird_abgelehnt(ob):
    ab, client = ob
    r = client.post("/api/ziel", json={"ziel": "x"}, headers={"origin": "http://boese.example"})
    assert r.status_code == 403
    r = client.get("/api/zustand", headers={"origin": "http://testserver"})
    assert r.status_code == 200


# ------------------------------------------------------- der ganze Ablauf --


def test_ganzer_ablauf_ueber_die_oberflaeche(ob, quelle, ziel, nachschauen, archiv_basis):
    ab, client = ob
    _post(client, "/api/ziel", {"ziel": str(ziel)})
    _post(client, "/api/quelle", {"pfad": str(quelle)})
    assert _post(client, "/api/los")["gestartet"] == "scan"
    assert "läuft" in _fehler(client, "/api/los")            # nie zwei zugleich
    l = _warten(client)
    assert l["zustand"] == "fertig" and l["schritt"] == "scan" and l["aktiv"] is False
    assert l["dateien"] > 0
    zf = client.get("/api/zusammenfassung?schritt=scan").json()
    assert zf["name"] == "Quellen durchsuchen"
    assert zf["quellen"][0]["wurzel"] == str(quelle) and zf["quellen"][0]["foto"] > 0
    assert any("gefunden" in z[0] for z in zf["zeilen"])
    # Startseite kennt das Archiv jetzt: Quelle bekannt, naechster Schritt Analyse.
    z = client.get("/api/zustand").json()
    assert z["archiv"]["da"] and z["archiv"]["quellen"] == [str(quelle)] and z["archiv"]["naechster"] == "analyse"
    assert z["quellen_neu"] == []

    n = client.get("/api/naechster").json()
    assert n["schritt"] == "analyse" and "Analyse" in n["name"] and n["text"]
    assert _post(client, "/api/schritt", {"schritt": "analyse"})["gestartet"] == "analyse"
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    zf = client.get("/api/zusammenfassung?schritt=analyse").json()
    modelle = {m["modell"]: m for m in zf["modelle"]}
    assert "ILCE-7CM2" in modelle and modelle["ILCE-7CM2"]["ordner"] == "A7C2"   # Alias aus der Vorlage
    assert zf["je_jahr"]

    # Alias: Ordnername direkt aus der Tabelle - Analyse laeuft danach erneut.
    a = _post(client, "/api/aliase", {"aliase": {"ILCE-7CM2": "Sony A7C", "Unbekannt": ""}})
    assert a["gestartet"] == "analyse" and a["geaendert"] == 1 and a["zurueck"] > 0
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    kennung = db.archiv_id_datei(ziel).read_text(encoding="utf-8").strip()
    konf = tomllib.loads((archiv_basis / kennung / "config.toml").read_text(encoding="utf-8"))
    assert konf["kamera"]["aliase"]["ILCE-7CM2"] == "Sony A7C"
    zf = client.get("/api/zusammenfassung?schritt=analyse").json()
    assert {m["modell"]: m["ordner"] for m in zf["modelle"]}["ILCE-7CM2"] == "Sony A7C"
    assert _post(client, "/api/aliase", {"aliase": {"ILCE-7CM2": "Sony A7C"}}) == {"geaendert": 0, "text": "Es wurde kein Ordnername geändert."}

    n = client.get("/api/naechster").json()
    assert n["schritt"] == "kopieren" and n["n"] > 0 and n["wort"] == "" and n["verschieben"] is False
    assert _post(client, "/api/schritt", {"schritt": "kopieren"})["gestartet"] == "kopieren"
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    assert l["bytes"] > 0 and l["text"]["rate"].endswith("MB/s")
    zf = client.get("/api/zusammenfassung?schritt=kopieren").json()
    assert zf["duplikate"] > 0 and any(z[0].startswith("kopiert") for z in zf["zeilen"])
    assert any(p.is_dir() and p.name == "Sony A7C" for p in ziel.rglob("*"))

    n = client.get("/api/naechster").json()
    assert n["schritt"] == "pruefen" and n["n"] > 0
    assert _post(client, "/api/schritt", {"schritt": "pruefen"})["gestartet"] == "pruefen"
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    zf = client.get("/api/zusammenfassung?schritt=pruefen").json()
    assert zf["zaehler"]["geprueft"] > 0 and zf["zaehler"]["kopiert"] == 0

    # Listen: seitenweise, nie alles auf einmal.
    for art in ("fehler", "duplikate", "ohne_datum"):
        li = client.get(f"/api/liste?art={art}&seite=1").json()
        assert li["seiten"] >= 1 and len(li["zeilen"]) <= 100 and li["gesamt"] == len(li["zeilen"])
    li = client.get("/api/liste?art=duplikate&seite=99").json()
    assert li["seite"] == li["seiten"] and li["zeilen"][0]["partner"]
    assert client.get("/api/liste?art=alles&seite=1").status_code == 400

    # Aufraeumen: Plan je Quelle, Wort ist Pflicht, falsches Wort startet nichts.
    n = client.get("/api/naechster").json()
    assert n["schritt"] == "aufraeumen"
    plan = n["plan"]
    assert plan["n"] > 0 and plan["je_quelle"][0]["wurzel"] == str(quelle)
    assert plan["woerter"] == {"endgueltig": "loeschen", "papierkorb": "verschieben", "ordner": "entfernen"}
    assert "verschieben" in _fehler(client, "/api/schritt", {"schritt": "aufraeumen", "wort": "ja"})
    assert "loeschen" in _fehler(client, "/api/schritt", {"schritt": "aufraeumen", "weise": "endgueltig", "wort": "verschieben"})
    assert "nichts" in _fehler(client, "/api/schritt", {"schritt": "aufraeumen", "wort": ""}).lower()
    assert "entfernen" in _fehler(client, "/api/schritt", {"schritt": "aufraeumen", "wort": "", "leere_ordner": True, "wort_ordner": "ok"})
    vorher = _echte(_zeilen(nachschauen, ziel))
    assert all(Path(q).exists() for q in vorher)
    a = _post(client, "/api/schritt", {"schritt": "aufraeumen", "weise": "papierkorb", "wort": "verschieben"})
    assert a["gestartet"] == "aufraeumen"
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    nachher = _echte(_zeilen(nachschauen, ziel))
    assert {z["status"] for z in nachher.values()} <= {"quelle_geloescht"}
    assert all(not Path(q).exists() for q in nachher)
    assert any(p.is_dir() and p.name.startswith("_geloescht_") for p in quelle.iterdir())
    zf = client.get("/api/zusammenfassung?schritt=aufraeumen").json()
    assert any(z[0].startswith("quelle_geloescht") for z in zf["zeilen"])
    assert client.get("/api/naechster").json()["schritt"] == "fertig"

    # Bericht und Einstellungen per Knopf: neu schreiben, zuletzt geschriebenen oeffnen, CSV.
    b = _post(client, "/api/bericht")
    assert Path(b["pfad"]).is_file() and b["pfad"].endswith(".txt") and b["bericht"]["name"] == Path(b["pfad"]).name
    assert _post(client, "/api/bericht", {"art": "txt"})["pfad"] == b["pfad"]
    assert _post(client, "/api/bericht", {"art": "csv"})["pfad"].endswith("_dateien.csv")
    z = client.get("/api/zustand").json()
    assert z["archiv"]["bericht"]["name"] == b["bericht"]["name"] and z["archiv"]["lauf_nr"] >= 5 and z["archiv"]["sicherung"]
    e = _post(client, "/api/einstellungen_oeffnen")
    assert Path(e["pfad"]).name == "config.toml" and e["geoeffnet"] is False
    assert [p.name for p in ab.geoeffnet][-1] == "config.toml" and len(ab.geoeffnet) == 4   # 3x Bericht, 1x Einstellungen


def test_weitermachen_erkennt_angefangenes_archiv(ob, quelle, ziel, tmp_path):
    ab, client = ob
    _post(client, "/api/ziel", {"ziel": str(ziel)})
    _post(client, "/api/quelle", {"pfad": str(quelle)})
    _post(client, "/api/los")
    assert _warten(client)["zustand"] == "fertig"
    # Neues Fenster, anderer Ordner der Oberflaeche - nur das Ziel ist bekannt.
    neu = ablauf_modul.Ablauf(ziel=str(ziel), ordner=tmp_path / "anderes_fenster")
    client2 = TestClient(server_modul.app_bauen(neu))
    z = client2.get("/api/zustand").json()
    assert z["archiv"]["da"] and z["archiv"]["naechster"] == "analyse" and "Analyse" in z["archiv"]["phase"]
    n = client2.get("/api/naechster").json()
    assert n["schritt"] == "analyse"


def test_verschieben_verlangt_das_wort(ob, quelle, ziel, nachschauen):
    ab, client = ob
    _post(client, "/api/ziel", {"ziel": str(ziel)})
    _post(client, "/api/quelle", {"pfad": str(quelle)})
    _post(client, "/api/einstellungen", {"verschieben": True})
    _post(client, "/api/los")
    assert _warten(client)["zustand"] == "fertig"
    _post(client, "/api/schritt", {"schritt": "analyse"})
    assert _warten(client)["zustand"] == "fertig"
    n = client.get("/api/naechster").json()
    assert n["schritt"] == "kopieren" and n["verschieben"] is True and n["wort"] == "verschieben"
    assert "verschieben" in _fehler(client, "/api/schritt", {"schritt": "kopieren", "wort": ""})
    assert "verschieben" in _fehler(client, "/api/schritt", {"schritt": "kopieren", "wort": "kopieren"})
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert all(Path(q).exists() for q in zeilen)   # nichts passiert
    _post(client, "/api/schritt", {"schritt": "kopieren", "wort": " Verschieben "})
    l = _warten(client)
    assert l["zustand"] == "fertig", l
    assert l["schritt_name"] == "Verschieben ins Archiv"
    zeilen = _echte(_zeilen(nachschauen, ziel))
    assert "verschoben" in {z["status"] for z in zeilen.values()}


# ------------------------------------------------------------- Steuerung --


def test_steuerung_pause_und_abbruch(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    steuer = tmp_path / "steuer.json"
    monkeypatch.setattr(steuerung, "SCHREIB_ABSTAND", 0.0)
    st = steuerung.Steuerung(status, steuer, "scan")
    st.schreiben()
    assert steuerung.json_lesen(status)["zustand"] == "laeuft"
    st.melden(5, 10, 500, 1000)
    d = steuerung.json_lesen(status)
    assert d["dateien"] == 5 and d["gesamt"] == 10 and d["bytes"] == 500 and d["restzeit_s"] is not None

    # Pause: melden() haelt an, bis "weiter" kommt; der Stand sagt "pause".
    steuerung.wunsch_schreiben(steuer, pause=True)
    fertig = threading.Event()
    threading.Thread(target=lambda: (st.melden(6, 10, 600, 1000), fertig.set()), daemon=True).start()
    ende = time.monotonic() + 5
    while time.monotonic() < ende and steuerung.json_lesen(status)["zustand"] != "pause":
        time.sleep(0.05)
    assert steuerung.json_lesen(status)["zustand"] == "pause"
    assert not fertig.is_set()
    steuerung.wunsch_schreiben(steuer, pause=False)
    assert fertig.wait(5)
    assert steuerung.json_lesen(status)["zustand"] == "laeuft"

    # Abbruch: derselbe Weg wie Strg+C.
    steuerung.wunsch_schreiben(steuer, abbrechen=True)
    with pytest.raises(KeyboardInterrupt):
        st.melden(7, 10, 700, 1000)
    st.beenden(steuerung.ZUSTAND_ABGEBROCHEN, 130, "abgebrochen")
    d = steuerung.json_lesen(status)
    assert d["zustand"] == "abgebrochen" and d["rc"] == 130 and d["hinweis"] == "abgebrochen"

    # Ohne aktive Steuerung ist melden() ein Nichts.
    steuerung.AKTIV = None
    steuerung.melden(1, 1, 1, 1)


def test_arbeit_abbruch_ueber_die_steuerdatei(tmp_path, quelle, ziel, monkeypatch, capsys):
    """Der Abbruchwunsch der Oberflaeche beendet den Schritt wie Strg+C."""
    monkeypatch.setattr(steuerung, "SCHREIB_ABSTAND", 0.0)
    status = tmp_path / "status.json"
    steuer = tmp_path / "steuer.json"
    steuerung.wunsch_schreiben(steuer, abbrechen=True)
    auftrag = tmp_path / "auftrag.json"
    steuerung.json_schreiben(auftrag, {
        "schritt": "scan", "ziel": str(ziel), "quellen": [str(quelle)], "ziel_anlegen": False,
        "status_datei": str(status), "steuer_datei": str(steuer),
    })
    assert cli.main(["arbeit", "--auftrag", str(auftrag)]) == cli.ABGEBROCHEN
    d = steuerung.json_lesen(status)
    assert d["zustand"] == "abgebrochen" and d["rc"] == cli.ABGEBROCHEN and d["schritt"] == "scan"
    assert steuerung.AKTIV is None
    # Fortsetzbar: derselbe Auftrag ohne Abbruchwunsch laeuft durch.
    steuerung.wunsch_schreiben(steuer, abbrechen=False)
    assert cli.main(["arbeit", "--auftrag", str(auftrag)]) == cli.OK
    assert steuerung.json_lesen(status)["zustand"] == "fertig"


def test_arbeit_ohne_auftrag_und_unbekannter_schritt(tmp_path, ziel):
    assert cli.main(["arbeit", "--auftrag", str(tmp_path / "fehlt.json")]) == cli.FEHLENDE_ANGABE
    status = tmp_path / "status.json"
    auftrag = tmp_path / "auftrag.json"
    steuerung.json_schreiben(auftrag, {
        "schritt": "loeschen_alles", "ziel": str(ziel), "status_datei": str(status), "steuer_datei": str(tmp_path / "s.json"),
    })
    assert cli.main(["arbeit", "--auftrag", str(auftrag)]) == cli.FEHLENDE_ANGABE
    assert steuerung.json_lesen(status)["zustand"] == "fehler"


def test_aufraeumen_im_arbeitsprozess_ohne_wort_loescht_nichts(tmp_path, quelle, ziel, nachschauen, capsys):
    from test_kopieren import _cli, _vorbereiten
    _vorbereiten(ziel, quelle)
    assert _cli("kopieren", "--ziel", ziel) == cli.OK
    assert _cli("pruefen", "--ziel", ziel) == cli.OK
    vorher = _echte(_zeilen(nachschauen, ziel))
    assert "geprueft" in {z["status"] for z in vorher.values()}
    auftrag = tmp_path / "auftrag.json"
    for bestaetigung in ({}, {"dateien": "ja"}, {"dateien": "loeschen"}):   # falsches Wort je Weise
        steuerung.json_schreiben(auftrag, {
            "schritt": "aufraeumen", "ziel": str(ziel), "weise": "papierkorb", "leere_ordner": False,
            "bestaetigung": bestaetigung,
            "status_datei": str(tmp_path / "status.json"), "steuer_datei": str(tmp_path / "steuer.json"),
        })
        cli.main(["arbeit", "--auftrag", str(auftrag)])
        assert all(Path(q).exists() for q in vorher), bestaetigung
        assert cli.bestaetigung_vorgabe is None
    assert _echte(_zeilen(nachschauen, ziel)) == vorher


# ------------------------------------------------ laufender Prozess von aussen --


def test_laufender_schritt_wird_beim_naechsten_oeffnen_uebernommen(tmp_path):
    ordner = tmp_path / "ob"
    ordner.mkdir()
    jetzt = time.time()
    steuerung.json_schreiben(ordner / "status.json", {
        "schritt": "kopieren", "zustand": "laeuft", "pid": os.getpid(), "beginn": jetzt, "aktualisiert": jetzt,
        "dateien": 3, "gesamt": 10, "bytes": 300, "gesamt_bytes": 1000, "bytes_pro_s": 1.0, "restzeit_s": 7.0,
        "sekunden": 1.0, "lauf": 4, "rc": None, "hinweis": "",
    })
    steuerung.json_schreiben(ordner / "auftrag.json", {"schritt": "kopieren", "ziel": str(tmp_path / "Ziel")})
    ab = ablauf_modul.Ablauf(ordner=ordner)
    assert ab.lauf is not None and ab.lauf.pid == os.getpid() and ab.ziel == str(tmp_path / "Ziel")
    assert ab.lauf_lebt()
    l = ab.lauf_status()
    assert l["aktiv"] and l["zustand"] == "laeuft" and l["anteil"] == 0.3 and l["schritt_name"] == "Kopieren ins Archiv"
    with pytest.raises(Exception) as f:
        ab.schritt_starten("scan")
    assert "läuft" in str(f.value)
    ab.steuern("pause")
    assert steuerung.json_lesen(ordner / "steuer.json")["pause"] is True
    ab.steuern("weiter")
    assert steuerung.json_lesen(ordner / "steuer.json")["pause"] is False
    # Der Prozess meldet sich ab: nichts mehr aktiv.
    d = steuerung.json_lesen(ordner / "status.json")
    d["zustand"] = "fertig"
    steuerung.json_schreiben(ordner / "status.json", d)
    l = ab.lauf_status()
    assert l["aktiv"] is False and l["zustand"] == "fertig" and ab.lauf is None
    with pytest.raises(Exception):
        ab.steuern("abbrechen")


def test_verschwundener_prozess_gilt_als_abgestuerzt(tmp_path):
    ordner = tmp_path / "ob"
    ordner.mkdir()
    tot = subprocess.Popen([sys.executable, "-c", "pass"])
    tot.wait()
    alt = time.time() - 600
    steuerung.json_schreiben(ordner / "status.json", {
        "schritt": "analyse", "zustand": "laeuft", "pid": tot.pid, "beginn": alt, "aktualisiert": alt,
        "dateien": 1, "gesamt": 2, "bytes": 0, "gesamt_bytes": 0, "sekunden": 1.0, "lauf": 1, "rc": None, "hinweis": "",
    })
    (ordner / "arbeit.log").write_text("letzte Zeile\n", encoding="utf-8")
    ab = ablauf_modul.Ablauf(ordner=ordner)
    assert ab.lauf is None
    l = ab.lauf_status()
    assert l["zustand"] == "abgestuerzt" and l["aktiv"] is False and "letzte Zeile" in l["log"]
    assert "unerwartet" in l["zustand_text"]
    assert steuerung.json_lesen(ordner / "status.json")["zustand"] == "abgestuerzt"
    assert ablauf_modul.pid_lebt(0) is False and ablauf_modul.pid_lebt(os.getpid()) is True


# ------------------------------------------------------------ Fenster --


def test_fenster_selbsttest_ohne_fenster(capsys):
    assert cli.main(["fenster", "--ohne-fenster", "--selbsttest"]) == cli.OK
    aus = capsys.readouterr().out
    assert "Selbsttest bestanden" in aus and "http://127.0.0.1:" in aus


def test_fenster_kommando_und_umgebung(monkeypatch):
    befehl = ablauf_modul._kommando()
    assert befehl[-2:] == ["-m", "fotosort"] and befehl[0] == sys.executable
    env = ablauf_modul._umgebung()
    assert env["PYTHONUTF8"] == "1"
    assert str(Path(cli.__file__).resolve().parent.parent) in env["PYTHONPATH"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(Path("/x/fotosort.exe")))
    assert ablauf_modul._kommando() == [str(Path("/x/fotosort.exe"))]   # fotosort-konsole.exe fehlt: sich selbst nehmen
