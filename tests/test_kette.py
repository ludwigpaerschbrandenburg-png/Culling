"""Seit v0.13 (Entscheidung des Nutzers vom 28.10.2026): „Alles automatisch“.

Nach einem einzigen „Los geht's“ mit dem Wort „verschieben“ laufen Scan,
Analyse, Kopieren, Pruefen und Aufraeumen nacheinander von selbst. Das
Aufraeumen legt die Originale nur in den Ordner _geloescht_ - nie endgueltig,
nie leere Ordner. Verschieben (loescht endgueltig) laeuft nie von selbst.

Die Tests treiben den Ablauf wie das Fenster: den Stand abfragen und bei jedem
Schrittende automatisch_weiter() rufen. Echte Arbeitsprozesse am kuenstlichen
Testbaum (SPEC §11), nie echte Fotos.
"""

from __future__ import annotations

import hashlib
import itertools
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

import testbaum
from fotosort import cli, loeschen, meldungen, steuerung, testbilder
from fotosort.oberflaeche import ablauf as ablauf_modul
from fotosort.oberflaeche.ablauf import KETTE, kette_naechster
from test_unterbrechungen import _bis, _kopierte, _zielbaum, grosse_quelle  # noqa: F401

WORT = meldungen.BESTAETIGUNGSWORT["papierkorb"]     # „verschieben“
ENDE = {"fertig", "abgebrochen", "fehler", "abgestuerzt"}


def _ablauf(tmp_path: Path, ziel: Path, quelle: Path | None = None) -> ablauf_modul.Ablauf:
    ab = ablauf_modul.Ablauf(ziel=str(ziel), ordner=tmp_path / "oberflaeche")
    if quelle is not None:
        ab.quelle_hinzufuegen(str(quelle))
    return ab


def _bis_ende(ab: ablauf_modul.Ablauf, sekunden: float = 240.0) -> dict:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        l = ab.lauf_status()
        if l["zustand"] in ENDE:
            return l
        time.sleep(0.05)
    raise AssertionError("Schritt nicht zu Ende: " + str(ab.lauf_status()))


def _weiter(ab: ablauf_modul.Ablauf) -> tuple[dict, dict]:
    """Wie das Fenster: aufs Ende des Schritts warten, dann automatisch_weiter()."""
    l = _bis_ende(ab)
    return l, ab.automatisch_weiter()


def _kette_bis_ende(ab: ablauf_modul.Ablauf, auftraege: dict | None = None) -> tuple[list[str], dict]:
    schritte: list[str] = []
    for _ in range(10):
        _l, a = _weiter(ab)
        if not a.get("gestartet"):
            return schritte, a
        schritte.append(a["gestartet"])
        if auftraege is not None:
            auftraege[a["gestartet"]] = steuerung.json_lesen(ab.auftrag_datei)
    raise AssertionError("Der Ablauf endet nicht: " + str(schritte))


def _inhalte(wurzel: Path) -> Counter:
    """Alle Inhalte unter einem Ordner, auch im Ordner _geloescht_."""
    return Counter(hashlib.sha256(p.read_bytes()).hexdigest() for p in wurzel.rglob("*") if p.is_file())


def _orte(wurzel: Path) -> list[str]:
    return sorted(p.relative_to(wurzel).as_posix() for p in wurzel.rglob("*") if p.is_file())


def _geloescht_ordner(quelle: Path) -> list[Path]:
    return [p for p in quelle.iterdir() if p.is_dir() and p.name.startswith("_geloescht_")]


def _stand(analyse: int = 0, kopieren: int = 0, pruefen: int = 0, aufraeumen: int = 0) -> dict:
    return {"analyse": analyse, "kopieren": (kopieren, kopieren * 10), "pruefen": (pruefen, pruefen * 10),
            "aufraeumen": (aufraeumen, aufraeumen * 10)}


def _scharf(ab: ablauf_modul.Ablauf, schritt: str = "scan") -> None:
    """Einen bestaetigten Ablauf hinstellen (wie nach „Los geht's“ mit dem Wort)."""
    ab._kette = ablauf_modul._Kette(WORT, ab.ziel, schritt, time.time())


# -------------------------------------------------- die Entscheidung allein --


