"""Zusammengehoerige Dateien (SPEC Abschnitt 3). Reine Logik.

Dateien mit gleichem Stammnamen im selben Quellordner wandern gemeinsam
und bekommen Datum und Kamera der Hauptdatei. Prioritaet der Hauptdatei:
RAW > Foto > Video. Sidecars gehoeren nach den drei Formen aus
dateitypen.sidecar_gehoert_zu dazu.

Seit v0.8 (Entscheidungen des Nutzers) wird eine solche Namensgruppe nach der
Aufnahmezeit aufgeteilt (aufteilen): IMG_0001.JPG von 2016 und IMG_0001.MOV von
2021 gehoeren nicht zusammen, nur weil der Zaehler der Kamera neu begann; und
ein Mitglied, das sich nicht lesen laesst, faellt heraus, statt die anderen
mitzureissen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import dateitypen

_PRIORITAET = {dateitypen.RAW: 0, dateitypen.FOTO: 1, dateitypen.VIDEO: 2}


@dataclass
class Gruppe:
    haupt: str                              # Name der Hauptdatei
    mitglieder: list[str] = field(default_factory=list)  # ohne die Hauptdatei
    sidecars: list[str] = field(default_factory=list)

    @property
    def alle(self) -> list[str]:
        return [self.haupt, *self.mitglieder, *self.sidecars]


def _stamm(name: str) -> str:
    stelle = name.rfind(".")
    return name if stelle <= 0 else name[:stelle]


def bilden(namen: list[str], konf) -> tuple[list[Gruppe], list[str]]:
    """Gruppen eines Quellordners bilden.

    Gibt (Gruppen, Sidecars ohne Hauptdatei) zurueck. Dateien ausserhalb der
    echten Typen (sonstiges) werden ignoriert.
    """
    typen = {name: dateitypen.typ_von(name, konf) for name in namen}
    haupt_kandidaten = [n for n in namen if typen[n] in _PRIORITAET]
    sidecars = [n for n in namen if typen[n] == dateitypen.SIDECAR]

    # Hauptdateien nach Stammname buendeln; die beste wird Hauptdatei.
    nach_stamm: dict[str, list[str]] = {}
    for n in haupt_kandidaten:
        nach_stamm.setdefault(_stamm(n).lower(), []).append(n)

    gruppen: list[Gruppe] = []
    gruppe_von: dict[str, Gruppe] = {}
    for stamm, mitglieder in nach_stamm.items():
        sortiert = sorted(mitglieder, key=lambda n: (_PRIORITAET[typen[n]], n.lower()))
        g = Gruppe(haupt=sortiert[0], mitglieder=sortiert[1:])
        gruppen.append(g)
        for n in sortiert:
            gruppe_von[n] = g

    # Sidecars zuordnen: erst ueber die beste passende Hauptdatei.
    # Tempo (Phase 6): Kandidaten ueber Nachschlagetabellen (voller Name,
    # Stammname, Stammname als Praefix fuer Form 3) statt jede Sidecar gegen
    # jede Hauptdatei zu halten; entschieden wird weiterhin ausschliesslich
    # von sidecar_gehoert_zu, die Regeln bleiben dieselben.
    nach_name: dict[str, list[str]] = {}
    nach_stamm_klein: dict[str, list[str]] = {}
    for h in haupt_kandidaten:
        nach_name.setdefault(h.lower(), []).append(h)
        nach_stamm_klein.setdefault(_stamm(h).lower(), []).append(h)
    ohne_haupt: list[str] = []
    for s in sidecars:
        ss = _stamm(s).lower()
        kandidaten: dict[str, None] = {}
        for h in nach_name.get(ss, []):           # Form 2
            kandidaten[h] = None
        for h in nach_stamm_klein.get(ss, []):    # Form 1
            kandidaten[h] = None
        for laenge in range(1, len(ss)):          # Form 3: Hauptstamm ist Praefix
            for h in nach_stamm_klein.get(ss[:laenge], []):
                kandidaten[h] = None
        passende = [
            h for h in kandidaten if dateitypen.sidecar_gehoert_zu(s, h, konf)
        ]
        if not passende:
            ohne_haupt.append(s)
            continue
        beste = min(passende, key=lambda n: (_PRIORITAET[typen[n]], n.lower()))
        gruppe_von[beste].sidecars.append(s)

    gruppen.sort(key=lambda g: g.haupt.lower())
    return gruppen, ohne_haupt


# ------------------------------------------------ Aufteilen nach Zeit -----


@dataclass
class Mitglied:
    """Ein Mitglied vom Typ Foto, RAW oder Video fuer aufteilen()."""
    name: str
    typ: str
    zeit: datetime | None = None   # Datum aus den Metadaten (Quellen 1-4); None: keins
    kaputt: bool = False           # nicht lesbar (ExifTool-Fehler, leere Datei)
    daten: object = None           # beliebige Nutzlast des Aufrufers


def _rang(m: Mitglied) -> tuple:
    return (_PRIORITAET.get(m.typ, 9), m.name.lower())


def aufteilen(mitglieder: list[Mitglied], toleranz_sekunden: float) -> tuple[list[list[Mitglied]], list[Mitglied]]:
    """(Teilgruppen, kaputte Mitglieder) - SPEC §3, seit v0.8.

    In der Reihenfolge der Prioritaet kommt jedes lesbare Mitglied mit
    Metadaten-Datum zur ersten Teilgruppe, deren Zeit (die des ersten Mitglieds
    mit Datum) hoechstens toleranz_sekunden entfernt liegt - oder die noch gar
    keine Zeit hat; sonst beginnt es eine neue. Ein Mitglied ohne Datum kommt
    zur ersten Teilgruppe. Jede Teilgruppe ist nach Prioritaet sortiert, ihr
    erstes Mitglied ist ihre Hauptdatei."""
    lesbar = sorted((m for m in mitglieder if not m.kaputt), key=_rang)
    kaputt = sorted((m for m in mitglieder if m.kaputt), key=_rang)
    teile: list[list[Mitglied]] = []
    anker: list[datetime | None] = []
    ohne_zeit: list[Mitglied] = []
    for m in lesbar:
        if m.zeit is None:
            if teile:
                teile[0].append(m)
            else:
                ohne_zeit.append(m)
            continue
        for i, a in enumerate(anker):
            if a is None or abs((m.zeit - a).total_seconds()) <= toleranz_sekunden:
                teile[i].append(m)
                if a is None:
                    anker[i] = m.zeit
                break
        else:
            if ohne_zeit and not teile:
                teile.append(ohne_zeit + [m])
                ohne_zeit = []
            else:
                teile.append([m])
            anker.append(m.zeit)
    if ohne_zeit:
        if teile:
            teile[0].extend(ohne_zeit)
        else:
            teile.append(ohne_zeit)
    return [sorted(t, key=_rang) for t in teile], kaputt
