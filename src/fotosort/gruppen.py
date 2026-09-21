"""Zusammengehoerige Dateien (SPEC Abschnitt 3). Reine Logik.

Dateien mit gleichem Stammnamen im selben Quellordner wandern gemeinsam
und bekommen Datum und Kamera der Hauptdatei. Prioritaet der Hauptdatei:
RAW > Foto > Video. Sidecars gehoeren nach den drei Formen aus
dateitypen.sidecar_gehoert_zu dazu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    ohne_haupt: list[str] = []
    for s in sidecars:
        passende = [
            h for h in haupt_kandidaten if dateitypen.sidecar_gehoert_zu(s, h, konf)
        ]
        if not passende:
            ohne_haupt.append(s)
            continue
        beste = min(passende, key=lambda n: (_PRIORITAET[typen[n]], n.lower()))
        gruppe_von[beste].sidecars.append(s)

    gruppen.sort(key=lambda g: g.haupt.lower())
    return gruppen, ohne_haupt