@pytest.mark.parametrize("verschieben", [False, True])
@pytest.mark.parametrize("zustand", ["fertig", "fehler"])
def test_es_geht_nur_vorwaerts_zum_naechsten_schritt_mit_arbeit(zustand, verschieben):
    """Vollstaendig ueber jeden Schritt und jede Verteilung der Arbeit: Es geht
    immer nur zu einem spaeteren Schritt - hoechstens vier Uebergaenge, nie
    eine Schleife (wie der gefuehrte Modus `fotosort start`)."""
    for fertig in KETTE:
        for bits in itertools.product((0, 1), repeat=4):
            arbeit = dict(zip(KETTE[1:], bits))
            spaeter = [s for s in KETTE[KETTE.index(fertig) + 1:] if arbeit[s]]
            ergebnis = kette_naechster(fertig, zustand, "", _stand(*bits), verschieben)
            if fertig == "pruefen" and zustand == "fehler":
                assert ergebnis == ("ende", "pruefen_befunde")
            elif spaeter and spaeter[0] == "kopieren" and verschieben:
                assert ergebnis == ("ende", "verschieben")
            elif spaeter:
                assert ergebnis == ("start", spaeter[0])
                assert KETTE.index(ergebnis[1]) > KETTE.index(fertig)
            else:
                assert ergebnis == ("ende", "offen" if any(bits) else "fertig")


@pytest.mark.parametrize("zustand", ["abgebrochen", "abgestuerzt"])
def test_abbruch_und_absturz_beenden_den_ablauf(zustand):
    for fertig in KETTE:
        assert kette_naechster(fertig, zustand, "", _stand(1, 1, 1, 1), False) == ("ende", zustand)


def test_nicht_fertig_gewordener_schritt_beendet_den_ablauf():
    """Platte voll, Archiv belegt, Ziel weg: „fehler“ mit einem Grund."""
    for fertig in KETTE:
        assert kette_naechster(fertig, "fehler", "Zu wenig Platz", _stand(1, 1, 1, 1), False) == ("ende", "nicht_fertig")


def test_einzelne_dateifehler_halten_nicht_an_aber_befunde_beim_pruefen():
    assert kette_naechster("scan", "fehler", "", _stand(1, 0, 0, 0), False) == ("start", "analyse")
    assert kette_naechster("analyse", "fehler", "", _stand(0, 1, 0, 0), False) == ("start", "kopieren")
    assert kette_naechster("kopieren", "fehler", "", _stand(0, 0, 1, 1), False) == ("start", "pruefen")
    # Hat das Pruefen Abweichungen gefunden, wird nicht aufgeraeumt.
    assert kette_naechster("pruefen", "fehler", "", _stand(0, 0, 0, 5), False) == ("ende", "pruefen_befunde")
    assert kette_naechster("pruefen", "fertig", "", _stand(0, 0, 0, 5), False) == ("start", "aufraeumen")


def test_nur_die_eigenen_schritte_und_nur_nach_dem_ende():
    for fremd in ("zuruecklegen", "ziel-index", "nachpruefen", ""):
        assert kette_naechster(fremd, "fertig", "", _stand(1, 1, 1, 1), False) == ("ende", "fremd")
    for zustand in ("laeuft", "pause", "startet", ""):
        assert kette_naechster("scan", zustand, "", _stand(1, 1, 1, 1), False)[0] == "ende"


# ------------------------------------------------------------ Weigerungen --


def test_ohne_wort_startet_nichts(tmp_path, quelle, ziel):
    ab = _ablauf(tmp_path, ziel, quelle)
    for wort in ("", "   "):
        a = ab.los(automatisch=True, wort=wort)
        assert a["frage"] == "automatisch" and a["wort"] == WORT
    for teil in ("_geloescht_", "Zurücklegen", f"„{WORT}“", str(quelle)):
        assert teil in a["text"]
    assert meldungen.OB_KETTE_VERSCHIEBEN_HINWEIS not in a["text"]
    assert ab.lauf is None and not ab.status_datei.exists()
    assert ab.lauf_status()["kette"] is False and ab.automatisch_weiter() == {}


