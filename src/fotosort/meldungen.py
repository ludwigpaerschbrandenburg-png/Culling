"""Alle deutschen Texte an einer Stelle (docs/architektur.md Abschnitt 1).

Jede Funktion gibt einen fertigen String zurueck. Kein Modul ausserhalb dieser
Datei formuliert eigene Texte fuer den Nutzer.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- Zahlen ----


def anzahl(n: int) -> str:
    """1234 -> "1.234" (Punkt als Tausendertrenner)."""
    return f"{int(n):,}".replace(",", ".")


def groesse(bytes_: int) -> str:
    """1288490189 -> "1,2 GB" (Komma als Dezimaltrenner)."""
    wert = float(bytes_)
    if wert < 1024:
        return f"{int(wert)} B"
    for einheit in ("KB", "MB", "GB", "TB", "PB"):
        wert /= 1024.0
        if wert < 1024 or einheit == "PB":
            return f"{wert:.1f}".replace(".", ",") + f" {einheit}"
    raise AssertionError("unerreichbar")


def dauer(sekunden: float) -> str:
    sekunden = max(0.0, float(sekunden))
    if sekunden < 60:
        return f"{sekunden:.1f}".replace(".", ",") + " s"
    minuten, rest = divmod(int(sekunden), 60)
    stunden, minuten = divmod(minuten, 60)
    if stunden:
        return f"{stunden} h {minuten} min {rest} s"
    return f"{minuten} min {rest} s"


def durchsatz(dateien: int, bytes_: int, sekunden: float) -> str:
    if sekunden <= 0:
        sekunden = 0.001
    pro_sekunde = dateien / sekunden
    mb_pro_sekunde = (bytes_ / 1024 / 1024) / sekunden
    d = f"{pro_sekunde:.1f}".replace(".", ",")
    m = f"{mb_pro_sekunde:.1f}".replace(".", ",")
    return f"{d} Dateien/s, {m} MB/s"


# ------------------------------------------------------------- ExifTool ----


def exiftool_fehlt(gesucht: str = "") -> str:
    """Harter Abbruch, wenn ein Befehl Metadaten braucht (SPEC Abschnitt 2)."""
    wo = gesucht or "ueber PATH"
    return (
        "ExifTool wurde nicht gefunden.\n"
        f"Gesucht wurde: {wo}\n"
        "Ohne ExifTool gibt es weder Aufnahmedatum noch Kamera; alle Dateien\n"
        "landeten unter _Ohne_Datum/Unbekannte_Kamera. Deshalb wird gar nicht\n"
        "erst angefangen.\n"
        "So laesst sich der Pfad setzen:\n"
        "  1. Umgebungsvariable FOTOSORT_EXIFTOOL\n"
        "  2. Konfigurationswert exiftool_pfad in der Gruppe [leistung]\n"
        "Zu beziehen ist ExifTool unter https://exiftool.org"
    )


def exiftool_hinweis(gesucht: str = "") -> str:
    """Weicher Hinweis fuer Befehle, die ohne ExifTool auskommen."""
    wo = gesucht or "ueber PATH"
    return (
        f"Hinweis: ExifTool wurde nicht gefunden (gesucht: {wo}).\n"
        "Dieser Befehl braucht es nicht, aber die Analyse wird ohne ExifTool\n"
        "nicht laufen. Pfad setzbar ueber FOTOSORT_EXIFTOOL oder den\n"
        "Konfigurationswert exiftool_pfad in der Gruppe [leistung]."
    )


# ------------------------------------------------- Lage Quelle und Ziel ----


def quelle_gleich_ziel(pfad) -> str:
    return (
        "Abbruch: Quelle und Ziel sind derselbe Ordner.\n"
        f"  {pfad}\n"
        "Das Programm wuerde Dateien in sich selbst einsortieren. Bitte ein\n"
        "anderes Ziel angeben."
    )


def ziel_in_quelle(ziel) -> str:
    return (
        "Das Ziel liegt innerhalb der Quelle:\n"
        f"  {ziel}\n"
        "Der Zielordner wird vom Scan ausgeschlossen. Der Lauf geht weiter."
    )


def quelle_in_ziel(quelle) -> str:
    return (
        "Abbruch: Die Quelle liegt innerhalb des Ziels.\n"
        f"  {quelle}\n"
        "Das Programm wuerde bereits einsortierte Bilder noch einmal einlesen.\n"
        "Bitte eine Quelle ausserhalb des Ziels angeben."
    )


def datei_zeigt_ins_ziel(pfad) -> str:
    return f"Uebersprungen, weil der Pfad ins Ziel zeigt: {pfad}"


# ------------------------------------------------------------ Datenbank ----


def datenbank_auf_netzlaufwerk(pfad, typ) -> str:
    art = typ if typ else "unbekannt"
    return (
        "Abbruch: Die Datenbank soll auf einem Netzlaufwerk liegen.\n"
        f"  {pfad}\n"
        f"  Dateisystem: {art}\n"
        "Die Datenbank muss immer auf einer lokalen Platte liegen. Ueber das\n"
        "Netz sind die Dateisperren unzuverlaessig; die Datenbank koennte\n"
        "beschaedigt werden, und sie ist das Gedaechtnis des Archivs.\n"
        "Anderer Ort: Umgebungsvariable FOTOSORT_DATENBANK oder der\n"
        "Konfigurationswert datenbank_ort in der Gruppe [datenbank]."
    )


def datenbank_fehlt_sicherung_da(ziel) -> str:
    return (
        "Abbruch: Zu diesem Ziel gibt es eine Archiv-Kennung, aber die lokale\n"
        "Datenbank fehlt. Im Ziel liegt eine Sicherungskopie:\n"
        f"  {ziel}\n"
        "Bitte zuerst zurueckholen mit:\n"
        "  fotosort wiederherstellen --ziel <Ziel>\n"
        "Es wird jetzt keine leere Datenbank angelegt - das Ziel wuerde sonst\n"
        "als leer gelten und alles noch einmal kopiert."
    )


def datenbank_fehlt_keine_sicherung(ziel) -> str:
    return (
        "Abbruch: Zu diesem Ziel gibt es eine Archiv-Kennung, aber weder eine\n"
        "lokale Datenbank noch eine Sicherungskopie im Ziel:\n"
        f"  {ziel}\n"
        "Hier hilft nur der vollstaendige Neuaufbau:\n"
        "  fotosort ziel-index --neu-aufbauen --ziel <Ziel>\n"
        "Es wird jetzt keine leere Datenbank angelegt - das Ziel wuerde sonst\n"
        "als leer gelten und alles noch einmal kopiert."
    )


def datenbank_gesichert(pfad) -> str:
    return f"Sicherungskopie der Datenbank geschrieben: {pfad}"


# ------------------------------------------------------------ Archiv-ID ----


def archiv_id_kaputt(pfad, inhalt) -> str:
    gezeigt = str(inhalt).strip()
    if len(gezeigt) > 120:
        gezeigt = gezeigt[:120] + " ..."
    return (
        "Abbruch: Die Archiv-Kennung des Ziels ist unlesbar.\n"
        f"  Datei:  {pfad}\n"
        f"  Inhalt: {gezeigt!r}\n"
        "Erwartet werden genau 32 Zeichen aus 0-9 und a-f.\n"
        "Es wird bewusst keine neue Kennung erzeugt: Eine neue Kennung zeigte\n"
        "auf eine neue, leere Datenbank; das Programm hielte das Ziel fuer\n"
        "leer und kopierte alles noch einmal."
    )


def archiv_id_angelegt(archiv_id, pfad) -> str:
    return f"Neue Archiv-Kennung angelegt: {archiv_id}\n  in {pfad}"


def archiv_id_fehlt(ziel) -> str:
    return (
        "Abbruch: In diesem Ziel gibt es noch kein Archiv.\n"
        f"  {ziel}\n"
        "Ein Archiv entsteht beim ersten Scan:\n"
        "  fotosort scan --quelle <Quelle> --ziel <Ziel>"
    )


# -------------------------------------------------------- Konfiguration ----


def config_erzeugt(pfad) -> str:
    return f"Neue Konfiguration mit Standardwerten angelegt: {pfad}"


def config_aus_ziel_uebernommen(pfad) -> str:
    return (
        "Die Konfiguration aus dem Ziel wurde uebernommen, statt eine neue\n"
        f"anzulegen: {pfad}"
    )


def config_unbekannte_werte(namen: list[str], pfad) -> str:
    liste = ", ".join(str(n) for n in namen)
    return (
        f"Hinweis: In der Konfiguration stehen unbekannte Werte: {liste}\n"
        f"  {pfad}\n"
        "Sie bleiben unangetastet stehen und wirken nicht. Meist ist es ein\n"
        "Tippfehler im Schluesselnamen."
    )


def config_datenbank_ort_ignoriert(pfad) -> str:
    return (
        "Hinweis: Der Wert datenbank_ort steht in der Konfiguration im\n"
        f"Archiv-Ordner selbst und wird ignoriert: {pfad}\n"
        "Der Ordner ist an dieser Stelle bereits gefunden; die Konfiguration\n"
        "kann ihn nicht selbst verschieben. Wirksam ist er nur aus einer mit\n"
        "--config angegebenen Datei."
    )


def editor_nicht_gefunden(pfad) -> str:
    return (
        "Es konnte kein Editor geoeffnet werden. Die Datei laesst sich von\n"
        f"Hand oeffnen: {pfad}"
    )


# -------------------------------------------------------------- Aufrufe ----


def ziel_fehlt() -> str:
    return (
        "Es fehlt die Angabe des Ziels.\n"
        "  fotosort <befehl> --ziel <Zielordner>\n"
        "Ersatzweise laesst sich das Ziel in der Umgebungsvariablen\n"
        "FOTOSORT_ZIEL hinterlegen; --ziel hat Vorrang."
    )


def quelle_fehlt() -> str:
    return (
        "Es fehlt die Angabe der Quelle.\n"
        "  fotosort scan --quelle <Quellordner> --ziel <Zielordner>\n"
        "Nur der Scan braucht die Quelle; sie wird in der Datenbank gemerkt."
    )


def quelle_existiert_nicht(pfad) -> str:
    return f"Abbruch: Diesen Quellordner gibt es nicht:\n  {pfad}"


def ziel_existiert_nicht(pfad) -> str:
    return f"Abbruch: Diesen Zielordner gibt es nicht:\n  {pfad}"


def noch_nicht_gebaut(befehl, phase: int) -> str:
    return (
        f"Der Befehl „{befehl}“ ist noch nicht gebaut. Er kommt in Phase {phase}.\n"
        "Fertig sind bisher: scan, status und config."
    )


# ----------------------------------------------------------------- Scan ----


def scan_beginnt(quelle, ziel) -> str:
    return f"Scan laeuft.\n  Quelle: {quelle}\n  Ziel:   {ziel}"


def scan_laeuft(gefunden: int) -> str:
    return f"{anzahl(gefunden)} Dateien gefunden"


def scan_abgebrochen() -> str:
    return (
        "Abgebrochen. Das Bisherige ist gespeichert; ein neuer Scan derselben\n"
        "Quelle macht genau dort weiter."
    )


def scan_ergebnis(
    dateien: int,
    bytes_: int,
    je_typ: dict[str, int],
    sekunden: float,
) -> str:
    zeilen = [
        "",
        "Ergebnis des Scans",
        f"  Dateien gesamt:  {anzahl(dateien)}",
        f"  Gesamtgroesse:   {groesse(bytes_)}",
        "  Aufteilung nach Typ:",
    ]
    for typ in ("foto", "raw", "video", "sidecar", "sonstiges"):
        zeilen.append(f"    {typ:<10} {anzahl(je_typ.get(typ, 0)):>12}")
    zeilen.append(f"  Dauer:           {dauer(sekunden)}")
    zeilen.append(f"  Durchsatz:       {durchsatz(dateien, bytes_, sekunden)}")
    return "\n".join(zeilen)


def scan_besonderheiten(
    neu: int,
    unveraendert: int,
    veraendert: int,
    verschwunden: int,
    ausgeschlossen: int,
    verknuepfungen: int,
    ins_ziel: int,
    fehler: int,
    ordner_nicht_lesbar: int = 0,
    verschwunden_ausgewertet: bool = True,
) -> str:
    zeilen = ["", "Dazu im Einzelnen"]
    zeilen.append(f"  neu aufgenommen:              {anzahl(neu)}")
    zeilen.append(f"  unveraendert uebernommen:     {anzahl(unveraendert)}")
    zeilen.append(f"  veraendert, neu einzuordnen:  {anzahl(veraendert)}")
    if verschwunden_ausgewertet:
        zeilen.append(f"  Quelle nicht mehr vorhanden:  {anzahl(verschwunden)}")
    else:
        zeilen.append("  Quelle nicht mehr vorhanden:  nicht geprueft")
    zeilen.append(f"  nach Muster ausgeschlossen:   {anzahl(ausgeschlossen)}")
    zeilen.append(f"  Verknuepfungen nicht verfolgt:{anzahl(verknuepfungen):>6}")
    zeilen.append(f"  zeigt ins Ziel, uebersprungen:{anzahl(ins_ziel):>6}")
    zeilen.append(f"  nicht lesbar (Fehler):        {anzahl(fehler)}")
    zeilen.append(f"  Ordner nicht lesbar:          {anzahl(ordner_nicht_lesbar)}")
    return "\n".join(zeilen)


def scan_ordner_nicht_lesbar(anzahl_ordner: int, beispiele: list) -> str:
    """Mindestens ein Ordner liess sich nicht oeffnen (SPEC Abschnitt 4 Phase 1).

    Das ist der Windows-Langpfad- und der Netzlaufwerk-Aussetzer-Fall. Der
    Scan hat dann nicht alles gesehen; das muss der Nutzer erfahren.
    """
    satz = (
        "1 Ordner liess sich nicht oeffnen"
        if anzahl_ordner == 1
        else f"{anzahl(anzahl_ordner)} Ordner liessen sich nicht oeffnen"
    )
    zeilen = [
        "",
        f"Achtung: {satz}.",
        "Was darin liegt, ist nicht erfasst worden. Der Scan ist damit nicht",
        "vollstaendig.",
    ]
    for pfad in beispiele:
        zeilen.append(f"  {pfad}")
    if len(beispiele) < anzahl_ordner:
        zeilen.append(f"  ... und {anzahl(anzahl_ordner - len(beispiele))} weitere")
    zeilen.append("Haeufige Ursachen: fehlende Leserechte, ein Netzlaufwerk mit")
    zeilen.append("kurzem Aussetzer, oder ein zu langer Pfad.")
    zeilen.append("Die Liste \u201eQuelle nicht mehr vorhanden\u201c wird deshalb nicht")
    zeilen.append("ausgewertet: Dateien in einem ungelesenen Ordner gelten sonst")
    zeilen.append("faelschlich als verschwunden.")
    return "\n".join(zeilen)


def scan_alles_ausgeschlossen(muster: list) -> str:
    """Die Ausschlussmuster haben die ganze Quelle getroffen."""
    liste = ", ".join(repr(str(m)) for m in muster)
    return (
        "Achtung: Es ist keine einzige Datei uebrig geblieben - die\n"
        f"Ausschlussmuster treffen die gesamte Quelle: {liste}\n"
        "Zu pruefen ist der Wert ausschlussmuster in der Gruppe [quelle]."
    )


# --------------------------------------------------------------- Status ----

# Reihenfolge der Stufen aus SPEC Abschnitt 8; die uebrigen Status sind
# Abzweigungen und zaehlen fuer die Phase nicht mit.
PHASE_JE_STATUS: dict[str, tuple[int, str]] = {
    "gefunden": (2, "Analyse offen"),
    "analysiert": (3, "Kopieren offen"),
    "kopieren_laeuft": (3, "Kopieren offen (ein Lauf wurde abgebrochen)"),
    "kopiert": (4, "Pruefen offen"),
    "geprueft": (5, "Quelle aufraeumen offen"),
    "quelle_geloescht": (6, "Leere Ordner entfernen offen"),
}


def status_phase(niedrigster: str | None, dateien_erfasst: bool = False) -> str:
    """Die aktuelle Phase (SPEC Abschnitt 8).

    Steht keine Datei in einer Stufe, haengt der Klammerzusatz davon ab, ob
    ueberhaupt schon Dateien erfasst sind: Stehen alle Zeilen in einem
    Abzweig-Status (uebersprungen, fehler ...), sind sie sehr wohl erfasst.
    """
    if niedrigster is None:
        if dateien_erfasst:
            return (
                "Aktuelle Phase: 1 - Scan offen (erfasste Dateien stehen alle in\n"
                "einem Status, der keine Stufe ist - etwa uebersprungen oder fehler)"
            )
        return "Aktuelle Phase: 1 - Scan offen (es sind noch keine Dateien erfasst)"
    phase, text = PHASE_JE_STATUS[niedrigster]
    return f"Aktuelle Phase: {phase} - {text}"


def status_zaehler(zaehler: dict[str, int]) -> str:
    zeilen = ["Dateien je Status"]
    for name, wert in zaehler.items():
        zeilen.append(f"  {name:<20} {anzahl(wert):>12}")
    return "\n".join(zeilen)


def status_letzter_lauf(nummer, befehl, start, ende) -> str:
    if nummer is None:
        return "Es gab noch keinen Lauf."
    schluss = ende if ende else "nicht beendet (abgebrochen oder abgestuerzt)"
    return (
        "Letzter Lauf\n"
        f"  Nummer:  {nummer}\n"
        f"  Befehl:  {befehl}\n"
        f"  Start:   {start}\n"
        f"  Ende:    {schluss}"
    )


# --------------------------------------------------------------- config ----


def config_pfad_zeigen(pfad: Path) -> str:
    return f"Die geltende Konfiguration liegt hier:\n  {pfad}"


def config_wird_geoeffnet(pfad: Path) -> str:
    return f"Wird im Editor geoeffnet: {pfad}"


# ----------------------------------------------------------- Archivsperre ----


def archiv_belegt(pfad) -> str:
    """Ein zweiter Lauf auf dasselbe Archiv (SPEC Abschnitt 6)."""
    return (
        "Fuer dieses Archiv laeuft bereits ein Vorgang.\n"
        f"  {pfad}\n"
        "Es kann immer nur ein Lauf gleichzeitig an einem Archiv arbeiten;\n"
        "sonst kaemen sich die Schreibvorgaenge in die Quere und die\n"
        "Datenbank - das Gedaechtnis des Archivs - koennte Schaden nehmen.\n"
        "Bitte warten, bis der andere Lauf fertig ist, und es dann erneut\n"
        "versuchen."
    )


def datenbank_belegt(pfad) -> str:
    """SQLite meldet die Datenbank als gesperrt."""
    return (
        "Die Datenbank des Archivs ist gerade belegt.\n"
        f"  {pfad}\n"
        "Vermutlich arbeitet ein zweiter Lauf daran. Es wurde nichts\n"
        "veraendert; bitte spaeter noch einmal versuchen."
    )


# ---------------------------------------------------- Fehler des Systems ----


def system_fehler(pfad, grund: str) -> str:
    """Ein Fehler des Betriebssystems, in verstaendlichen Worten."""
    return (
        "Abbruch: Auf diesen Pfad konnte nicht zugegriffen werden.\n"
        f"  {pfad}\n"
        f"  Grund: {grund}\n"
        "Haeufige Ursachen: fehlende Rechte, ein Netzlaufwerk, das gerade\n"
        "nicht erreichbar ist, oder ein Name, der auf eine Datei statt auf\n"
        "einen Ordner zeigt."
    )


def config_kaputt(pfad, zeile, spalte, grund: str) -> str:
    """Tippfehler in der von Hand gepflegten config.toml."""
    stelle = ""
    if zeile is not None:
        stelle = f"  Stelle: Zeile {zeile}, Spalte {spalte}\n"
    return (
        "Abbruch: Die Konfigurationsdatei laesst sich nicht lesen.\n"
        f"  Datei:  {pfad}\n"
        f"{stelle}"
        f"  Grund:  {grund}\n"
        "Die Datei bleibt unveraendert stehen - es wird nichts ueberschrieben.\n"
        "Meist fehlt ein Anfuehrungszeichen, eine eckige Klammer oder ein\n"
        "Gleichheitszeichen. Nach dem Berichtigen laeuft der Befehl wieder."
    )


def config_falscher_typ(schluessel: str, gefunden: str, erwartet: str, pfad) -> str:
    """Ein Konfigurationswert hat die falsche Art (Liste, Wahrheitswert ...)."""
    return (
        "Abbruch: Ein Wert in der Konfiguration hat die falsche Form.\n"
        f"  Datei:     {pfad}\n"
        f"  Schluessel: {schluessel}\n"
        f"  gefunden:  {gefunden}\n"
        f"  erwartet:  {erwartet}\n"
        "Der Wert wird nicht benutzt, weil eine falsche Form die Bedeutung\n"
        'umkehren kann: Eine Zeichenkette statt einer Liste wird Zeichen fuer\n'
        'Zeichen gelesen, und aus "nein" wird ein Ja.\n'
        "Die Datei bleibt unveraendert stehen."
    )


# -------------------------------------------------------- Ziel anlegen ----


def ziel_wird_nicht_angelegt(ziel) -> str:
    """Ein nicht vorhandenes Ziel wird nicht stillschweigend angelegt."""
    return (
        "Abbruch: Diesen Zielordner gibt es nicht:\n"
        f"  {ziel}\n"
        "Er wird bewusst nicht von selbst angelegt. Ein Tippfehler im Pfad -\n"
        "oder ein Netzlaufwerk, das gerade nicht eingebunden ist - ergaebe\n"
        "sonst ein zweites, leeres Archiv mit einer neuen Kennung; das\n"
        "richtige Archiv gaelte danach als unbekannt und alles wuerde noch\n"
        "einmal kopiert.\n"
        "Ist der Pfad richtig und der Ordner soll wirklich neu entstehen:\n"
        "  fotosort scan --quelle <Quelle> --ziel <Ziel> --ziel-anlegen"
    )


def ziel_eltern_fehlt(ziel, eltern) -> str:
    return (
        "Abbruch: Der Ordner, in dem das Ziel angelegt werden soll, gibt es\n"
        "nicht:\n"
        f"  Ziel:          {ziel}\n"
        f"  fehlender Ort: {eltern}\n"
        "Bitte den Pfad pruefen. Liegt das Ziel auf einem Netzlaufwerk, ist\n"
        "es vermutlich gerade nicht eingebunden."
    )


def ziel_angelegt(ziel) -> str:
    return f"Neuer Zielordner angelegt: {ziel}"


# ------------------------------------------------------------- Abbrueche ----


def lauf_abgebrochen_vermerkt() -> str:
    return "Der Lauf wurde als sauber abgebrochen vermerkt."


def abbruch_durch_signal() -> str:
    """SIGTERM - das Signal von "docker stop" und von TrueNAS."""
    return (
        "Das Programm wurde vom System zum Beenden aufgefordert.\n"
        "Das Bisherige ist gespeichert; ein neuer Lauf macht dort weiter."
    )


# ---------------------------------------------------------- Quellen -----


def datenbank_schema_veraltet(pfad, gefunden: int, erwartet: int) -> str:
    return (
        f"Die Datenbank {pfad} stammt aus einem frueheren Stand des Programms\n"
        f"(Schema-Version {gefunden}, erwartet {erwartet}). Sie wird nicht\n"
        "stillschweigend weiterbenutzt. Da es noch keine echten Archive gibt,\n"
        "hilft: den Archiv-Ordner loeschen und neu scannen."
    )


def quelle_nicht_erreichbar(pfad) -> str:
    return (
        f"Quelle nicht erreichbar: {pfad}\n"
        "  Sie bleibt bekannt und wird uebersprungen. Ihre Dateien gelten\n"
        "  nicht als verschwunden. Platte eingesteckt, Netzlaufwerk eingebunden?"
    )


def quelle_abgelehnt_ueberschneidung(pfad, andere) -> str:
    return (
        f"Quelle abgelehnt: {pfad}\n"
        f"  Sie ueberschneidet sich mit der Quelle {andere}. Dieselbe Datei\n"
        "  wuerde sonst zweimal erfasst. Die uebrigen Quellen laufen weiter."
    )


def keine_quellen_bekannt() -> str:
    return (
        "Dieses Archiv kennt noch keine Quelle. Beim ersten Scan muss\n"
        "mindestens eine angegeben werden: fotosort scan --quelle <Ordner> --ziel <Ziel>"
    )


def scan_quellen_beginnt(quellen: list, ziel) -> str:
    zeilen = ["Scan laeuft."]
    for q in quellen:
        zeilen.append(f"  Quelle: {q}")
    zeilen.append(f"  Ziel:   {ziel}")
    return "\n".join(zeilen)


def scan_neue_quellen(neue: list) -> str:
    if not neue:
        return ""
    zeilen = [f"Neu aufgenommene Quelle{'n' if len(neue) != 1 else ''}:"]
    zeilen += [f"  {q}" for q in neue]
    return "\n".join(zeilen)


def scan_laufwerke(anzahl_laufwerke: int, anzahl_quellen: int) -> str:
    if anzahl_quellen <= 1:
        return ""
    if anzahl_laufwerke == 1:
        return f"{anzahl(anzahl_quellen)} Quellen auf einem Laufwerk, nacheinander gelesen."
    return (
        f"{anzahl(anzahl_quellen)} Quellen auf {anzahl(anzahl_laufwerke)} Laufwerken,"
        " je Laufwerk parallel gelesen."
    )


def scan_je_quelle(je_quelle: dict) -> str:
    """Eine Zeile je Quelle: Dateien, Groesse, neu/unveraendert/veraendert."""
    if len(je_quelle) <= 1:
        return ""
    zeilen = ["Je Quelle"]
    for wurzel, e in je_quelle.items():
        zeilen.append(f"  {wurzel}")
        zeilen.append(
            f"    {anzahl(e.dateien)} Dateien, {groesse(e.bytes_gesamt)}"
            f" — neu {anzahl(e.neu)}, unveraendert {anzahl(e.unveraendert)},"
            f" veraendert {anzahl(e.veraendert)}"
            + (f", nicht mehr vorhanden {anzahl(e.verschwunden)}" if e.verschwunden_ausgewertet else "")
            + (f", Fehler {anzahl(e.fehler)}" if e.fehler else "")
        )
    return "\n".join(zeilen)


def scan_nichts_zu_tun(abgelehnt: list, nicht_erreichbar: list) -> str:
    return (
        "Keine Quelle konnte durchlaufen werden"
        f" ({anzahl(len(abgelehnt))} abgelehnt, {anzahl(len(nicht_erreichbar))} nicht erreichbar)."
    )


def status_je_quelle(quellen: list, je_quelle: dict, je_status: dict) -> str:
    """Fuer 'fotosort status': eine Zeile je bekannter Quelle."""
    if not quellen:
        return "Quellen: noch keine bekannt."
    zeilen = ["Quellen"]
    for z in quellen:
        wurzel = z["wurzel"]
        zaehler = je_quelle.get(wurzel, {})
        stati = je_status.get(wurzel, {})
        stand = "erreichbar" if int(z["erreichbar"] or 0) else "NICHT ERREICHBAR beim letzten Scan"
        zeilen.append(f"  {wurzel}  ({stand})")
        zeilen.append(
            f"    {anzahl(zaehler.get('gesamt', 0))} Dateien, {groesse(zaehler.get('bytes', 0))}"
            + (
                "  —  " + ", ".join(f"{s} {anzahl(n)}" for s, n in sorted(stati.items()))
                if stati
                else ""
            )
        )
    return "\n".join(zeilen)


# ---------------------------------------------------------- Analyse -----


def analyse_beginnt(prozesse: int, offen: int) -> str:
    return (
        f"Analyse laeuft: {anzahl(offen)} Dateien zu bearbeiten,"
        f" {anzahl(prozesse)} ExifTool-Prozess{'e' if prozesse != 1 else ''}."
    )


def analyse_laeuft(bisher: int, gesamt: int) -> str:
    return f"Analyse: {anzahl(bisher)} von {anzahl(gesamt)} Dateien"


def analyse_nichts_zu_tun() -> str:
    return "Nichts zu analysieren: Es gibt keine Dateien mit Status gefunden."


def analyse_abgebrochen() -> str:
    return "Abgebrochen. Das Bisherige ist gespeichert; der naechste Lauf macht dort weiter."


def analyse_ergebnis(e) -> str:
    """Zaehler dieses Laufs (ein analyse.Ergebnis)."""
    zeilen = [
        "Ergebnis der Analyse (dieser Lauf)",
        f"  bearbeitet:                  {anzahl(e.bearbeitet)}",
        f"  Gruppen (RAW+JPG, Sidecars): {anzahl(e.gruppen)}",
        f"  Sidecars ohne Hauptdatei:    {anzahl(e.sidecar_ohne_haupt)}",
        f"  Fehler (nicht lesbar):       {anzahl(e.fehler)}",
        f"  Zielordner mit Zusatz wiederverwendet: {anzahl(e.wiederverwendet)}",
    ]
    if e.mehrdeutig:
        zeilen.append(f"  davon mehrdeutig (alphabetisch gewaehlt): {anzahl(e.mehrdeutig)}")
    zeilen.append(f"  Dauer:           {dauer(e.sekunden)}")
    if e.sekunden > 0:
        zeilen.append(f"  Durchsatz:       {e.bearbeitet / e.sekunden:,.1f} Dateien/s".replace(",", "."))
    zeilen.append(f"  ExifTool-Prozesse: {anzahl(e.prozesse)}")
    return "\n".join(zeilen)


def analyse_zusammenfassung(z: dict) -> str:
    """Der Plan als Ganzes (alle analysierten Dateien, nicht nur dieser Lauf)."""
    zeilen = ["Zusammenfassung des Plans"]
    je = z.get("je_jahr_quelle", {})
    jahre: dict[str, int] = {}
    for wurzel, nach_jahr in je.items():
        for jahr, n in nach_jahr.items():
            jahre[jahr] = jahre.get(jahr, 0) + n
    zeilen.append("  Dateien pro Jahr (gesamt):")
    for jahr in sorted(jahre, key=lambda j: (j == "ohne Datum", j)):
        zeilen.append(f"    {jahr:<12}{anzahl(jahre[jahr]):>8}")
    if len(je) > 1:
        zeilen.append("  Dateien pro Jahr je Quelle:")
        for wurzel in sorted(je):
            zeilen.append(f"    {wurzel}")
            for jahr in sorted(je[wurzel], key=lambda j: (j == "ohne Datum", j)):
                zeilen.append(f"      {jahr:<12}{anzahl(je[wurzel][jahr]):>8}")
    zeilen.append("  Gefundene Kameramodelle (Modell -> Ordner):")
    for roh, ordner, n in z.get("modelle", []):
        zeilen.append(f"    {(roh or '(kein Modell)'):<28} -> {ordner:<20}{anzahl(n):>8}")
    zeilen.append(
        "  Aliase fuer unbekannte Modelle traegt man in der config.toml unter"
        " [kamera.aliase] nach (fotosort config), BEVOR kopiert wird."
    )
    zeilen.append(f"  Ohne sicheres Datum (nur Aenderungsdatum):    {anzahl(z.get('unsicher', 0))}")
    zeilen.append(f"  Namenskonflikte (gleicher Zielname, Phase 3): {anzahl(z.get('namenskonflikte', 0))}")
    zeilen.append(
        f"  Moegliche Duplikate (SCHAETZUNG: gleiche Groesse und Aufnahmezeit;"
        f" sicher weiss es erst Phase 3 ueber den Hash): {anzahl(z.get('moegliche_duplikate', 0))}"
    )
    zeilen.append(f"  Zeitzone angenommen (Video ohne Offset):     {anzahl(z.get('zeitzone_angenommen', 0))}")
    zeilen.append(f"  Datum aus Dateiname ohne Uhrzeit:            {anzahl(z.get('ohne_uhrzeit', 0))}")
    zeilen.append(f"  Sidecars ohne Hauptdatei:                    {anzahl(z.get('sidecar_ohne_haupt', 0))}")
    zeilen.append(f"  Fehler:                                      {anzahl(z.get('fehler', 0))}")
    zeilen.append(f"  Noch nicht analysiert:                       {anzahl(z.get('offen', 0))}")
    return "\n".join(zeilen)


def abbruch_allgemein() -> str:
    return "Abgebrochen. Das Bisherige ist gespeichert; der naechste Lauf macht dort weiter."


def zeitzone_ungueltig(name) -> str:
    return (
        f"Die Heimat-Zeitzone \"{name}\" ist unbekannt (config.toml, [datum] heimat_zeitzone).\n"
        "Erwartet wird ein Name wie \"Europe/Berlin\". Ohne gueltige Zeitzone wuerden alle\n"
        "Videos ohne Offset falsch einsortiert; deshalb wird abgebrochen."
    )


# --------------------------------------------------------- Kopieren -----

# Texte, die beim Kopieren in die Datenbank gelangen (fehlergrund, Ereignistext).
GRUND_QUELLE_FEHLT = "Quelldatei nicht gefunden"
GRUND_QUELLE_WAEHREND_KOPIE = "Quelle hat sich waehrend des Kopierens veraendert"
GRUND_KOPIE = "Kopieren fehlgeschlagen"
GRUND_PART_BELEGT = "Zwischendatei (.part) ist von einem anderen Vorgang belegt"
GRUND_PART_INHALT = "Inhalt der .part-Datei stimmt nicht mehr"
EREIGNIS_PART_AUFGERAEUMT = "liegengebliebene .part-Datei entfernt"
EREIGNIS_ANGEFANGENE_ENTFERNT = "angefangene Zieldatei aus abgebrochenem Lauf entfernt"
EREIGNIS_NACHTRAEGLICH = "Kopie aus abgebrochenem Lauf war vollstaendig"
EREIGNIS_RUECKFALL_ORDNER = "Dateisystem kann kein nicht ueberschreibendes Umbenennen"
EREIGNIS_RUECKFALL_ZIEL = "Ziel kann kein nicht ueberschreibendes Umbenennen: ohne .part, exklusiv angelegt"
EREIGNIS_QUELLE_UEBERSPRUNGEN = "nicht erreichbar, uebersprungen"


def profil_ungueltig(profil, erlaubt: list) -> str:
    return (
        f"Unbekanntes Profil {profil!r}. Erlaubt sind: {', '.join(erlaubt)}"
        " (Befehlszeile --profil oder config.toml unter [leistung])."
    )


def zu_wenig_platz(ziel, benoetigt: int, frei: int) -> str:
    return (
        f"Zu wenig Platz im Ziel {ziel}: benoetigt werden bis zu {groesse(benoetigt)},"
        f" frei sind {groesse(frei)}. Es wurde nichts kopiert."
    )


def kopieren_beginnt(dateien: int, bytes_: int, kopier_worker: int, hash_worker: int,
                     profil: str, direkt: bool) -> str:
    zeilen = [
        f"Kopieren laeuft: {anzahl(dateien)} Dateien, {groesse(bytes_)}."
        f" Profil {profil}: {anzahl(kopier_worker)} Kopier-Worker, {anzahl(hash_worker)} Hash-Worker."
    ]
    if direkt:
        zeilen.append(
            "Hinweis: Das Ziel kann kein nicht ueberschreibendes Umbenennen (z. B. exFAT/FAT32)."
            " Es wird ohne .part-Datei direkt und exklusiv unter dem endgueltigen Namen angelegt."
        )
    return "\n".join(zeilen)


def kopieren_laeuft(dateien: int, gesamt: int, bytes_: int, gesamt_bytes: int, bytes_pro_s: float) -> str:
    mb = f"{bytes_pro_s / 1024 / 1024:.1f}".replace(".", ",")
    return (
        f"Kopieren: {anzahl(dateien)} von {anzahl(gesamt)} Dateien,"
        f" {groesse(bytes_)} von {groesse(gesamt_bytes)}, {mb} MB/s"
    )


def restzeit(sekunden: float) -> str:
    return f"noch etwa {dauer(sekunden)}"


def kopieren_nichts_zu_tun() -> str:
    return "Nichts zu kopieren: Es gibt keine Dateien mit Status analysiert."


def kopieren_abgebrochen() -> str:
    return (
        "Abgebrochen. Angefangene Kopien wurden entfernt, fertige bleiben;"
        " der naechste Lauf macht dort weiter."
    )


def quellen_uebersprungen(quellen: list) -> str:
    zeilen = ["Nicht erreichbare Quellen (uebersprungen, ihre Dateien bleiben offen):"]
    zeilen.extend(f"  {q}" for q in quellen)
    return "\n".join(zeilen)


def kopieren_plan(plan) -> str:
    """--dry-run: was passieren wuerde."""
    zeilen = [
        "Probelauf (--dry-run): Es wird nichts kopiert und kein Lauf angelegt.",
        f"  zu kopieren:                         {anzahl(plan.dateien)} Dateien, {groesse(plan.bytes)}",
    ]
    if len(plan.je_quelle) > 1:
        for wurzel, (n, b) in sorted(plan.je_quelle.items()):
            zeilen.append(f"    {wurzel}: {anzahl(n)} Dateien, {groesse(b)}")
    zeilen.append(
        f"  Zielname schon belegt (wird Duplikat oder bekommt _1): {anzahl(plan.zielname_belegt)}"
    )
    if plan.liegengeblieben:
        zeilen.append(
            f"  Reste eines abgebrochenen Laufs (werden zuerst aufgeraeumt): {anzahl(plan.liegengeblieben)}"
        )
    if plan.quellen_nicht_erreichbar:
        zeilen.append("")
        zeilen.append(quellen_uebersprungen(plan.quellen_nicht_erreichbar))
    return "\n".join(zeilen)


def kopieren_ergebnis(e) -> str:
    """Zaehler dieses Laufs (ein kopieren.Ergebnis)."""
    zeilen = [
        "Ergebnis des Kopierens (dieser Lauf)",
        f"  angestanden:                 {anzahl(e.geplant)} Dateien, {groesse(e.geplant_bytes)}",
        f"  kopiert:                     {anzahl(e.kopiert)} Dateien, {groesse(e.bytes_kopiert)}",
        f"  Duplikate (Inhalt war schon im Ziel, nicht kopiert): {anzahl(e.duplikate)}",
        f"  Namenskonflikte (mit Anhang _1, _2 ... abgelegt):    {anzahl(e.namenskonflikte)}",
        f"  Quelle seit der Analyse veraendert (neu einordnen):  {anzahl(e.quelle_veraendert)}",
        f"  Fehler:                      {anzahl(e.fehler)}",
    ]
    if e.part_aufgeraeumt or e.angefangene_entfernt or e.nachtraeglich_bestaetigt:
        zeilen.append("  Reste eines abgebrochenen Laufs:")
        if e.part_aufgeraeumt:
            zeilen.append(f"    .part-Dateien entfernt:                 {anzahl(e.part_aufgeraeumt)}")
        if e.angefangene_entfernt:
            zeilen.append(f"    angefangene Zieldateien entfernt:       {anzahl(e.angefangene_entfernt)}")
        if e.nachtraeglich_bestaetigt:
            zeilen.append(f"    fertige Kopien nachtraeglich bestaetigt: {anzahl(e.nachtraeglich_bestaetigt)}")
    if e.exfat_rueckfall:
        zeilen.append("  Rueckfall ohne .part (Ziel kann kein nicht ueberschreibendes Umbenennen): ja")
    zeilen.append(f"  Dauer:           {dauer(e.sekunden)}")
    if e.sekunden > 0:
        zeilen.append(f"  Durchsatz:       {durchsatz(e.kopiert, e.bytes_kopiert, e.sekunden)}")
    zeilen.append(
        f"  Worker:          {anzahl(e.kopier_worker)} Kopier-Worker, {anzahl(e.hash_worker)} Hash-Worker"
        f" (Profil {e.profil})"
    )
    return "\n".join(zeilen)


def kopieren_zusammenfassung(z: dict) -> str:
    """Stand des ganzen Archivs nach dem Lauf."""
    status = z.get("status", {})
    zeilen = [
        "Stand des Archivs",
        f"  kopiert (Pruefen offen):     {anzahl(status.get('kopiert', 0))} Dateien, {groesse(z.get('kopiert_bytes', 0))}",
        f"  Duplikate:                   {anzahl(status.get('duplikat', 0))}",
        f"  noch zu kopieren:            {anzahl(status.get('analysiert', 0))}",
        f"  Fehler:                      {anzahl(status.get('fehler', 0))}",
    ]
    je = z.get("je_quelle", {})
    if len(je) > 1:
        zeilen.append("  je Quelle (kopiert / Duplikate / offen / Fehler):")
        for wurzel in sorted(je):
            s = je[wurzel]
            zeilen.append(
                f"    {wurzel}: {anzahl(s.get('kopiert', 0))} / {anzahl(s.get('duplikat', 0))}"
                f" / {anzahl(s.get('analysiert', 0))} / {anzahl(s.get('fehler', 0))}"
            )
    return "\n".join(zeilen)


# ---------------------------------------------------------- Pruefen -----

GRUND_PRUEFUNG = "Zielpruefung fehlgeschlagen"
GRUND_PRUEFUNG_FEHLT = f"{GRUND_PRUEFUNG}: Zieldatei fehlt"
GRUND_PRUEFUNG_INHALT = f"{GRUND_PRUEFUNG}: Inhalt weicht ab (Hash ungleich)"
GRUND_PRUEFUNG_LESEN = f"{GRUND_PRUEFUNG}: Zieldatei nicht lesbar"
EREIGNIS_NEU_NACH_PRUEFUNG = "nach fehlgeschlagener Pruefung neu zu kopieren"


def grund_pruefung_groesse(erwartet: int, gefunden: int) -> str:
    art = "abgeschnitten" if gefunden < erwartet else "groesser als die Quelle"
    return f"{GRUND_PRUEFUNG}: Groesse weicht ab ({art}: {anzahl(gefunden)} statt {anzahl(erwartet)} Byte)"


def pruefen_beginnt(dateien: int, bytes_: int, hash_worker: int, profil: str) -> str:
    return (
        f"Pruefen laeuft: {anzahl(dateien)} Dateien, {groesse(bytes_)} werden vollstaendig neu gelesen."
        f" Profil {profil}: {anzahl(hash_worker)} Hash-Worker."
    )


def pruefen_laeuft(dateien: int, gesamt: int, bytes_: int, gesamt_bytes: int, bytes_pro_s: float) -> str:
    mb = f"{bytes_pro_s / 1024 / 1024:.1f}".replace(".", ",")
    return (
        f"Pruefen: {anzahl(dateien)} von {anzahl(gesamt)} Dateien,"
        f" {groesse(bytes_)} von {groesse(gesamt_bytes)}, {mb} MB/s"
    )


def pruefen_nichts_zu_tun() -> str:
    return "Nichts zu pruefen: Es gibt keine Dateien mit Status kopiert, duplikat oder verschoben."


def pruefen_abgebrochen() -> str:
    return "Abgebrochen. Das Bisherige ist gespeichert; der naechste Lauf prueft die uebrigen Dateien."


def pruefen_ergebnis(e) -> str:
    """Zaehler dieses Laufs (ein pruefen.Ergebnis)."""
    zeilen = [
        "Ergebnis des Pruefens (dieser Lauf)",
        f"  angestanden:                 {anzahl(e.geplant)} Dateien, {groesse(e.geplant_bytes)}",
        f"  geprueft (Zieldatei stimmt): {anzahl(e.geprueft)}",
        f"  Duplikate bestaetigt (Partnerdatei stimmt): {anzahl(e.duplikate_bestaetigt)}",
        f"  verschobene Dateien gehasht: {anzahl(e.verschoben_gehasht)}",
        f"  Fehler:                      {anzahl(e.fehler)}",
    ]
    if e.fehler:
        zeilen.append(f"    Zieldatei fehlt:           {anzahl(e.fehler_fehlt)}")
        zeilen.append(f"    Groesse weicht ab:         {anzahl(e.fehler_groesse)}")
        zeilen.append(f"    Inhalt weicht ab:          {anzahl(e.fehler_inhalt)}")
        if e.fehler_lesen:
            zeilen.append(f"    nicht lesbar:              {anzahl(e.fehler_lesen)}")
        zeilen.append(
            "  Fehlerhafte Zieldateien wurden weder geloescht noch ueberschrieben, nur gemeldet."
            " Ein erneutes 'fotosort kopieren' legt eine frische Kopie an."
        )
    zeilen.append(f"  Dauer:           {dauer(e.sekunden)}")
    if e.sekunden > 0:
        zeilen.append(f"  Durchsatz:       {durchsatz(e.bearbeitet, e.bytes_gelesen, e.sekunden)}")
    zeilen.append(f"  Hash-Worker:     {anzahl(e.hash_worker)} (Profil {e.profil})")
    return "\n".join(zeilen)


def pruefen_zusammenfassung(status: dict, noch_zu_pruefen: int) -> str:
    zeilen = [
        "Stand des Archivs",
        f"  geprueft (Aufraeumen offen):  {anzahl(status.get('geprueft', 0))}",
        f"  Duplikate bestaetigt:         {anzahl(status.get('duplikat_bestaetigt', 0))}",
        f"  noch zu pruefen:              {anzahl(noch_zu_pruefen)}",
        f"  Fehler:                       {anzahl(status.get('fehler', 0))}",
    ]
    return "\n".join(zeilen)


def kopieren_neu_nach_pruefung(n: int) -> str:
    return (
        f"{anzahl(n)} Datei{'en' if n != 1 else ''} mit fehlgeschlagener Pruefung"
        " werden neu kopiert (die fehlerhafte Zieldatei bleibt liegen und steht im Bericht)."
    )


# ---------------------------------------------------------- Bericht -----


def bericht_geschrieben(txt, csv_dateien, csv_ereignisse) -> str:
    return (
        "Bericht geschrieben:\n"
        f"  {txt}\n"
        f"  {csv_dateien}\n"
        f"  {csv_ereignisse}"
    )


# --------------------------------------------------------- Loeschen -----
# Gruende, die in die Datenbank und den Bericht gelangen (Phase 5).

GRUND_ZEILE_FEHLT = "Loeschung verweigert: keine Zeile in der Datenbank"
GRUND_KEIN_ECHTER_TYP = "Loeschung verweigert: kein echter Dateityp"
GRUND_KEIN_HASH = "Loeschung verweigert: kein gespeicherter Quell-Hash"
GRUND_QUELLE_ABWEICHUNG = "Quelle seit dem Kopieren geaendert (Hash der Quelle weicht ab) - nicht geloescht, wird neu kopiert"
GRUND_ZIEL_ABWEICHUNG = "Loeschung verweigert: Zieldatei weicht vom gespeicherten Hash ab"
GRUND_BYTEVERGLEICH = "Loeschung verweigert: Byte-Vergleich von Quelle und Ziel ungleich"
GRUND_KEINE_FRISCHLESUNG = "Loeschung verweigert: keine Frischlesung im laufenden Lauf"
GRUND_QUELLE_NICHT_LESBAR = "Loeschung verweigert: Quelldatei nicht lesbar"
GRUND_ZIEL_NICHT_LESBAR = "Loeschung verweigert: Zieldatei nicht lesbar"
GRUND_PAPIERKORB_FEHLT = "Loeschung verweigert: kein Ordner _geloescht_ angegeben"
GRUND_PAPIERKORB_KOPIE = "Loeschung verweigert: Kopie in den Ordner _geloescht_ stimmt nicht ueberein"
GRUND_QUELLE_FEHLT_LOESCHEN = "Loeschung verweigert: Quelldatei nicht mehr vorhanden"
GRUND_ZIEL_FEHLT_LOESCHEN = "Loeschung verweigert: Zieldatei nicht mehr vorhanden"
GRUND_VERSCHIEBEN_GROESSE = "Verschieben: Zieldatei nach dem Umbenennen nicht vorhanden oder Groesse weicht ab"
GRUND_DIESELBE_DATEI = "Loeschung verweigert: Quelle und Ziel sind dieselbe Datei (derselbe Speicherort ueber zwei Pfade)"
GRUND_LESUNG_FREMDER_LAUF = "Loeschung verweigert: Frischlesung stammt nicht aus dem laufenden Lauf"
EREIGNIS_VERSCHOBEN_NACHGETRAGEN = "Umbenennen aus abgebrochenem Lauf war fertig (Quelle weg, Zieldatei mit passender Groesse da) - Status verschoben nachgetragen"
EREIGNIS_ANHANG_ABWEICHEND = "Namensanhang weicht innerhalb der Gruppe ab (ein anderes Programm hat den Namen dazwischen belegt)"
EREIGNIS_LOESCHFEHLER = "Betriebssystemfehler beim Entfernen - Quelle bleibt"
EREIGNIS_GELOESCHT = "Quelldatei endgueltig geloescht"
EREIGNIS_NACHGETRAGEN = "Loeschung aus abgebrochenem Lauf nachgetragen (Quelle fehlt, Ziel stimmt, Frischlesung war festgeschrieben)"
EREIGNIS_REST_NICHT_ENTFERNT = "Name in reste_dateien, steht aber mit echtem Dateityp in der Datenbank - nicht entfernt"
EREIGNIS_REST_ENTFERNT = "Reste-Datei entfernt"
EREIGNIS_LEERER_ORDNER = "leerer Ordner entfernt"


def grund_status_nicht_berechtigt(status: str) -> str:
    return f"Loeschung verweigert: Status {status!r} berechtigt nicht zum Loeschen"


def grund_lesung(art: str) -> str:
    return {
        "quelle_fehlt": GRUND_QUELLE_FEHLT_LOESCHEN,
        "ziel_fehlt": GRUND_ZIEL_FEHLT_LOESCHEN,
        "abgebrochen": "Loeschung verweigert: Lesen abgebrochen",
    }.get(art, f"Loeschung verweigert: {art}")


def grund_groesse_abweichung(erwartet: int, quelle: int, ziel: int) -> str:
    if quelle == erwartet:
        return (
            f"Loeschung verweigert: Zieldatei hat die falsche Groesse (gespeichert {anzahl(erwartet)} Byte,"
            f" Ziel {anzahl(ziel)}); die Quelle ist in Ordnung"
        )
    return (
        f"Loeschung verweigert: Groesse weicht ab (gespeichert {anzahl(erwartet)} Byte,"
        f" Quelle {anzahl(quelle)}, Ziel {anzahl(ziel)})"
    )


def grund_weise_unbekannt(weise) -> str:
    return f"Loeschung verweigert: unbekannte Loeschweise {weise!r}"


# --------------------------------------------------------- Aufraeumen ---

BESTAETIGUNGSWORT = {"endgueltig": "loeschen", "papierkorb": "verschieben", "ordner": "entfernen",
                     "verwerfen": "verwerfen"}


def weise_text(weise: str) -> str:
    if weise == "papierkorb":
        return "in den Ordner _geloescht_<Datum> innerhalb der Quelle verschieben (Standard; den Ordner loeschen Sie spaeter selbst)"
    return "ENDGUELTIG loeschen (--endgueltig)"


def aufraeumen_plan(je_quelle: dict, weise: str, nicht_erreichbar: list) -> str:
    zeilen = ["Aufraeumen der Quellen: loeschberechtigt sind nur Dateien mit Status geprueft oder duplikat_bestaetigt."]
    zeilen.append(f"Loeschweise: {weise_text(weise)}")
    gesamt_n = gesamt_b = 0
    for wurzel in sorted(je_quelle):
        n, b = je_quelle[wurzel]
        gesamt_n += n
        gesamt_b += b
        zeilen.append(f"  {wurzel}: {anzahl(n)} Dateien, {groesse(b)}")
    zeilen.append(f"  gesamt: {anzahl(gesamt_n)} Dateien, {groesse(gesamt_b)}")
    if nicht_erreichbar:
        zeilen.append("Nicht erreichbare Quellen (dort passiert nichts):")
        zeilen.extend(f"  {q}" for q in nicht_erreichbar)
    return "\n".join(zeilen)


def aufraeumen_frage(wurzel, n: int, bytes_: int, weise: str) -> str:
    wort = BESTAETIGUNGSWORT[weise]
    return (
        f"Quelle {wurzel}: {anzahl(n)} Dateien ({groesse(bytes_)}) {weise_text(weise)}.\n"
        f"Vor jeder Loeschung werden Quelle und Ziel vollstaendig neu gelesen und verglichen.\n"
        f"Zum Bestaetigen das Wort '{wort}' eingeben, alles andere ueberspringt diese Quelle: "
    )


def aufraeumen_ordner_frage(wurzel, n: int) -> str:
    return (
        f"Quelle {wurzel}: {anzahl(n)} leere Ordner entfernen (Reste-Dateien laut Konfiguration zaehlen als leer;"
        f" der Wurzelordner bleibt).\nZum Bestaetigen das Wort '{BESTAETIGUNGSWORT['ordner']}' eingeben: "
    )


def aufraeumen_uebersprungen(wurzel) -> str:
    return f"Quelle {wurzel}: uebersprungen (nicht bestaetigt)."


def aufraeumen_nichts_zu_tun() -> str:
    return "Nichts aufzuraeumen: Es gibt keine Dateien mit Status geprueft oder duplikat_bestaetigt."


def aufraeumen_dry_run_liste(wurzel, pfade_liste: list, weitere: int) -> str:
    zeilen = [f"Quelle {wurzel}: diese Dateien wuerden entfernt:"]
    zeilen.extend(f"  {p}" for p in pfade_liste)
    if weitere:
        zeilen.append(f"  ... und {anzahl(weitere)} weitere (vollstaendig im Bericht)")
    return "\n".join(zeilen)


def aufraeumen_laeuft(dateien: int, gesamt: int, bytes_: int, gesamt_bytes: int, bytes_pro_s: float) -> str:
    mb = f"{bytes_pro_s / 1024 / 1024:.1f}".replace(".", ",")
    return (
        f"Aufraeumen: {anzahl(dateien)} von {anzahl(gesamt)} Dateien geprueft,"
        f" {groesse(bytes_)} von {groesse(gesamt_bytes)} gelesen, {mb} MB/s"
    )


def aufraeumen_ergebnis(e) -> str:
    zeilen = [
        "Ergebnis des Aufraeumens (dieser Lauf)",
        f"  angestanden:                       {anzahl(e.geplant)}",
        f"  endgueltig geloescht:              {anzahl(e.geloescht)}",
        f"  in _geloescht_-Ordner verschoben:  {anzahl(e.in_papierkorb)}",
        f"  aus abgebrochenem Lauf nachgetragen: {anzahl(e.nachgetragen)}",
        f"  QUELLE SEIT DEM KOPIEREN GEAENDERT - nicht geloescht, neu zu kopieren: {anzahl(e.quelle_veraendert)}",
        f"  Loeschung verweigert (Ziel fehlt oder weicht ab, Lesefehler): {anzahl(e.verweigert)}",
        f"  freigegebener Platz:               {groesse(e.bytes_frei)}",
    ]
    if e.leere_ordner_entfernt or e.reste_entfernt or e.reste_verweigert:
        zeilen.append(f"  leere Ordner entfernt:             {anzahl(e.leere_ordner_entfernt)}")
        zeilen.append(f"  Reste-Dateien entfernt:            {anzahl(e.reste_entfernt)}")
        zeilen.append(f"  Reste mit echtem Dateityp, NICHT entfernt: {anzahl(e.reste_verweigert)}")
    zeilen.append(f"  Dauer:           {dauer(e.sekunden)}")
    if e.sekunden > 0:
        zeilen.append(f"  Durchsatz:       {durchsatz(e.bearbeitet, e.bytes_gelesen, e.sekunden)}")
    if e.quelle_veraendert:
        zeilen.append("  Geaenderte Quellen stehen im Bericht unter 'Quelle seit dem Kopieren geaendert' und werden beim naechsten 'kopieren' neu kopiert.")
    return "\n".join(zeilen)


def aufraeumen_abgebrochen() -> str:
    return "Abgebrochen. Was geloescht wurde, steht in der Datenbank und im Bericht; nichts ist halb."


def aufraeumen_quelle_nicht_erreichbar(wurzel) -> str:
    return f"Quelle {wurzel} ist nicht erreichbar - dort passiert nichts."


def aufraeumen_keine_eingabe() -> str:
    return "Keine Bestaetigung moeglich (keine Eingabe verfuegbar). Es wurde nichts geloescht."


def aufraeumen_ordner_dry_run(wurzel, ordner: list) -> str:
    zeilen = [f"Quelle {wurzel}: diese leeren Ordner wuerden entfernt ({anzahl(len(ordner))}):"]
    zeilen.extend(f"  {o}" for o in ordner)
    return "\n".join(zeilen)


# ------------------------------------------------------- Verschieben ----


def verschieben_hinweis(umbenennen: bool, direkt: bool) -> str:
    if umbenennen:
        return "Verschieben: Quelle und Ziel liegen auf demselben Laufwerk - Dateien werden umbenannt, nicht kopiert."
    if direkt:
        return "Verschieben: Ziel kann kein nicht ueberschreibendes Umbenennen - kopieren, pruefen, dann Quelle loeschen."
    return "Verschieben: kopieren, Ziel und Quelle frisch lesen, dann Quelle loeschen."


def verschieben_ergebnis(e) -> str:
    zeilen = [
        f"  verschoben durch Umbenennen:  {anzahl(e.verschoben)}",
        f"  Quelle nach Pruefung geloescht: {anzahl(e.quelle_geloescht)}",
        f"  Quelle seit dem Kopieren geaendert (nicht geloescht): {anzahl(e.quelle_seit_kopieren)}",
        f"  Loeschung verweigert:         {anzahl(e.loeschung_verweigert)}",
    ]
    return "\n".join(zeilen)


def quelle_unbekannt(pfad) -> str:
    return f"Quelle {pfad} ist in diesem Archiv nicht bekannt (fotosort status zeigt die bekannten Quellen)."


def aufraeumen_dry_run_schluss() -> str:
    return "Probelauf (--dry-run): Es wurde nichts geloescht und kein Lauf angelegt."


# ------------------------------------------------- Gefuehrter Modus -----


def start_keine_eingabe() -> str:
    return (
        "Der gefuehrte Modus stellt Fragen und braucht dafuer ein Terminal.\n"
        "Ohne Terminal (Pipe, Skript, Aufgabenplanung) bitte die einzelnen Befehle\n"
        "benutzen: scan, analyse, kopieren, pruefen, aufraeumen."
    )


def start_begruessung() -> str:
    return (
        "fotosort - gefuehrter Ablauf\n"
        "Es werden ein paar Fragen gestellt; danach laufen die Schritte nacheinander,\n"
        "und vor jedem Schritt wird gefragt. Enter allein nimmt den Vorschlag in\n"
        "eckigen Klammern. Abbrechen jederzeit mit Strg+C - das Bisherige bleibt\n"
        "gespeichert, und 'fotosort start' macht spaeter an derselben Stelle weiter."
    )


def start_frage_ziel() -> str:
    return "Zielordner des Archivs (dorthin werden die Bilder sortiert): "


def start_ziel_fehlt(ziel) -> str:
    return f"Den Ordner {ziel} gibt es noch nicht."


def start_frage_ziel_anlegen() -> str:
    return "Soll er angelegt werden? (ja/nein) [nein]: "


def start_quellen_bekannt(quellen: list) -> str:
    zeilen = ["Bekannte Quellordner dieses Archivs:"]
    zeilen += [f"  {q}" for q in quellen]
    return "\n".join(zeilen)


def start_frage_quelle(weitere: bool) -> str:
    if weitere:
        return "Weiterer Quellordner (leer = keiner mehr): "
    return "Quellordner mit den unsortierten Bildern: "


def start_quelle_noetig() -> str:
    return "Ohne mindestens einen Quellordner kann nichts sortiert werden."


def start_quelle_schon_dabei(pfad) -> str:
    return f"Schon dabei: {pfad}"


def start_frage_modus() -> str:
    return (
        "Kopieren (Quelle bleibt unveraendert, aufraeumen spaeter) oder\n"
        "Verschieben (Quelle wird nach gelungener Pruefung Datei fuer Datei geloescht)?\n"
        "(k = kopieren, v = verschieben) [k]: "
    )


def start_frage_profil(standard: str) -> str:
    return (
        "Wo liegt das Ziel? hdd = Festplatte, ssd = SSD, netzwerk = Netzlaufwerk"
        f" [{standard}]: "
    )


def start_zusammenfassung(ziel, quellen: list, verschieben: bool, profil: str, phase_text: str) -> str:
    zeilen = [
        "",
        "Zusammenfassung",
        f"  Ziel:     {ziel}",
        "  Quellen:  " + (", ".join(str(q) for q in quellen) if quellen else "(keine)"),
        f"  Modus:    {'verschieben' if verschieben else 'kopieren'}",
        f"  Profil:   {profil}",
        f"  {phase_text}",
    ]
    return "\n".join(zeilen)


def start_frage_ok() -> str:
    return "Stimmt das so? (Enter = ja, n = abbrechen): "


def start_abgebrochen() -> str:
    return "Abgebrochen. Es wurde nichts veraendert."


def start_schritt(nummer: int, titel: str) -> str:
    return f"\n=== Schritt {nummer}: {titel} ==="


def start_frage_weiter(titel: str) -> str:
    return f"Weiter mit '{titel}'? (Enter = ja, n = hier aufhoeren): "


def start_uebersprungen(titel: str) -> str:
    return f"{titel}: nichts zu tun, wird uebersprungen."


def start_fehler_frage() -> str:
    return "Der Schritt hat Fehler gemeldet (siehe oben). Trotzdem weitermachen? (ja/nein) [nein]: "


def start_aufgehoert() -> str:
    return (
        "Hier aufgehoert. Alles Bisherige ist gespeichert;\n"
        "'fotosort start' macht spaeter an dieser Stelle weiter."
    )


def start_modelle(modelle: list) -> str:
    """(Rohmodell, Ordnername, Anzahl) - die Liste vor der Alias-Frage."""
    zeilen = ["Gefundene Kameramodelle (Modell -> Ordner):"]
    for roh, ordner, n in modelle:
        zeilen.append(f"  {(roh or '(kein Modell)'):<28} -> {ordner:<20}{anzahl(n):>8}")
    return "\n".join(zeilen)


def start_quelle_kein_ordner(pfad) -> str:
    return f"Das ist kein Ordner: {pfad}"


def start_quelle_abgelehnt(pfad, grund: str) -> str:
    return f"Quellordner {pfad} nicht uebernommen: {grund}"


def start_verschieben_frage(n: int, bytes_: int) -> str:
    return (
        f"Verschieben: {anzahl(n)} Dateien ({groesse(bytes_)}) werden ins Archiv gebracht und danach\n"
        "in der Quelle geloescht (auf demselben Laufwerk durch Umbenennen, sonst nach Kopie\n"
        "und Frischlesung beider Seiten). Zum Bestaetigen das Wort 'verschieben' eingeben,\n"
        "alles andere hoert hier auf: "
    )


def start_frage_alias() -> str:
    return (
        "Soll ein Kameramodell einen anderen Ordnernamen bekommen?\n"
        "Modell genau wie in der Liste oben eingeben (leer = nein, weiter): "
    )


def start_frage_alias_ordner(modell: str) -> str:
    return f"Ordnername fuer '{modell}': "


def start_alias_unbekannt(modell: str) -> str:
    return f"Dieses Modell kam in der Analyse nicht vor: {modell} - nicht eingetragen."


def start_aliase_geschrieben(pfad, n: int, zurueck: int) -> str:
    return (
        f"{anzahl(n)} Alias{'e' if n != 1 else ''} in {pfad} eingetragen;"
        f" {anzahl(zurueck)} Dateien werden neu analysiert."
    )


def start_frage_aufraeumen(n: int, bytes_: int) -> str:
    return (
        f"Quelle jetzt aufraeumen? {anzahl(n)} geprueft kopierte Dateien ({groesse(bytes_)})\n"
        "wuerden in den Ordner _geloescht_<Datum> innerhalb der Quelle verschoben\n"
        "(je Quelle wird noch einmal mit einem Wort bestaetigt). (ja/nein) [nein]: "
    )


def start_frage_leere_ordner() -> str:
    return "Leere Ordner in den Quellen entfernen? (ja/nein) [nein]: "


def start_fertig(zaehler: dict) -> str:
    zeilen = ["", "Gefuehrter Ablauf beendet.", status_zaehler(zaehler)]
    return "\n".join(zeilen)


def config_alias_nicht_geschrieben(pfad, modell: str) -> str:
    return (
        f"Der Alias fuer '{modell}' konnte nicht in {pfad} eingetragen werden;"
        " die Datei wurde nicht veraendert. Bitte von Hand unter [kamera.aliase] eintragen (fotosort config)."
    )


# ------------------------------------------------------------ Messen -----


def messen_beginnt(quelle, ziel, mb: int, stufen: tuple) -> str:
    return (
        f"Tempo messen: Lesen aus {quelle}, Schreiben nach {ziel}.\n"
        f"  Je Stufe etwa {mb} MB, Worker-Zahlen {', '.join(str(s) for s in stufen)}.\n"
        "  Im Ziel entsteht nur ein voruebergehender Messordner, der am Ende wieder entfernt wird."
    )


def messen_quelle_zu_klein(bytes_: int, mindestens: int) -> str:
    return (
        f"In der Quelle liegen nur {groesse(bytes_)} an Dateien (mindestens {groesse(mindestens)} noetig)."
        " Das Lesetempo wird deshalb nicht gemessen."
    )


def messen_zu_wenig_platz(ziel, benoetigt: int, frei: int) -> str:
    return (
        f"Im Ziel {ziel} sind nur {groesse(frei)} frei; fuer die Schreibmessung werden"
        f" {groesse(benoetigt)} gebraucht. Das Schreibtempo wird nicht gemessen."
    )


def messen_stufe(worker: int, lesen: float | None, schreiben: float | None) -> str:
    def mbs(w):
        return "   -   " if w is None else f"{w:7.1f}".replace(".", ",")
    return f"  {worker:>6}   {mbs(lesen)} MB/s     {mbs(schreiben)} MB/s"


def messen_tabelle_kopf() -> str:
    return "  Worker     Lesen (Hash)     Schreiben"


def messen_ergebnis(e) -> str:
    zeilen = ["", "Vorschlag fuer die config.toml, Gruppe [leistung]:"]
    zeilen.append(f'  profil = "{e.profil}"')
    zeilen.append(f"  kopier_worker = {e.kopier_worker}")
    zeilen.append(f"  hash_worker = {e.hash_worker}")
    zeilen.append("")
    zeilen.append(
        "So ist das zu lesen: 'Worker' sind gleichzeitig laufende Kopier- bzw."
        " Lesevorgaenge. Mehr Worker helfen bei SSDs und im Netz, bremsen aber eine"
        " Festplatte aus. Gewaehlt wird die kleinste Zahl, die nahe am besten Wert liegt."
    )
    if e.hinweis:
        zeilen.append(e.hinweis)
    zeilen.append(
        "Die Messung dauerte " + dauer(e.sekunden) + ". Beim ersten Durchlauf kann der"
        " Zwischenspeicher des Betriebssystems mitspielen; im Zweifel zweimal messen."
    )
    return "\n".join(zeilen)


def messen_nichts_gemessen() -> str:
    return "Es konnte weder Lesen noch Schreiben gemessen werden (siehe oben)."


def messen_abgebrochen(rest=None) -> str:
    if rest:
        return f"Messung abgebrochen. Der voruebergehende Messordner konnte nicht ganz entfernt werden: {rest}"
    return "Messung abgebrochen. Der voruebergehende Messordner wurde entfernt."


def messen_netz_hinweis(wo: str) -> str:
    return f"Hinweis: {wo} liegt auf einem Netzlaufwerk; deshalb wird das Profil netzwerk vorgeschlagen."


# ------------------------------------------------- Arbeitsprozess (Phase 7) -----


def arbeit_auftrag_fehlt(pfad) -> str:
    return f"Auftragsdatei nicht lesbar: {pfad}"


def arbeit_schritt_unbekannt(schritt: str) -> str:
    return f"Unbekannter Schritt im Auftrag: {schritt}"


def arbeit_mit_fehlern(schritt: str) -> str:
    return f"Der Schritt '{schritt}' ist durchgelaufen, hat aber Fehler gemeldet (siehe Bericht)."


# ------------------------------------------------ Oberflaeche (Phase 7) ----
# Diese Texte erscheinen nur im Fenster (UTF-8), nie in der Windows-Konsole.
# Deshalb duerfen sie - anders als der Rest dieser Datei - Umlaute tragen.

SCHRITT_NAME: dict[str, str] = {
    "scan": "Quellen durchsuchen",
    "analyse": "Analyse: Datum, Kamera und Zielordner bestimmen",
    "kopieren": "Kopieren ins Archiv",
    "verschieben": "Verschieben ins Archiv",
    "pruefen": "Prüfen: jede Zieldatei vollständig neu lesen",
    "aufraeumen": "Quelle aufräumen",
}

SCHRITT_ERKLAERUNG: dict[str, str] = {
    "scan": "Das Programm sieht alle Quellordner durch und merkt sich jede Datei. Es wird noch nichts kopiert oder verändert.",
    "analyse": "Für jede Datei werden Aufnahmedatum und Kameramodell gelesen und daraus der Zielordner berechnet. Es wird noch nichts kopiert.",
    "kopieren": "Die Dateien werden ins Archiv kopiert. Die Quelle bleibt unverändert; nie wird eine vorhandene Datei überschrieben.",
    "verschieben": "Die Dateien werden ins Archiv gebracht und erst nach erfolgreicher Prüfung in der Quelle gelöscht.",
    "pruefen": "Jede kopierte Datei wird im Archiv vollständig neu gelesen und mit der Quelle verglichen.",
    "aufraeumen": "Nur Dateien, deren Kopie im Archiv nachweislich stimmt, werden aus der Quelle entfernt. Vorher werden Quelle und Ziel noch einmal komplett gelesen.",
}

OB_PROFILE: list[tuple[str, str]] = [
    ("hdd", "Festplatte – der Zielordner liegt auf einer normalen Festplatte (Standard, immer sicher)"),
    ("ssd", "SSD – der Zielordner liegt auf einer SSD (mehrere Dateien gleichzeitig, schneller)"),
    ("netzwerk", "Netzlaufwerk – der Zielordner liegt auf einem NAS oder einer Netzfreigabe"),
]

OB_ZUSTAND: dict[str, str] = {
    "startet": "Wird gestartet …",
    "laeuft": "Läuft",
    "pause": "Angehalten",
    "fertig": "Fertig",
    "abgebrochen": "Abgebrochen – das Bisherige ist gespeichert, der nächste Lauf macht dort weiter.",
    "fehler": "Beendet, aber mit Fehlern",
    "abgestuerzt": "Der Arbeitsvorgang ist unerwartet beendet worden. Das Bisherige ist gespeichert; ein neuer Start macht dort weiter.",
}


def ob_laeuft_schon(schritt: str) -> str:
    return f"Es läuft gerade noch ein Schritt ({SCHRITT_NAME.get(schritt, schritt)}). Bitte warten, bis er fertig ist."


def ob_kein_lauf() -> str:
    return "Im Moment läuft nichts, das sich anhalten oder abbrechen ließe."


def ob_wort_falsch(wort: str) -> str:
    return f"Zur Bestätigung muss genau das Wort „{wort}“ eingetippt werden. Es wurde nichts gestartet."


def ob_quelle_noetig() -> str:
    return "Bitte mindestens einen Quellordner hinzufügen – den Ordner, in dem die unsortierten Fotos liegen."


def ob_quelle_fehlt_pfad() -> str:
    return "Bitte zuerst einen Ordner eintragen oder auswählen."


def ob_frage_ziel_anlegen(ziel) -> str:
    return f"Den Ordner {ziel} gibt es noch nicht. Soll er angelegt werden?"


def ob_frage_quelle_gross(pfad, art: str) -> str:
    """Rueckfrage, wenn ein ganzes Laufwerk oder der Benutzerordner als Quelle gewaehlt wurde."""
    if art == "laufwerk":
        was = f"{pfad} ist ein ganzes Laufwerk. Dann werden alle Fotos und Videos darauf erfasst – auch die aus Programmen, Spielen und Systemordnern."
    elif art == "profil":
        was = f"{pfad} ist der eigene Benutzerordner. Dann werden alle Fotos und Videos darin erfasst – auch aus Downloads, vom Desktop und aus Programmdaten."
    else:
        was = f"{pfad} enthält die Ordner aller Benutzer dieses Rechners."
    return was + " Meist ist ein Unterordner wie „Bilder“ gemeint. Trotzdem diesen Ordner nehmen?"


def ob_frage_ziel_nicht_leer(ziel, n: int) -> str:
    return (
        f"Der Zielordner {ziel} ist nicht leer ({anzahl(n)} Einträge), enthält aber noch kein Archiv. "
        "Es wird darin nichts gelöscht oder überschrieben; die Fotos kommen zu dem, was schon da liegt, "
        "und passende Jahres- und Tagesordner werden weiterverwendet. Weiter mit diesem Ordner?"
    )


def ob_frage_verwerfen(ziel, lokal, im_ziel) -> str:
    return (
        f"Das entfernt die Merkliste des Programms zu {ziel}: die Datenbank unter {lokal} und den Ordner "
        f"{im_ziel} mit Sicherung, Einstellungen und Berichten. Kopierte Fotos und Videos im Zielordner bleiben "
        "unangetastet, die Quellordner ebenso. Danach ist die Startseite leer, und der Ordner kann als neues "
        f"Archiv beginnen. Zum Bestätigen „{BESTAETIGUNGSWORT['verwerfen']}“ tippen:"
    )


def ob_verwerfen_bilddatei(pfad) -> str:
    return (
        f"Nicht verworfen: Unter {pfad} liegt eine Foto-, RAW- oder Videodatei in einem Ordner, "
        "der nur Programmdaten enthalten dürfte. Das Programm löscht dort nichts. Bitte die Datei "
        "zuerst von Hand in Sicherheit bringen."
    )


def ob_verwerfen_unvollstaendig(fehler: list) -> str:
    return "Nicht alles ließ sich entfernen: " + "; ".join(str(f) for f in fehler[:5])


def ob_verworfen(ziel, entfernt: int) -> str:
    return f"Archiv zu {ziel} verworfen ({anzahl(entfernt)} Ordner entfernt). Die kopierten Fotos liegen unverändert dort."


def ob_nichts_ausgewaehlt() -> str:
    return "Es ist nichts ausgewählt: Entweder das Bestätigungswort für die Dateien eintippen oder „Leere Ordner entfernen“ ankreuzen."


def ob_liste_unbekannt(art: str) -> str:
    return f"Unbekannte Liste: {art}"


def ob_datenbank_belegt() -> str:
    return "Solange ein Schritt läuft, kann die Zusammenfassung nicht gelesen werden. Bitte warten, bis er fertig ist."


def ob_kein_archiv(ziel) -> str:
    return f"In {ziel} liegt noch kein Archiv. Bitte zuerst „Los geht's“ mit mindestens einem Quellordner."


def ob_bericht(pfad, geoeffnet: bool) -> str:
    if geoeffnet:
        return f"Der Bericht wurde geschrieben und geöffnet: {pfad}"
    return f"Der Bericht wurde geschrieben: {pfad} (er ließ sich nicht automatisch öffnen)."


def ob_einstellungen(pfad, geoeffnet: bool) -> str:
    if geoeffnet:
        return f"Die Einstellungsdatei wurde geöffnet: {pfad}"
    return f"Die Einstellungsdatei liegt hier: {pfad} (sie ließ sich nicht automatisch öffnen)."


def ob_aliase_geschrieben(n: int, zurueck: int) -> str:
    return (
        f"{anzahl(n)} Ordnernamen gespeichert. {anzahl(zurueck)} Dateien werden jetzt noch einmal analysiert,"
        " damit sie den neuen Ordnernamen bekommen."
    )


def ob_keine_aliase() -> str:
    return "Es wurde kein Ordnername geändert."


def ob_kopieren_text(n: int, bytes_: int, verschieben: bool) -> str:
    if verschieben:
        return (
            f"{anzahl(n)} Dateien ({groesse(bytes_)}) werden ins Archiv verschoben. Jede Datei wird erst in der"
            " Quelle gelöscht, wenn ihre Kopie im Archiv geprüft ist. Zur Bestätigung bitte das Wort"
            " „verschieben“ eintippen."
        )
    return f"{anzahl(n)} Dateien ({groesse(bytes_)}) werden ins Archiv kopiert. Die Quelle bleibt unverändert."


def ob_pruefen_text(n: int, bytes_: int) -> str:
    return f"{anzahl(n)} Dateien ({groesse(bytes_)}) werden im Archiv vollständig neu gelesen und verglichen."


def ob_analyse_text(n: int) -> str:
    return f"{anzahl(n)} Dateien warten auf die Analyse."


def ob_fertig_text() -> str:
    return "Alle Schritte sind erledigt. Es gibt nichts mehr zu tun."


def ob_herkunft_abgelehnt() -> str:
    return "Anfrage von einer fremden Seite abgelehnt."


def ob_adresse(adresse: str) -> str:
    return f"Die Oberfläche läuft. Im Browser öffnen: {adresse}   (Beenden mit Strg+C)"


def ob_kein_fenster(grund: str) -> str:
    return (
        f"Das Fenster lässt sich hier nicht öffnen ({grund}).\n"
        "Ersatz: fotosort fenster --ohne-fenster  und die genannte Adresse im Browser öffnen."
    )


def ob_server_fehlgeschlagen(fehler) -> str:
    return f"Der Server der Oberfläche konnte nicht gestartet werden: {fehler}"


def ob_selbsttest(ok: bool, einzelheit: str, fenster: bool = True) -> str:
    if ok and fenster:
        return f"Selbsttest bestanden: Fenster geöffnet, Seite geladen, Zustand gelesen. {einzelheit}"
    if ok:
        return f"Selbsttest bestanden: Server läuft, Seite und Zustand lesbar. {einzelheit}"
    return f"Selbsttest FEHLGESCHLAGEN: {einzelheit}"


def ob_abgebrochen_hart(schritt: str) -> str:
    return f"Der Schritt {SCHRITT_NAME.get(schritt, schritt)} wurde sofort beendet. Angefangene Kopien räumt der nächste Lauf auf."


def ob_phase_kurz(niedrigster: str | None, dateien_erfasst: bool) -> str:
    """Die aktuelle Phase in einem Satz fuer die Startseite."""
    if niedrigster is None:
        return "Es sind noch keine Dateien erfasst." if not dateien_erfasst else "Alle erfassten Dateien sind erledigt oder übersprungen."
    return {
        "gefunden": "Die Quellen sind durchsucht; die Analyse steht noch aus.",
        "analysiert": "Die Analyse ist fertig; das Kopieren steht noch aus.",
        "kopieren_laeuft": "Ein Kopiervorgang wurde unterbrochen; er kann fortgesetzt werden.",
        "kopiert": "Kopiert; die Prüfung steht noch aus.",
        "geprueft": "Kopiert und geprüft; die Quelle kann aufgeräumt werden.",
        "quelle_geloescht": "Alles erledigt; höchstens leere Ordner sind noch zu entfernen.",
    }.get(niedrigster, "")


def ob_startfehler(grund: str, protokoll) -> str:
    zeilen = [
        "Das Programm konnte nicht starten.",
        "",
        f"Grund: {grund}",
        "",
        "Was Sie tun können:",
        "  1. Die ZIP-Datei noch einmal vollständig entpacken und start.bat erneut starten.",
        "  2. Den Ordner nicht aus der ZIP-Vorschau heraus starten, sondern erst entpacken.",
        "  3. Bleibt es dabei: das Protokoll an den Entwickler schicken.",
    ]
    if protokoll:
        zeilen += ["", f"Protokoll: {protokoll}"]
    return "\n".join(zeilen)


def ob_laufzeitfehler(grund: str, protokoll) -> str:
    zeilen = [
        "Im Fenster ist ein unerwarteter Fehler aufgetreten. Ihre Dateien sind davon nicht betroffen;",
        "ein laufender Schritt arbeitet weiter.",
        "",
        f"Grund: {grund}",
        "",
        "Sie können das Fenster schließen und über start.bat neu öffnen.",
    ]
    if protokoll:
        zeilen += ["", f"Protokoll: {protokoll}"]
    return "\n".join(zeilen)


def ob_qt_fehlt(grund: str) -> str:
    return (
        "Das Fenster braucht die Bibliothek PySide6 (Qt). Sie fehlt oder lässt sich nicht laden:\n"
        f"{grund}\n"
        "Im fertigen Paket ist sie enthalten - dann die ZIP-Datei noch einmal vollständig entpacken.\n"
        "Aus dem Quellcode: einrichten.bat erneut ausführen (installiert PySide6-Essentials)."
    )


def ob_durchlauf(ok: bool, einzelheit: str) -> str:
    if ok:
        return f"Durchlauf bestanden: Startseite, Scan, Analyse, Kopieren, Prüfen, Aufräumen über das Fenster. {einzelheit}"
    return f"Durchlauf FEHLGESCHLAGEN: {einzelheit}"
