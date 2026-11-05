"""Reiter "Wohin?": wohin kommt was - als Rechnung, ohne Qt (v0.14, SPEC §8).

1. lesen(): EINE Abfrage ueber die Tabelle dateien. Jede Zeile bekommt ihren
   Quellordner (unter ihrer Quellwurzel), ihr Schicksal und ihren
   Archivordner (unter dem Archiv) und wird zu Stroemen zusammengezaehlt -
   aus einer Million Dateien werden einige zehntausend Stroeme.
2. ansicht(): eine Ebene links und rechts waehlen (hineinklicken), hoechstens
   max_knoten Knoten je Seite, der Rest als "weitere".
3. lage(): Knoten und Baender als reine Rechnung, ohne Zeichnen; band_bei()
   findet das Band unter dem Zeiger. Gezeichnet wird in
   oberflaeche/wohinfenster.py.

Zuordnung (Pruefung v0.14):
- kopiert, geprueft, verschoben, quelle_geloescht: im Archiv - der Inhalt
  liegt unter zielpfad. Ein aufgeraeumtes Duplikat (war_duplikat) bleibt doppelt.
- analysiert, kopieren_laeuft: geplant - zielpfad ist der geplante Name.
- duplikat, duplikat_bestaetigt: zielpfad ist die Partnerdatei im Archiv,
  dort liegt ihr Inhalt. schon_im_archiv 1: war schon im Archiv, sonst doppelt.
- uebersprungen, gefunden, fehler: Kaesten ohne Archivordner.
- Ein zielpfad ausserhalb des Archivs (alter Ort, siehe umzug.py): Kasten
  "Archiv an anderem Ort".
Der erste Ordner unter dem Archiv ist nicht immer ein Jahr ("2020.08",
"Alte Handybilder", "_Ohne_Datum") - gezeigt werden die echten Namen.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import db, meldungen

# Schicksale. Die ersten vier fuehren in einen Archivordner, die anderen in einen Kasten.
KOPIERT = "kopiert"
GEPLANT = "geplant"
DOPPELT = "doppelt"
SCHON_DA = "schon_da"
BLEIBT = "bleibt"
OFFEN = "offen"
FEHLER = "fehler"
ANDERSWO = "anderswo"
INS_ARCHIV = (KOPIERT, GEPLANT, DOPPELT, SCHON_DA)
KAESTEN = (BLEIBT, OFFEN, FEHLER, ANDERSWO)
SCHICKSALE = INS_ARCHIV + KAESTEN
_REIHE = {s: i for i, s in enumerate(SCHICKSALE)}

_VON_STATUS = {
    "kopiert": KOPIERT, "geprueft": KOPIERT, "verschoben": KOPIERT, "quelle_geloescht": KOPIERT,
    "analysiert": GEPLANT, "kopieren_laeuft": GEPLANT,
    "duplikat": DOPPELT, "duplikat_bestaetigt": DOPPELT,
    "uebersprungen": BLEIBT, "gefunden": OFFEN, "fehler": FEHLER,
}

# Arten von Knoten (Kaesten tragen ihr Schicksal als Art).
ORDNER = "ordner"
DIREKT = "direkt"
WEITERE = "weitere"

STAND_LEER = "leer"          # noch nichts eingeplant
STAND_PLAN = "plan"          # eingeplant, noch nichts im Archiv
STAND_SORTIERT = "sortiert"  # mindestens eine Datei liegt im Archiv

MAX_KNOTEN = 10              # je Seite, "weitere" eingerechnet (Kaesten kommen dazu)
KNOTEN_BREITE = 10.0
ZEILE = 18.0                 # Mindestplatz je Knoten fuer seine Beschriftung
ABSTAND = 6.0                # Luft zwischen zwei Knoten
MIN_BAND = 1.0               # duennstes Band: auch eine einzelne Datei bleibt sichtbar

# Interne Schluessel, die kein Ordnername sein koennen.
_DIREKT = "\x00direkt"
_WEITERE = "\x00weitere"


@dataclass(frozen=True, slots=True)
class Eintrag:
    """Ein Strom: so viele Dateien aus diesem Quellordner gehen mit diesem
    Schicksal in diesen Archivordner (ziel None: in einen Kasten)."""
    wurzel: str
    quelle: tuple[str, ...]
    schicksal: str
    ziel: tuple[str, ...] | None
    n: int
    bytes: int


@dataclass
class Daten:
    ziel: str
    eintraege: list[Eintrag]
    n: int = 0
    bytes: int = 0
    je_schicksal: dict[str, int] = field(default_factory=dict)
    bytes_je_schicksal: dict[str, int] = field(default_factory=dict)
    stand: str = STAND_LEER


@dataclass
class Knoten:
    schluessel: tuple[str, ...] | None   # zum Hineinklicken; None bei "direkt", "weitere", Kaesten
    name: str
    art: str
    n: int = 0
    bytes: int = 0
    tiefer: bool = False                 # hat Unterordner - laesst sich anklicken
    mitglieder: tuple[tuple[str, ...], ...] = ()   # bei "weitere": die zusammengefassten Ordner


@dataclass
class Band:
    links: int
    rechts: int
    schicksal: str
    n: int
    bytes: int


@dataclass
class Ansicht:
    links: list[Knoten]
    rechts: list[Knoten]
    baender: list[Band]
    pfad_links: tuple[str, ...] = ()
    pfad_rechts: tuple[str, ...] = ()
    n: int = 0
    bytes: int = 0
    # Interner Schluessel (Ordnername, "direkt", Kasten) -> Knoten; fuer band_dateien.
    l_index: dict = field(default_factory=dict, repr=False, compare=False)
    r_index: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Datei:
    """Eine Datei in der Liste eines Bandes oder der Suche."""
    quelle: str
    ziel: str            # Pfad im Archiv ('' ohne)
    schicksal: str
    status: str
    grund: str
    groesse: int


@dataclass
class KnotenLage:
    x: float
    y: float
    b: float
    h: float
    mitte: float          # Hoehe der Beschriftung


@dataclass
class BandLage:
    x0: float
    x1: float
    y0o: float
    y0u: float
    y1o: float
    y1u: float


@dataclass
class Lage:
    links: list[KnotenLage]
    rechts: list[KnotenLage]
    baender: list[BandLage]
    massstab: float       # Pixel je Datei


# ------------------------------------------------------------- Lesen ----


def schicksal_von(status: str, schon_im_archiv: int) -> str:
    s = _VON_STATUS.get(status, OFFEN)
    return SCHON_DA if s == DOPPELT and schon_im_archiv else s


_SPALTEN = "quellwurzel, quellpfad, zielpfad, status, schon_im_archiv, groesse, war_duplikat"


class _Einordner:
    """Eine Zeile einordnen: (Quellwurzel, Quellordner, Schicksal, Archivordner).
    Die Ordner als Text mit dem Trenner des Systems ("" = direkt in der Wurzel,
    Archivordner None = Kasten). Dieselbe Rechnung fuer die ganze Tabelle
    (lesen), fuer die Dateien eines Bandes und fuer die Suche."""

    def __init__(self, ziel: Path) -> None:
        self.sep = os.sep
        self.windows = self.sep == "\\"
        ziel_text = db.text_pfad(db.pfad_text(ziel))
        self.zbasis = ziel_text if ziel_text.endswith(self.sep) else ziel_text + self.sep
        self.zbasis_klein = self.zbasis.lower()
        self.zlaenge = len(self.zbasis)
        self.basen: dict[str, tuple[str, str, int]] = {}

    def __call__(self, wurzel, qp, zp, status, schon, war_duplikat) -> tuple[str, str, str, str | None]:
        sep = self.sep
        s = _VON_STATUS.get(status, OFFEN)
        if s == DOPPELT and schon:
            s = SCHON_DA
        elif war_duplikat and status == "quelle_geloescht":
            s = DOPPELT          # aufgeraeumtes Duplikat (seit v0.14)
        b = self.basen.get(wurzel)
        if b is None:
            w = db.text_pfad(wurzel)
            basis = w if w.endswith(sep) else w + sep
            b = self.basen[wurzel] = (basis, basis.lower(), len(basis))
        if qp.startswith(_ROH):
            qp = db.text_pfad(qp)
        if qp.startswith(b[0]) or (self.windows and qp[:b[2]].lower() == b[1]):
            rest = qp[b[2]:]
        else:
            rest = qp
        stelle = rest.rfind(sep)
        q_ordner = rest[:stelle] if stelle > 0 else ""
        z_ordner = None
        if s in _MIT_ORDNER:
            if zp.startswith(_ROH):
                zp = db.text_pfad(zp)
            if zp.startswith(self.zbasis) or (self.windows and zp[:self.zlaenge].lower() == self.zbasis_klein):
                zrest = zp[self.zlaenge:]
                stelle = zrest.rfind(sep)
                z_ordner = zrest[:stelle] if stelle > 0 else ""
            else:
                s = ANDERSWO
        return wurzel, q_ordner, s, z_ordner

    def ketten(self, q_ordner: str, z_ordner: str | None) -> tuple[tuple[str, ...], tuple[str, ...] | None]:
        quelle = tuple(q_ordner.split(self.sep)) if q_ordner else ()
        if z_ordner is None:
            return quelle, None
        return quelle, (tuple(z_ordner.split(self.sep)) if z_ordner else ())


_ROH = db._ROH_KENNZEICHEN
_MIT_ORDNER = frozenset(INS_ARCHIV)


def lesen(dbank: db.Datenbank, ziel: Path) -> Daten:
    """Die ganze Tabelle einmal lesen und zu Stroemen zusammenzaehlen."""
    einordnen = _Einordner(ziel)
    sammel: dict[tuple, list[int]] = {}
    dbank.stapel_schreiben()
    for wurzel, qp, zp, status, schon, groesse, war_duplikat in dbank.verbindung.execute(
            f"SELECT {_SPALTEN} FROM dateien"):
        schluessel = einordnen(wurzel, qp, zp, status, schon, war_duplikat)
        wert = sammel.get(schluessel)
        if wert is None:
            sammel[schluessel] = [1, groesse or 0]
        else:
            wert[0] += 1
            wert[1] += groesse or 0
    eintraege: list[Eintrag] = []
    je: dict[str, int] = {}
    bytes_je: dict[str, int] = {}
    for (wurzel, q_ordner, s, z_ordner), (n, b) in sammel.items():
        quelle, kette = einordnen.ketten(q_ordner, z_ordner)
        eintraege.append(Eintrag(wurzel, quelle, s, kette, n, b))
        je[s] = je.get(s, 0) + n
        bytes_je[s] = bytes_je.get(s, 0) + b
    eintraege.sort(key=lambda e: (e.wurzel, e.quelle, _REIHE[e.schicksal], e.ziel or ()))
    if je.get(KOPIERT, 0) + je.get(DOPPELT, 0) + je.get(SCHON_DA, 0):
        stand = STAND_SORTIERT
    elif je.get(GEPLANT, 0):
        stand = STAND_PLAN
    else:
        stand = STAND_LEER
    return Daten(ziel=db.pfad_text(ziel), eintraege=eintraege, n=sum(je.values()), bytes=sum(bytes_je.values()),
                 je_schicksal=je, bytes_je_schicksal=bytes_je, stand=stand)


# ------------------------------------------------------------ Ansicht ----


def name_direkt(ordner: str) -> str:
    return meldungen.wohin_direkt(ordner)


def _sortierung(name: str) -> tuple:
    """Natuerliche Reihenfolge ("2" vor "10"), Gross-/Kleinschreibung egal;
    Ordner mit "_" am Anfang (_Ohne_Datum) zuletzt."""
    teile = [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", name.casefold()) if t]
    return (name.startswith("_"), teile, name)


def _anzeigename(wurzel: str) -> str:
    return db.text_pfad(wurzel)


def _quellnamen(wurzeln) -> dict[str, str]:
    """Quellen heissen nach ihrem Ordner ("Karte", "Urlaub 2019"). Heissen zwei
    gleich (Gross-/Kleinschreibung egal) oder hat eine keinen eigenen Namen
    (ein ganzes Laufwerk), steht der ganze Pfad da."""
    kurz = {w: Path(_anzeigename(w)).name for w in wurzeln}
    wie_oft: dict[str, int] = {}
    for name in kurz.values():
        wie_oft[name.casefold()] = wie_oft.get(name.casefold(), 0) + 1
    return {w: name if name and wie_oft[name.casefold()] == 1 else _anzeigename(w) for w, name in kurz.items()}


def _ordnername(teil: str) -> str:
    return Path(db.text_pfad(teil)).name or db.text_pfad(teil)


def ansicht(daten: Daten, links: tuple[str, ...] = (), rechts: tuple[str, ...] = (),
            max_knoten: int = MAX_KNOTEN) -> Ansicht:
    """Eine Ebene der Grafik. links: Weg in den Quellen ((), (Wurzel,),
    (Wurzel, Ordner, ...)); rechts: Weg im Archiv ((), ("2019",), ...).
    Klickt man rechts hinein, zaehlt nur, was dort liegt - die Kaesten
    entfallen, und die linke Seite zeigt nur, was dorthin geht."""
    ll, rl = len(links), len(rechts)
    l_werte: dict[str, list] = {}     # Schluessel -> [n, bytes, tiefer]
    r_werte: dict[str, list] = {}
    stroeme: dict[tuple[str, str, str], list[int]] = {}
    for e in daten.eintraege:
        kette = (e.wurzel, *e.quelle)
        schluessel = _schluessel(kette, e.ziel, e.schicksal, links, rechts)
        if schluessel is None:
            continue
        lk, rk = schluessel
        for werte, k, tiefer in ((l_werte, lk, len(kette) > ll + 1),
                                 (r_werte, rk, e.ziel is not None and len(e.ziel) > rl + 1)):
            w = werte.get(k)
            if w is None:
                werte[k] = [e.n, e.bytes, tiefer]
            else:
                w[0] += e.n
                w[1] += e.bytes
                w[2] = w[2] or tiefer
        s = stroeme.get((lk, rk, e.schicksal))
        if s is None:
            stroeme[(lk, rk, e.schicksal)] = [e.n, e.bytes]
        else:
            s[0] += e.n
            s[1] += e.bytes

    def knoten_bilden(werte: dict[str, list], weg: tuple[str, ...], ist_links: bool) -> tuple[list[Knoten], dict]:
        """Knoten in fester Reihenfolge und eine Zuordnung Schluessel -> Index."""
        ordner_k = [k for k in werte if not k.startswith("\x00")]
        kandidaten = ordner_k + ([_DIREKT] if _DIREKT in werte else [])
        behalten = set(kandidaten)
        rest: list[str] = []
        if len(kandidaten) > max_knoten:
            nach_groesse = sorted(kandidaten, key=lambda k: (-werte[k][0], _sortierung(k)))
            behalten = set(nach_groesse[: max_knoten - 1])
            rest = [k for k in kandidaten if k not in behalten]
        knoten: list[Knoten] = []
        index: dict[str, int] = {}
        namen = _quellnamen(ordner_k) if ist_links and not weg else {k: _ordnername(k) for k in ordner_k}
        for k in sorted((k for k in ordner_k if k in behalten), key=lambda k: (_sortierung(namen[k]), k)):
            n, b, tiefer = werte[k]
            index[k] = len(knoten)
            knoten.append(Knoten((*weg, k), namen[k], ORDNER, n, b, tiefer))
        if _DIREKT in behalten:
            if weg:
                hier = _anzeigename(weg[0]) if ist_links and len(weg) == 1 else weg[-1]
            else:
                hier = daten.ziel
            index[_DIREKT] = len(knoten)
            knoten.append(Knoten(None, name_direkt(_ordnername(hier)), DIREKT, *werte[_DIREKT][:2]))
        if rest:
            index.update({k: len(knoten) for k in rest})
            knoten.append(Knoten(None, meldungen.wohin_weitere(len(rest)), WEITERE,
                                 sum(werte[k][0] for k in rest), sum(werte[k][1] for k in rest), False,
                                 tuple((*weg, k) for k in sorted(rest, key=_sortierung) if k != _DIREKT)))
        for s in KAESTEN:
            k = "\x00" + s
            if k in werte:
                index[k] = len(knoten)
                knoten.append(Knoten(None, meldungen.WOHIN_SCHICKSAL[s], s, *werte[k][:2]))
        return knoten, index

    l_knoten, l_index = knoten_bilden(l_werte, links, True)
    r_knoten, r_index = knoten_bilden(r_werte, rechts, False)
    zusammen: dict[tuple[int, int, str], list[int]] = {}
    for (lk, rk, s), (n, b) in stroeme.items():
        schluessel = (l_index[lk], r_index[rk], s)
        w = zusammen.get(schluessel)
        if w is None:
            zusammen[schluessel] = [n, b]
        else:
            w[0] += n
            w[1] += b
    baender = [Band(li, ri, s, n, b) for (li, ri, s), (n, b) in
               sorted(zusammen.items(), key=lambda t: (t[0][0], t[0][1], _REIHE[t[0][2]]))]
    return Ansicht(l_knoten, r_knoten, baender, links, rechts,
                   sum(k.n for k in l_knoten), sum(k.bytes for k in l_knoten), l_index, r_index)


def _schluessel(kette: tuple, ziel: tuple | None, schicksal: str, links: tuple, rechts: tuple):
    """(linker, rechter) Schluessel einer Zeile in dieser Ansicht - oder None,
    wenn sie nicht hineingehoert."""
    ll, rl = len(links), len(rechts)
    if kette[:ll] != links:
        return None
    if rl and (ziel is None or ziel[:rl] != rechts):
        return None
    lk = kette[ll] if len(kette) > ll else _DIREKT
    if ziel is None:
        rk = "\x00" + schicksal
    else:
        rk = ziel[rl] if len(ziel) > rl else _DIREKT
    return lk, rk


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def band_dateien(dbank: db.Datenbank, ziel: Path, a: Ansicht, band: int, grenze: int = 500) -> tuple[list[Datei], int]:
    """Die Dateien eines Bandes: hoechstens grenze Stueck und die Gesamtzahl.
    Gelesen wird nur der Teil der Tabelle unter dem linken Knoten (Index ueber
    Quellwurzel und Quellpfad); eingeordnet wird jede Zeile wie in lesen()."""
    b = a.baender[band]
    knoten = a.links[b.links]
    sep = os.sep
    if knoten.art == WEITERE:
        wege = list(knoten.mitglieder)
    elif knoten.art == DIREKT:
        wege = [a.pfad_links]
    else:
        wege = [knoten.schluessel]
    einordnen = _Einordner(ziel)
    gesehen: set[str] = set()
    dateien: list[Datei] = []
    gesamt = 0
    dbank.stapel_schreiben()
    for weg in wege:
        wurzel = weg[0]
        if len(weg) == 1:
            sql, werte = f"SELECT {_SPALTEN}, fehlergrund FROM dateien WHERE quellwurzel = ?", [wurzel]
        else:
            anfang = db.text_pfad(wurzel).rstrip(sep) + sep + sep.join(weg[1:]) + sep
            sql = (f"SELECT {_SPALTEN}, fehlergrund FROM dateien WHERE quellwurzel = ?"
                   " AND quellpfad LIKE ? ESCAPE '\\'")
            werte = [wurzel, _like(db.pfad_text(anfang)) + "%"]
        for z in dbank.verbindung.execute(sql, werte):
            if z[1] in gesehen:
                continue
            w, q_ordner, s, z_ordner = einordnen(*z[:5], z[6])
            if s != b.schicksal:
                continue
            quelle, zkette = einordnen.ketten(q_ordner, z_ordner)
            schluessel = _schluessel((w, *quelle), zkette, s, a.pfad_links, a.pfad_rechts)
            if schluessel is None or a.l_index.get(schluessel[0]) != b.links or a.r_index.get(schluessel[1]) != b.rechts:
                continue
            gesehen.add(z[1])
            gesamt += 1
            if len(dateien) < grenze:
                dateien.append(Datei(db.text_pfad(z[1]), db.text_pfad(z[2]) if z[2] else "", s, z[3], z[7] or "",
                                     int(z[5] or 0)))
    dateien.sort(key=lambda x: x.quelle)
    return dateien, gesamt


def suchen(dbank: db.Datenbank, ziel: Path, text: str, grenze: int = 200) -> tuple[list[Datei], int]:
    """Dateien, deren Quellpfad den Text enthaelt (Gross-/Kleinschreibung egal):
    woher, wohin, was passiert ist. Hoechstens grenze Stueck und die Gesamtzahl."""
    text = text.strip()
    if not text:
        return [], 0
    einordnen = _Einordner(ziel)
    dbank.stapel_schreiben()
    muster = "%" + _like(text) + "%"
    gesamt = int(dbank.verbindung.execute(
        "SELECT COUNT(*) FROM dateien WHERE quellpfad LIKE ? ESCAPE '\\'", (muster,)).fetchone()[0])
    dateien = []
    for z in dbank.verbindung.execute(
            f"SELECT {_SPALTEN}, fehlergrund FROM dateien WHERE quellpfad LIKE ? ESCAPE '\\'"
            " ORDER BY quellpfad LIMIT ?", (muster, int(grenze))):
        _w, _q, s, _z = einordnen(*z[:5], z[6])
        dateien.append(Datei(db.text_pfad(z[1]), db.text_pfad(z[2]) if z[2] else "", s, z[3], z[7] or "",
                             int(z[5] or 0)))
    return dateien, gesamt


# --------------------------------------------------------------- Lage ----


def _seitenhoehe(dicken: list[float], zeile: float, abstand: float) -> float:
    return sum(max(d, zeile) for d in dicken) + abstand * max(0, len(dicken) - 1)


def mindesthoehe(a: Ansicht, zeile: float = ZEILE, abstand: float = ABSTAND, min_band: float = MIN_BAND) -> float:
    """So hoch muss die Grafik mindestens sein, damit jede Beschriftung Platz hat."""
    return max(_seitenhoehe(_knotendicken(a, 0.0, min_band)[seite], zeile, abstand) for seite in (0, 1))


def _knotendicken(a: Ansicht, massstab: float, min_band: float) -> tuple[list[float], list[float]]:
    links = [0.0] * len(a.links)
    rechts = [0.0] * len(a.rechts)
    for b in a.baender:
        d = max(b.n * massstab, min_band)
        links[b.links] += d
        rechts[b.rechts] += d
    return links, rechts


def lage(a: Ansicht, breite: float, hoehe: float, x_links: float, x_rechts: float,
         zeile: float = ZEILE, abstand: float = ABSTAND, min_band: float = MIN_BAND,
         knoten_breite: float = KNOTEN_BREITE) -> Lage:
    """Knoten und Baender in Pixeln. x_links: rechte Kante der linken Knoten
    (dort beginnen die Baender), x_rechts: linke Kante der rechten Knoten.
    Der Massstab (Pixel je Datei) ist fuer beide Seiten derselbe, damit jedes
    Band an beiden Enden gleich dick ist; jedes Band ist mindestens min_band
    dick, jeder Knoten hat mindestens eine Zeile Platz fuer seine Schrift."""
    del breite   # die Breite steckt in x_links/x_rechts
    gesamt = max(1, a.n)

    def passt(massstab: float) -> bool:
        l, r = _knotendicken(a, massstab, min_band)
        return max(_seitenhoehe(l, zeile, abstand), _seitenhoehe(r, zeile, abstand)) <= hoehe

    unten, oben = 0.0, hoehe / gesamt
    if passt(oben):
        unten = oben
    else:
        for _ in range(60):
            mitte = (unten + oben) / 2
            if passt(mitte):
                unten = mitte
            else:
                oben = mitte
    massstab = unten
    dicken_l, dicken_r = _knotendicken(a, massstab, min_band)

    def stapeln(dicken: list[float], x: float) -> list[KnotenLage]:
        y = max(0.0, (hoehe - _seitenhoehe(dicken, zeile, abstand)) / 2)
        lagen = []
        for d in dicken:
            platz = max(d, zeile)
            lagen.append(KnotenLage(x, y + (platz - d) / 2, knoten_breite, d, y + platz / 2))
            y += platz + abstand
        return lagen

    l_lage = stapeln(dicken_l, x_links - knoten_breite)
    r_lage = stapeln(dicken_r, x_rechts)
    # Baender an jedem Knoten der Reihe nach stapeln: links nach dem Knoten auf
    # der anderen Seite (wenig Kreuzungen), dann nach Schicksal; rechts ebenso.
    oben_l = [k.y for k in l_lage]
    oben_r = [k.y for k in r_lage]
    enden_l: dict[int, tuple[float, float]] = {}
    enden_r: dict[int, tuple[float, float]] = {}
    for i in sorted(range(len(a.baender)), key=lambda i: (a.baender[i].links, a.baender[i].rechts,
                                                          _REIHE[a.baender[i].schicksal])):
        b = a.baender[i]
        d = max(b.n * massstab, min_band)
        enden_l[i] = (oben_l[b.links], oben_l[b.links] + d)
        oben_l[b.links] += d
    for i in sorted(range(len(a.baender)), key=lambda i: (a.baender[i].rechts, a.baender[i].links,
                                                          _REIHE[a.baender[i].schicksal])):
        b = a.baender[i]
        d = max(b.n * massstab, min_band)
        enden_r[i] = (oben_r[b.rechts], oben_r[b.rechts] + d)
        oben_r[b.rechts] += d
    baender = [BandLage(x_links, x_rechts, *enden_l[i], *enden_r[i]) for i in range(len(a.baender))]
    return Lage(l_lage, r_lage, baender, massstab)


def band_kanten(b: BandLage, x: float) -> tuple[float, float]:
    """Ober- und Unterkante eines Bandes bei x. Die Baender sind kubische
    Kurven mit Stuetzpunkten bei einem und zwei Dritteln der Breite - damit
    ist x linear im Kurvenparameter, und die Hoehe folgt 3u² - 2u³."""
    u = 0.0 if b.x1 == b.x0 else min(1.0, max(0.0, (x - b.x0) / (b.x1 - b.x0)))
    f = u * u * (3 - 2 * u)
    return b.y0o + (b.y1o - b.y0o) * f, b.y0u + (b.y1u - b.y0u) * f


def band_bei(lage_: Lage, x: float, y: float, toleranz: float = 2.0) -> int | None:
    """Das Band unter dem Zeiger: das obenauf gezeichnete (das spaetere). Wer
    knapp daneben zeigt (duenne Baender), bekommt das naechstgelegene."""
    if not lage_.baender or not (lage_.baender[0].x0 <= x <= lage_.baender[0].x1):
        return None
    naechstes, abstand = None, toleranz
    for i in range(len(lage_.baender) - 1, -1, -1):
        oben, unten = band_kanten(lage_.baender[i], x)
        if oben <= y <= unten:
            return i
        weg = oben - y if y < oben else y - unten
        if weg < abstand:
            naechstes, abstand = i, weg
    return naechstes