@pytest.mark.parametrize("wort", ["ja", "loeschen", "entfernen", "verwerfen", "verschieben!", "nicht verschieben"])
def test_falsches_wort_startet_nichts(tmp_path, quelle, ziel, wort):
    ab = _ablauf(tmp_path, ziel, quelle)
    with pytest.raises(ablauf_modul.FotosortFehler) as f:
        ab.los(automatisch=True, wort=wort)
    assert f"„{WORT}“" in str(f.value)
    assert ab.lauf is None and not ab.status_datei.exists() and ab.automatisch_weiter() == {}


def test_ohne_automatik_bleibt_los_wie_bisher(tmp_path, quelle, ziel):
    """Die Browser-Fassung fragt nicht: los() ohne automatisch startet den Scan,
    und danach geht nichts von selbst weiter - auch wenn die Einstellung an ist."""
    ab = _ablauf(tmp_path, ziel, quelle)
    assert ab.automatisch is True
    assert ab.los()["gestartet"] == "scan"
    l = _bis_ende(ab)
    assert l["zustand"] == "fertig" and l["kette"] is False
    assert ab.automatisch_weiter() == {} and not ab.lauf_lebt()


def test_automatik_ist_standard_und_wird_gemerkt(tmp_path):
    ab = ablauf_modul.Ablauf(ordner=tmp_path / "ob")
    assert ab.automatisch is True and ab.zustand()["automatisch"] is True
    alt = tmp_path / "alt"
    steuerung.json_schreiben(alt / "zustand.json", {"ziel": "", "quellen": [], "verschieben": False, "profil": "hdd"})
    assert ablauf_modul.Ablauf(ordner=alt).automatisch is True       # Stand von v0.12: an
    assert ab.einstellungen_setzen(automatisch=False)["automatisch"] is False
    assert ablauf_modul.Ablauf(ordner=tmp_path / "ob").automatisch is False


def test_jede_andere_aktion_loescht_die_bestaetigung(tmp_path, ziel):
    """Die Bestaetigung gilt nur fuer diesen einen Ablauf."""
    ab = _ablauf(tmp_path, ziel)
    aktionen = {
        "Automatik aus": lambda: ab.einstellungen_setzen(automatisch=False),
        "Modus Verschieben": lambda: ab.einstellungen_setzen(verschieben=True),
        "anderes Ziel": lambda: ab.ziel_setzen(str(tmp_path / "anderes Ziel")),
        "Programm schliessen": lambda: ab.beenden(),
        "Sofort beenden": lambda: ab.steuern("sofort"),
        "Abbrechen": lambda: ab.steuern("abbrechen"),
        "Archiv verwerfen": lambda: ab.archiv_verwerfen(""),
    }
    for name, aktion in aktionen.items():
        ab.einstellungen_setzen(automatisch=True, verschieben=False)
        ab.ziel_setzen(str(ziel))
        _scharf(ab)
        assert ab.lauf_status()["kette"] is True
        try:
            aktion()
        except ablauf_modul.FotosortFehler:
            pass
        assert ab.lauf_status()["kette"] is False, name
    _scharf(ab)
    ab.einstellungen_setzen(profil="ssd")          # das Profil zu aendern ist harmlos
    assert ab.lauf_status()["kette"] is True


def test_aufraeumen_im_ablauf_nur_nach_geloescht(tmp_path, ziel, monkeypatch):
    """Weise und leere Ordner stehen fest im Programm - egal, was rechts auf der
    Karte eingestellt ist: nie endgueltig, nie leere Ordner."""
    ab = _ablauf(tmp_path, ziel)
    gestartet: list[tuple[str, dict]] = []
    stand = {**_stand(aufraeumen=3), "zaehler": {"geprueft": 3}, "phase": "", "zuruecklegbar": 0,
             "loeschbar_je_quelle": {}, "quellen": []}
    monkeypatch.setattr(ab, "schritt_starten", lambda schritt, **werte: gestartet.append((schritt, werte)) or {"gestartet": schritt, "pid": 0})
    monkeypatch.setattr(ab, "lauf_lebt", lambda: False)
    monkeypatch.setattr(ab, "lauf_status", lambda: {"zustand": "fertig", "schritt": "pruefen", "hinweis": "", "kette": True})
    monkeypatch.setattr(ab, "archiv_lesen", lambda: dict(stand))
    _scharf(ab, "pruefen")
    assert ab.automatisch_weiter()["gestartet"] == "aufraeumen"
    assert ab.automatisch_starten(WORT)["gestartet"] == "aufraeumen"      # Knopf „Automatisch weiter ab …“
    assert len(gestartet) == 2
    for schritt, werte in gestartet:
        assert schritt == "aufraeumen"
        assert werte["weise"] == loeschen.WEISE_PAPIERKORB and werte["leere_ordner"] is False
        assert werte["bestaetigung"] == {"dateien": WORT, "ordner": ""}
    with pytest.raises(ablauf_modul.FotosortFehler):
        ab.automatisch_starten(meldungen.BESTAETIGUNGSWORT["endgueltig"])   # „loeschen“ gilt hier nie
    assert len(gestartet) == 2


# ------------------------------------------- echte Arbeitsprozesse, Testbaum --


def test_alles_automatisch_bis_zum_aufraeumen(tmp_path, quelle, ziel, nachschauen):
    """Ein „Los geht's“ mit dem Wort, dann kein Klick mehr. Die Originale liegen
    danach im Ordner _geloescht_ der Quelle: kein Inhalt fehlt, ein leerer Ordner
    bleibt stehen, und „Zuruecklegen“ holt alles an den alten Ort."""
    (quelle / "Leer" / "auch leer").mkdir(parents=True)
    vorher, orte = _inhalte(quelle), _orte(quelle)
    ab = _ablauf(tmp_path, ziel, quelle)
    a = ab.los(automatisch=True, wort="  Verschieben ")
    assert a["gestartet"] == "scan" and ab.lauf_status()["kette"] is True
    auftraege = {"scan": steuerung.json_lesen(ab.auftrag_datei)}
    schritte, ende = _kette_bis_ende(ab, auftraege)
    assert schritte == ["analyse", "kopieren", "pruefen", "aufraeumen"]
    assert ende["ende"] == "fertig" and "erledigt" in ende["text"]
    assert ab.naechster()["schritt"] == "fertig"
    assert ab.lauf_status()["kette"] is False and ab.automatisch_weiter() == {}
    # Aufgeraeumt nur in den Ordner _geloescht_, nie endgueltig, nie leere Ordner.
    auf = auftraege["aufraeumen"]
    assert auf["weise"] == loeschen.WEISE_PAPIERKORB and auf["leere_ordner"] is False
    assert auf["bestaetigung"] == {"dateien": WORT, "ordner": ""}
    for schritt in ("scan", "analyse", "kopieren", "pruefen"):
        assert "bestaetigung" not in auftraege[schritt] and "wort" not in auftraege[schritt]
    assert len(_geloescht_ordner(quelle)) == 1
    assert _inhalte(quelle) == vorher
    assert (quelle / "Leer" / "auch leer").is_dir()
    with nachschauen(ziel) as d:
        z = d.zaehler_je_status()
    assert z.get("quelle_geloescht", 0) > 0 and not z.get("geprueft") and not z.get("duplikat_bestaetigt")
    assert not z.get("analysiert") and not z.get("kopiert")
    # Die Bestaetigung lebt nur im Speicher: Ein neues Fenster kennt sie nicht.
    neu = ablauf_modul.Ablauf(ordner=tmp_path / "oberflaeche")
    assert neu.lauf_status()["kette"] is False and neu.automatisch_weiter() == {}
    # „Zuruecklegen“ holt alles an den alten Ort.
    assert neu.zuruecklegen_starten(True)["gestartet"] == "zuruecklegen"
    assert _bis_ende(neu)["zustand"] == "fertig"
    assert _orte(quelle) == orte and _inhalte(quelle) == vorher


def test_verschieben_laeuft_nie_von_selbst(tmp_path, quelle, ziel):
    """Verschieben loescht die Originale endgueltig - mit demselben Wort wie das
    Aufraeumen. Der Ablauf haelt deshalb davor an, und auch der Knopf
    „Automatisch weiter“ verschiebt nie."""
    vorher, orte = _inhalte(quelle), _orte(quelle)
    ab = _ablauf(tmp_path, ziel, quelle)
    ab.einstellungen_setzen(verschieben=True)
    a = ab.los(automatisch=True)
    assert a["frage"] == "automatisch" and meldungen.OB_KETTE_VERSCHIEBEN_HINWEIS in a["text"]
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    schritte, ende = _kette_bis_ende(ab)
    assert schritte == ["analyse"] and ende["ende"] == "verschieben" and "endgültig" in ende["text"]
    assert ab.naechster()["schritt"] == "kopieren" and not ab.lauf_lebt()
    with pytest.raises(ablauf_modul.FotosortFehler):
        ab.automatisch_starten(WORT)
    assert not ab.lauf_lebt()
    assert _inhalte(quelle) == vorher and _orte(quelle) == orte
    assert not [p for p in ziel.rglob("*") if p.is_file() and ".fotosortierer" not in p.parts]


def test_kein_aufraeumen_wenn_das_pruefen_abweichungen_findet(tmp_path, quelle, ziel):
    vorher = _inhalte(quelle)
    ab = _ablauf(tmp_path, ziel, quelle)
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    assert _weiter(ab)[1]["gestartet"] == "analyse"
    assert _weiter(ab)[1]["gestartet"] == "kopieren"
    l = _bis_ende(ab)
    assert l["schritt"] == "kopieren" and l["zustand"] == "fertig"
    kopie = next(p for p in sorted(ziel.rglob("*")) if p.suffix.lower() == ".jpg" and ".fotosortierer" not in p.parts)
    with open(kopie, "ab") as f:
        f.write(b"verfaelscht")                          # die Kopie im Archiv stimmt nicht mehr
    assert ab.automatisch_weiter()["gestartet"] == "pruefen"
    l, a = _weiter(ab)
    assert l["schritt"] == "pruefen" and l["zustand"] == "fehler"
    assert a["ende"] == "pruefen_befunde" and a["text"]
    assert not _geloescht_ordner(quelle) and _inhalte(quelle) == vorher
    assert not ab.lauf_lebt() and ab.automatisch_weiter() == {}


def test_abbrechen_mitten_im_kopieren_haelt_den_ablauf_an(tmp_path, grosse_quelle, ziel):
    ab = _ablauf(tmp_path, ziel, grosse_quelle)
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    assert _weiter(ab)[1]["gestartet"] == "analyse"
    assert _weiter(ab)[1]["gestartet"] == "kopieren"
    _bis(lambda: _kopierte(ziel) >= 50)
    ab.steuern("abbrechen")
    assert ab.lauf_status()["kette"] is False        # sofort, noch bevor der Schritt endet
    assert _bis_ende(ab)["zustand"] == "abgebrochen"
    assert ab.automatisch_weiter() == {} and not ab.lauf_lebt()
    assert not _geloescht_ordner(grosse_quelle)


def test_abbrechen_gleich_nach_dem_ende_eines_schritts_startet_nichts_mehr(tmp_path, quelle, ziel):
    """Der Klick auf „Abbrechen“ kommt einen Augenblick zu spaet: Der Schritt ist
    schon fertig. Dann darf kein naechster Schritt mehr beginnen."""
    ab = _ablauf(tmp_path, ziel, quelle)
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    l = _bis_ende(ab)
    assert l["zustand"] == "fertig" and l["kette"] is True
    a = ab.steuern("abbrechen")
    assert a["ok"] is True and a["text"]
    assert ab.lauf_status()["kette"] is False and ab.automatisch_weiter() == {}
    assert not ab.lauf_lebt() and ab.naechster()["schritt"] == "analyse"
    with pytest.raises(ablauf_modul.FotosortFehler):
        ab.steuern("abbrechen")                          # ohne Ablauf und ohne Schritt wie bisher


def test_ein_schritt_von_hand_loescht_die_bestaetigung(tmp_path, quelle, ziel):
    ab = _ablauf(tmp_path, ziel, quelle)
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    assert _bis_ende(ab)["kette"] is True
    assert ab.schritt("analyse")["gestartet"] == "analyse"
    assert ab.lauf_status()["kette"] is False
    _bis_ende(ab)
    assert ab.automatisch_weiter() == {} and not ab.lauf_lebt()


def test_doppelte_aufrufe_starten_nur_einmal(tmp_path, quelle, ziel):
    ab = _ablauf(tmp_path, ziel, quelle)
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    _bis_ende(ab)
    assert ab.automatisch_weiter()["gestartet"] == "analyse"
    assert ab.automatisch_weiter() == {"laeuft": "analyse"}
    _bis_ende(ab)
    ergebnisse: list[dict] = []
    straenge = [threading.Thread(target=lambda: ergebnisse.append(ab.automatisch_weiter())) for _ in range(4)]
    for s in straenge:
        s.start()
    for s in straenge:
        s.join(60)
    assert [e["gestartet"] for e in ergebnisse if e.get("gestartet")] == ["kopieren"]
    assert all(e.get("gestartet") or e.get("laeuft") == "kopieren" for e in ergebnisse)
    ab.steuern("abbrechen")
    _bis_ende(ab)


def test_startfehler_beendet_den_ablauf_genau_einmal(tmp_path, quelle, ziel, monkeypatch):
    """Ein Fehler beim Starten kommt nicht bei jeder Abfrage wieder."""
    ab = _ablauf(tmp_path, ziel, quelle)
    assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
    _bis_ende(ab)

    def kaputt(*_a, **_k):
        raise OSError(28, "Kein Platz auf dem Datenträger")

    monkeypatch.setattr(ab, "schritt_starten", kaputt)
    a = ab.automatisch_weiter()
    assert a["ende"] == "startfehler" and "Kein Platz" in a["text"]
    assert ab.automatisch_weiter() == {} and ab.lauf_status()["kette"] is False


def test_unterbrochen_und_automatisch_weiter_wie_ohne_unterbrechung(tmp_path, nachschauen):
    """Abbruch zwischen zwei Schritten, Fenster zu und wieder auf, dann
    „Automatisch weiter“ mit dem Wort: Am Ende sehen Archiv und Datenbank aus
    wie nach einem Lauf ohne Unterbrechung."""
    ergebnisse = []
    for name, unterbrechen in (("ohne", False), ("mit", True)):
        baum = testbaum.erzeugen(tmp_path / name / "baum")
        ziel = tmp_path / name / "Ziel"
        ziel.mkdir()
        ab = ablauf_modul.Ablauf(ziel=str(ziel), ordner=tmp_path / name / "oberflaeche")
        ab.quelle_hinzufuegen(str(baum["quelle"]))
        assert ab.los(automatisch=True, wort=WORT)["gestartet"] == "scan"
        assert _weiter(ab)[1]["gestartet"] == "analyse"
        if unterbrechen:
            _bis_ende(ab)
            assert ab.steuern("abbrechen")["ok"] is True          # zwischen Analyse und Kopieren
            ab = ablauf_modul.Ablauf(ordner=tmp_path / name / "oberflaeche")
            assert ab.automatisch_starten()["frage"] == "automatisch"
            assert ab.automatisch_starten(WORT)["gestartet"] == "kopieren"
        _schritte, ende = _kette_bis_ende(ab)
        assert ende["ende"] == "fertig"
        with nachschauen(ziel) as d:
            ergebnisse.append((_zielbaum(ziel), d.zaehler_je_status()))
    assert ergebnisse[0] == ergebnisse[1]


def test_testbilder_alles_automatisch_und_alles_richtig(tmp_path):
    """300 Testbilder (SPEC §11), alles automatisch bis zum Aufraeumen: „Ergebnis
    pruefen“ findet jede Datei am erwarteten Platz, kein Inhalt ging verloren."""
    test = tmp_path / "Testbilder"
    assert cli.main(["testbilder", str(test), "--anzahl", "300"]) == cli.OK
    ab = ablauf_modul.Ablauf(ziel=str(test / testbilder.ZIEL), ordner=tmp_path / "oberflaeche")
    ab.quelle_hinzufuegen(str(test / testbilder.QUELLE))
    assert ab.los(automatisch=True)["frage"] == "ziel_nicht_leer"      # das Testziel ist absichtlich belegt
    assert ab.los(ziel_trotzdem=True, automatisch=True)["frage"] == "automatisch"
    assert ab.los(ziel_trotzdem=True, automatisch=True, wort=WORT)["gestartet"] == "scan"
    schritte, ende = _kette_bis_ende(ab)
    assert schritte == ["analyse", "kopieren", "pruefen", "aufraeumen"] and ende["ende"] == "fertig"
    assert _geloescht_ordner(test / testbilder.QUELLE)
    p = testbilder.pruefen(test)
    assert p.ok and p.verloren == 0, p.befunde[:5]
