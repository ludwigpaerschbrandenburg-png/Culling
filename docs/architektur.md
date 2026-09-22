# Architekturvorschlag

Vorschlag aus Prompt 0, noch nichts davon gebaut. Grundlage ist [`SPEC.md`](SPEC.md).
Alle elf Punkte aus [`offene_fragen.md`](offene_fragen.md) sind entschieden und hier
eingearbeitet. Diese Datei erklärt und begründet die SPEC, sie ersetzt sie nicht: bei einem
Widerspruch gilt die SPEC.

---

## 1. Aufbau in Modulen

Ein Modul ist eine Datei mit einer klar umrissenen Aufgabe. Der Zuschnitt folgt einer
einzigen Überlegung: **alles, was viele Sonderfälle hat, muss sich ohne echte Dateien testen
lassen.**

Datum, Kamera, Zielpfad, Dateityp samt Sidecar-Zuordnung und Gruppenbildung sind genau solche
Stellen — dort stecken die meisten Regeln der SPEC und damit die meisten möglichen Fehler.
Diese fünf Module bekommen nur Werte herein und geben Werte zurück, ohne die Festplatte
anzufassen. So lassen sich hundert Sonderfälle in Sekunden durchtesten, statt für jeden einen
Testordner anzulegen.

```
Culling/ (Repository-Wurzel)
├─ pyproject.toml            Projektdatei: Name, Abhängigkeiten, Befehl "fotosort"
├─ CLAUDE.md                 Projektregeln
├─ docs/                     SPEC, Prompts, offene Fragen, diese Datei
├─ src/fotosort/
│  ├─ cli.py                 Kommandozeile, Unterbefehle, geführter Modus
│  ├─ config.py              config.toml lesen und beim ersten Start erzeugen
│  ├─ db.py                  SQLite: Schema, Statuswechsel, Sammelschreiben
│  ├─ meldungen.py           alle deutschen Texte an einer Stelle
│  ├─ pfade.py               Pfad-Hilfen: langes Präfix, Netz- und Laufwerkserkennung
│  │
│  ├─ scan.py                Phase 1: Quelle durchlaufen, zählen
│  ├─ analyse.py             Phase 2: Gruppen, Metadaten, Datum, Ziel je Datei
│  ├─ metadaten.py           ExifTool-Pool (-stay_open); Videos ohne -fast2; Prozesszahl nach Profil, gestaffelter Start
│  ├─ prozesse.py            Popen-Argumente für Hilfsprozesse: unter Windows kein Konsolenfenster (CREATE_NO_WINDOW, SW_HIDE)
│  ├─ datum.py               Aufnahmedatum bestimmen        ← reine Logik
│  ├─ kamera.py              Modell → Ordnername, Aliase    ← reine Logik
│  ├─ dateitypen.py          Dateityp, Sidecar-Zuordnung    ← reine Logik
│  ├─ gruppen.py             RAW+JPG, Sidecars              ← reine Logik
│  ├─ ziel.py                Zielpfad, Ordner mit Zusatz    ← reine Logik
│  ├─ hashes.py              BLAKE3-Prüfsummen, Byte-Vergleich
│  ├─ kopieren.py            Phase 3: übertragen
│  ├─ pruefen.py             Phase 4: nachrechnen
│  ├─ loeschen.py            die einzige Löschstelle (SPEC §5), Papierkorb _geloescht_
│  ├─ aufraeumen.py          Phase 5: Quelle aufräumen, leere Ordner
│  ├─ fortschritt.py         laufende Anzeige (Kopieren, Prüfen)
│  ├─ bericht.py             Text- und CSV-Bericht
│  ├─ messen.py              fotosort messen: Lese-/Schreibtempo, Profilvorschlag (Phase 6)
│  ├─ steuerung.py           Statusdatei und Steuerdatei je Schritt (Phase 7): Stand ≤ 2×/s, Pause, Abbruch
│  └─ oberflaeche/           Phase 7: die Oberfläche
│     ├─ ablauf.py           Zustand, Arbeitsprozess (fotosort arbeit), Zusammenfassungen und Listen
│     ├─ desktop.py          das Desktop-Fenster (PySide6/Qt): Seiten, Ordnerdialoge, Selbsttest, Durchlauf
│     ├─ stil.py             Nocturne als Qt-Stylesheet, Inter-Schrift laden, Programmsymbol
│     ├─ meldungsfenster.py  Startfehler als verständliches Meldungsfenster (ctypes), excepthook
│     ├─ server.py           FastAPI-Schnittstelle der Browser-Fassung (nur 127.0.0.1, Origin-Prüfung)
│     ├─ fenster.py          Einstieg: Desktop-Fenster oder --ohne-fenster (Server für Phase 8)
│     └─ static/             index.html, app.js, app.css (Layout), styles.css (Design-Tokens, docs/design/),
│                             fonts.css + fonts/ (Inter als woff2, offline) — eine Seite, kein Rahmenwerk
├─ docs/design/             Design-Uebergabe der Oberflaeche: DESIGN.md, index.html, app.css, styles.css
├─ docs/oberflaeche/         Bildschirmfotos jeder Ansicht (fenster --durchlauf --fotos, Qt offscreen, Testbaum)
├─ paket/
│  ├─ fotosort_start.py      Einstieg fuer PyInstaller
│  ├─ fotosort.spec          PyInstaller-Spec: fotosort.exe (Fenster, Symbol) und fotosort-konsole.exe auf einem _internal
│  ├─ fotosort.ico           Programmsymbol (aus stil.symbol() erzeugt)
│  ├─ exiftool_holen.py      ExifTool (Windows, 64 Bit, mit exiftool_files) von exiftool.org holen
│  ├─ bauen.py               PyInstaller-Ordnervariante bauen, Paketordner zusammenstellen
│  └─ pruefen.py             gepacktes Programm wie auf einem frischen PC ausprobieren (start.bat aus Ordner mit
│                             Leerzeichen, Fenster in 20 s, Durchlauf über das Fenster, Befehle, Arbeitsprozess)
├─ .github/workflows/
│  ├─ tests.yml              Testsuite auf ubuntu-latest und windows-latest
│  └─ paket.yml              Windows-Paket bauen und pruefen; Artefakt je Push, Release bei Tag v*
└─ tests/
   ├─ testbaum.py            erzeugt den künstlichen Testbaum
   └─ test_*.py              ein Test je Modul
```

`meldungen.py` als eigene Datei hat einen praktischen Grund: alle deutschen Ausgaben stehen
an einer Stelle. Ändert sich eine Formulierung, muss man nicht den ganzen Code durchsuchen —
und beim Bauen der Weboberfläche in Phase 7 lassen sich dieselben Texte wiederverwenden.

`pfade.py` ist die einzige Stelle im Programm, an der Windows und Linux sich unterscheiden.
Dort steht das Präfix `\\?\` (bei Netzpfaden `\\?\UNC\`) für lange Windows-Pfade, die
Erkennung, ob ein Pfad auf einem Netzlaufwerk liegt, die sichere Feststellung, ob zwei Pfade
auf demselben Laufwerk liegen, und die Prüfung, ob Ziel und Quelle ineinander liegen. Das
rechtfertigt ein eigenes Modul: Sonst verteilen sich diese Sonderfälle über `kopieren.py`,
`db.py` und `scan.py`, und beim Umzug in den Docker-Container findet man sie nicht wieder.
Überall sonst gilt die Regel aus `CLAUDE.md` unverändert — nur `pathlib`, keine Windows-Wege.

Drei weitere Regeln der SPEC stehen ebenfalls dort, weil sie alle drei mit Pfaden zu tun
haben und sonst über `scan.py` und `kopieren.py` verstreut lägen:

- **Aufgelöste Pfade statt Textvergleich.** Quelle und Ziel werden mit `Path.resolve()`
  aufgelöst, Verknüpfungen also mit aufgelöst, bevor verglichen wird (SPEC §5, §4 Phase 1).
  Quelle gleich Ziel bricht ab, Quelle innerhalb des Ziels bricht ab, Ziel innerhalb der
  Quelle wird vom Scan ausgeschlossen. Die Prüfung endet nicht am Anfang: Während des
  Durchlaufs wird der aufgelöste Pfad jedes Ordners gegen das aufgelöste Ziel gehalten. Ein
  reiner Textvergleich der Pfade übersähe eine Verknüpfung, die aus der Quelle ins Ziel
  zeigt — und genau die führt in die Schleife aus 4.4.
- **Ordner-Verknüpfungen werden nicht verfolgt** (Standard `verknuepfungen_folgen` =
  `false`, SPEC §9). Sie werden gezählt und im Bericht aufgeführt. Der Grund sind zwei
  Schäden auf einmal: Ein Ring aus Verknüpfungen ließe den Scan endlos laufen, und dieselbe
  Datei erschiene unter zwei Pfaden, also zweimal in der Datenbank — mit zwei Zielpfaden und
  zwei Löschentscheidungen für ein einziges Bild. Versteckte Ordner werden dagegen normal
  erfasst; sie sind nur unauffällig, nicht gefährlich.
- **Der Rückfall, wenn nicht überschreibendes Umbenennen fehlt** (SPEC §5). Auf exFAT und
  FAT32 — dem üblichen Format externer Platten — gibt es keine harten Verknüpfungen,
  `os.link` schlägt fehl, und `renameat2` mit `RENAME_NOREPLACE` wird dort ebenfalls nicht
  angenommen. `pfade.py` stellt das einmal je Ziel-Dateisystem fest. Dann entfällt das
  Verschieben durch Umbenennen und es wird kopiert, geprüft und gelöscht; das Kopieren
  verzichtet auf die `.part`-Datei und legt die Zieldatei direkt unter ihrem endgültigen
  Namen exklusiv an (`O_EXCL`), was auch auf diesen Dateisystemen nicht überschreiben kann.
  Ein einfaches Umbenennen, das eine vorhandene Datei ersetzen könnte, ist nie der Ausweg —
  auch nicht einmalig und auch nicht nach einer vorherigen Existenzprüfung, denn zwischen
  Prüfung und Umbenennen liegt immer ein Zeitraum. Dass der Rückfall gegriffen hat, steht
  mit Anzahl im Bericht.

`dateitypen.py` beantwortet zwei Fragen, ohne die Festplatte anzufassen: zu welchem Typ eine
Datei gehört (`foto`, `raw`, `video`, `sidecar`, `sonstiges`) und zu welcher Hauptdatei ein
Sidecar gehört. Für die Sidecar-Zuordnung gelten die drei Formen aus SPEC §3 — Stammname plus
Endung (`DSC01234.xmp`), vollständiger Dateiname plus Endung (`DSC01234.ARW.xmp`) und
Stammname plus konfigurierbares Zusatzmuster plus Endung (`C0001M01.XML` zu `C0001.MP4`). Die
ersten beiden gelten für alle Sidecar-Endungen; die dritte fängt die Sony-Video-Sidecars ab,
die sonst durchfallen würden. `gruppen.py` benutzt das Ergebnis, um Gruppen zu bilden; die
Einordnung selbst bleibt reine Logik und damit in Sekunden durchtestbar.

`aufraeumen.py` ist das einzige Modul, das löscht. Bei Quelldateien aus dem Bestand der
Datenbank fragt es vor jeder Datei den Status ab und arbeitet ausschließlich mit `geprueft`
und `duplikat_bestaetigt`; jeder andere Status führt dazu, dass die Datei stehen bleibt. Der
Status allein reicht nicht — dazu kommt die Frischlesung **beider** Dateien im aktuellen
Lauf, der Quelldatei wie der Zieldatei (SPEC §5, Begründung in 4.10). Davon getrennt und eng
begrenzt sind die beiden Dateiarten, die nie in der Datenbank stehen: die Reste-Dateien aus
Phase 6 und liegengebliebene `.part`-Dateien. Gebaut wird das Modul trotzdem erst in seiner
eigenen Phase.

---

## 2. Datenbank

Eine SQLite-Datei, also eine einzelne Datei ohne Server im Hintergrund. Sie merkt sich jeden
Schritt, damit ein Lauf nach einem Absturz genau dort weitergeht, wo er war.

### Wo die Datenbank liegt

Immer auf einer lokalen Platte, nie auf einem Netzlaufwerk. Die Pfade je Betriebssystem, der
Docker-Fall und die beiden Überschreibungen (`datenbank_ort`, `FOTOSORT_DATENBANK`) stehen in
SPEC §6 und werden hier nicht wiederholt. Hier steht der Grund: SQLite verlässt sich auf
Dateisperren, die über SMB nicht zuverlässig funktionieren. Eine Datenbank auf dem NAS wäre
nicht nur langsam, sondern im ungünstigen Fall beschädigt — und sie ist das Gedächtnis
darüber, was schon sicher im Ziel liegt.

Stellt `pfade.py` fest, dass der eingestellte Datenbankpfad auf einem Netzlaufwerk liegt,
bricht das Programm mit einer verständlichen Meldung ab. Kein stilles Ausweichen auf einen
anderen Journal-Modus, kein halb funktionierender Betrieb: Ein anderer Journal-Modus würde
das Problem nicht lösen, sondern nur verdecken — die Sperren blieben unzuverlässig, der
Schaden fiele erst später auf.

Woran `pfade.py` einen Netzpfad erkennt — dasselbe Verfahren, das auch über „gleiches
Laufwerk" entscheidet (SPEC §4 Phase 3):

- **Windows:** ein UNC-Präfix im Pfad (`\\server\freigabe`), sonst `GetDriveType` für das
  Laufwerk des Pfades; Ergebnis `DRIVE_REMOTE` heißt Netzlaufwerk. Verbundene
  Laufwerksbuchstaben werden dabei zuerst auf ihr Ziel aufgelöst, damit ein `Z:`, das auf eine
  Freigabe zeigt, nicht als lokale Platte durchgeht.
- **Linux:** der Dateisystemtyp des Einhängepunkts, zu dem der Pfad gehört. Welche Typen als
  Netz gelten, zählt SPEC §6 vollständig auf. Dazu gehören auch `9p` und `virtiofs`, und zwar
  aus einem Grund, den man leicht übersieht: Docker Desktop und WSL2 binden Windows-Pfade so
  ein. Der Pfad sieht dann wie ein gewöhnlicher lokaler Ordner aus, die Dateisperren sind dort
  aber ebenso unzuverlässig wie über SMB.

Lässt sich der Typ nicht bestimmen, gilt der Pfad als Netzpfad. Die vorsichtige Antwort
kostet im schlimmsten Fall einen Kopiervorgang statt eines Umbenennens; die unvorsichtige
kostet im schlimmsten Fall Bilder.

Zusammengehalten werden lokale Datenbank und Zielordner durch die **Archiv-ID**. Ihre Form,
ihr Ort im Ziel und ihr Dateiname stehen in SPEC §6 und werden hier nicht wiederholt. Hier
steht der Grund: Dieselbe ID liegt im Ziel und bildet zugleich den Namen des lokalen
Datenbankordners. So findet ein Lauf Monate später die richtige Datenbank wieder, auch wenn
das Ziel inzwischen unter einem anderen Laufwerksbuchstaben hängt. Aus demselben Grund wird
eine vorhandene, aber unlesbare ID nie durch eine neue ersetzt, sondern führt zum Abbruch:
Eine neue ID zeigte auf eine neue, leere Datenbank, das Programm hielte das Ziel für leer und
kopierte alles noch einmal.

Im Ziel liegen unter `.fotosortierer/` nur drei Dinge: die Archiv-ID, die Berichte und nach
jeder abgeschlossenen Phase eine Sicherungskopie der Datenbank. Die Dateinamen und das
Verfahren mit genau zwei aufbewahrten Ständen stehen in SPEC §6. Hier steht, warum es die
SQLite-Backup-Funktion sein muss und kein einfaches Kopieren der Datei: Nur sie erzeugt von
einer Datenbank, die gerade benutzt wird, eine in sich stimmige Kopie; ein Dateikopiervorgang
könnte einen halb geschriebenen Zustand einfangen. Das Ergebnis liegt danach als ganz normale
Datei im Ziel. Gearbeitet wird nie in dieser Kopie. Geht die lokale Datenbank verloren, holt
`fotosort wiederherstellen` sie daraus zurück (SPEC §8).

### Tabelle `dateien` — eine Zeile pro Quelldatei

Die Spalten sind dieselben wie in SPEC §6; hier steht zu jeder, wofür sie gebraucht wird.

| Spalte | Inhalt |
|---|---|
| `quellpfad` | absoluter, aufgelöster Pfad der Quelldatei. Er ist eindeutig und damit der Schlüssel der Tabelle |
| `quellwurzel` | der beim Scan angegebene Quell-Wurzelordner. Daraus ergibt sich der Pfad relativ zur Wurzel für die Ausschlussmuster — und deshalb muss `--quelle` nur beim Scan angegeben werden (SPEC §8) |
| `groesse`, `mtime` | Größe und Änderungsdatum beim letzten Scan; zusammen die Grundlage der Änderungserkennung beim zweiten Scan |
| `dateityp` | `foto`, `raw`, `video` oder `sidecar`. Nur diese vier gelten als echter Dateityp; daran hängt, dass keine Datei aus dem Bestand der Datenbank je als Reste-Datei durchgeht (SPEC §5) |
| `gruppe` | Kennung der zusammengehörigen Dateien (RAW+JPG+Sidecars). Alle Dateien einer Gruppe bekommen denselben Zielordner und denselben Namensanhang |
| `hash` | BLAKE3-Prüfsumme der Quelldatei, wird beim Kopieren nebenbei berechnet; bei umbenannten Dateien erst in der Prüf-Phase aus der Zieldatei. Leer, solange die Datei noch nicht gelesen wurde |
| `kamera` | fertiger Ordnername nach der Alias-Tabelle, z. B. `A7C2` |
| `kamera_modell` | roher Modellname aus den Metadaten, für die Liste der gefundenen Modelle |
| `aufnahme_zeit` | ermitteltes Datum mit Uhrzeit, als Ortszeit; daraus werden die Ordner gebildet |
| `datum_quelle` | welche der sechs Datumsquellen aus SPEC §3 gewonnen hat, als Zahl 1 bis 6 |
| `datum_sicher` | 0 oder 1. Unsicher ist ausschließlich das Datum aus Quelle 6; das steuert `_Ohne_Datum/` |
| `datum_hinweis` | leer, `zeitzone_angenommen` oder `dateiname_ohne_uhrzeit` — die Berichtszählungen aus §10 |
| `zielpfad` | in Phase 2 berechneter, später tatsächlicher Zielpfad samt Anhang `_1`, `_2` … bei Namenskonflikten; leer, solange nicht berechnet |
| `status` | siehe unten |
| `fehlergrund` | Klartext bei `fehler` und `uebersprungen`, landet so im Bericht; sonst leer |
| `bestaetigt_in_lauf` | Nummer des Laufs, in dem Quelldatei **und** Zieldatei zuletzt frisch gelesen und ihre Hashes verglichen wurden — gilt für `geprueft` und `duplikat_bestaetigt` gleichermaßen |
| `umbenannt` | 1, wenn der laufende Anspruch (`kopieren_laeuft`) ein Verschieben durch Umbenennen ist; so erkennt der nächste Start nach einem Absturz ein fertiges Umbenennen (Quelle weg, Zieldatei da) |
| `gefunden_in_lauf` | Nummer des Laufs, in dem diese Zeile angelegt wurde |
| `zuletzt_gesehen_in_lauf` | Nummer des letzten Laufs, in dem der Quellpfad beim Scan noch vorhanden war. Daran wird „Quelle nicht mehr vorhanden" erkannt |

Die Metadaten bekommen **eigene Spalten** (`kamera`, `aufnahme_zeit`, `datum_quelle`,
`datum_sicher`) und stehen nicht zusammen in einem JSON-Feld. Der Grund ist schlicht: Nach
ihnen wird gefiltert und sortiert, und das soll die Datenbank tun. Aus einem JSON-Feld müsste
das Programm für jede Auswertung jede Zeile einzeln auspacken.

Eine Zeile wird nie gelöscht, auch dann nicht, wenn der Quellpfad verschwunden ist (SPEC §6).
Die Datenbank ist das Gedächtnis des Archivs; eine gelöschte Zeile wäre eine verlorene Spur.
Stattdessen bleibt sie stehen, `zuletzt_gesehen_in_lauf` bleibt auf dem alten Wert, und der
Bericht führt sie unter „Quelle nicht mehr vorhanden".

Zwei Zusatzlisten des Berichts (SPEC §10) entstehen direkt aus diesen Spalten, ohne zweite
Buchhaltung: „Zeitzone angenommen" aus `datum_quelle` = 3, die umbenannten Dateien aus
`status` = `verschoben`.

### Status

```
gefunden → analysiert → kopieren_laeuft → kopiert → geprueft → quelle_geloescht
                     ↘ verschoben
                     ↘ duplikat → duplikat_bestaetigt → quelle_geloescht
                     ↘ uebersprungen
                     ↘ fehler
```

`kopieren_laeuft` ist ein Anspruch auf den Zielpfad, kein Fortschritt: Er wird gesetzt, **bevor**
die Zieldatei angelegt wird. Nur so lässt sich eine abgebrochene Kopie später von einem fertigen
Archivbild unterscheiden, ohne sich auf das Fehlen eines anderen Status zu verlassen — Status
fallen zurück, ein Archivbild bliebe dabei auf der Strecke (SPEC §5).

Die hier genannten Werte sind genau die, die in der Datenbank stehen — ohne Umlaute, eine
zweite Schreibweise gibt es nicht (SPEC §6).

Der Status ist die Voraussetzung dafür, dass mit einer Datei überhaupt etwas passieren darf.
Gelöscht werden darf **nur** aus `geprueft` und `duplikat_bestaetigt`; kein anderer Status
berechtigt dazu (SPEC §4 Phase 5). Der Status allein genügt aber nicht: Vor jeder Löschung
kommt die Frischlesung von Quelldatei und Zieldatei im aktuellen Lauf dazu (SPEC §5, 4.10).

`duplikat_bestaetigt` bekommt eine Quelldatei nur dann, wenn die inhaltsgleiche Zieldatei
**im aktuellen Lauf** vollständig neu gelesen wurde und ihr Hash mit dem der Quelle
übereinstimmt (SPEC §5). Ein Hash aus einem früheren Lauf oder aus dem Ziel-Index genügt
nicht — das wäre genau der Fehler aus 4.1.

Buchgeführt wird das in der Spalte `bestaetigt_in_lauf`. Sie ist keine Eigenschaft eines
einzelnen Status, sondern die Buchführung über die Frischlesung, und sie gilt für beide
löschberechtigenden Status **gleichermaßen**: Steht dort nicht die Nummer des laufenden
Laufs, wird vor dem Löschen erneut frisch gelesen und verglichen — Quelldatei **und**
Zieldatei (SPEC §6, „Was ein Lauf ist"). Lässt sich dabei nicht beides bestätigen, bleibt die
Datei stehen und wird im Bericht aufgeführt. Für `geprueft` gilt das aus demselben Grund wie
für `duplikat_bestaetigt`: Die Prüfung aus Phase 4 kann Wochen her sein und sagt nichts
darüber, wie Quelle und Ziel jetzt aussehen.

**Ein Lauf ist ein Programmstart** (SPEC §6). Jeder Start legt in der Tabelle `laeufe` eine
Zeile mit einer Nummer an, und genau diese Nummer steht in `bestaetigt_in_lauf`. Ein
Neustart, der nur dieselbe Phase fortsetzt, ist deshalb ein neuer Lauf — jede frühere
Bestätigung verfällt damit von selbst. Das ist gewollt: Zwischen zwei Programmstarts kann
alles passiert sein, und keine Zeile in der Datenbank weiß davon.

`verschoben` steht für Dateien, die auf demselben Laufwerk durch Umbenennen ins Ziel
gekommen sind (SPEC §4 Phase 3). Dass die Zieldatei existiert und die Größe stimmt, wird
direkt nach dem Umbenennen in Phase 3 geprüft; erst danach wird der Status gesetzt. Für sie
gibt es keine Quelle mehr, gegen die gehasht werden könnte: Die Prüf-Phase berechnet deshalb
nur noch den Hash aus der Zieldatei und trägt ihn in den Ziel-Index nach.
`quelle_geloescht` folgt darauf nicht — die Quelle ist mit dem Umbenennen verschwunden, es
gibt nichts mehr aufzuräumen.

`uebersprungen` ist kein Fehler, sondern der normale Fall für Dateitypen außerhalb der Liste
aus SPEC §3. Sie werden gezählt, aber nie angefasst. Denselben Status bekommt ein Sidecar
ohne Hauptdatei, mit diesem Grund im Klartext. Sidecars sind ein eigener Dateityp und stehen
in der Liste (SPEC §3); „übersprungen nach Typ" ist ein Sidecar deshalb nie.

### Tabelle `ziel_index` — was liegt schon im Ziel

`zielpfad` (eindeutig und damit Schlüssel), `groesse`, `mtime`, `hash` und
`zuletzt_gelesen_in_lauf` (SPEC §6).

Spart beim zweiten Lauf das erneute Hashen des gesamten Archivs: Größe und Änderungsdatum
entscheiden, ob überhaupt neu gehasht werden muss. **Darf nur Kopien überspringen, nie eine
Löschung rechtfertigen** (SPEC §6). Für eine Löschung liefert er höchstens Kandidaten, die
anschließend frisch gelesen werden — die Begründung steht in 4.1 und 4.10. Bei umbenannten
Dateien (`verschoben`) wird der Hash hier in der Prüf-Phase nachgetragen.

### Tabelle `laeufe` — Verlauf

Eine Zeile je Programmstart: `nummer`, `befehl`, `start`, `ende` (SPEC §6). Die `nummer` ist
der Wert, der in `bestaetigt_in_lauf`, `gefunden_in_lauf` und `zuletzt_gesehen_in_lauf` steht
— deshalb braucht ein Lauf überhaupt eine Nummer. Stürzt das Programm ab oder wird es mit
Strg+C beendet, bleibt `ende` leer; daran ist ein abgebrochener Lauf später erkennbar. Aus
diesen Zeilen entsteht der Verlauf im Bericht, und Geschwindigkeitsmessungen zwischen
verschiedenen Einstellungen lassen sich vergleichen.

### Tabelle `quellen` — die Liste der Quellordner

`wurzel`, `hinzugefuegt_in_lauf`, `zuletzt_gescannt_in_lauf`, `erreichbar`, `laufwerk` (SPEC §6).
Ein Archiv hat viele Quellen — verschiedene Platten, Ordner, Netzlaufwerke —, und alle gehen in
dasselbe Ziel. Die Tabelle merkt sich, welche das sind, damit `scan` ohne Angabe alle kennt und
eine gerade nicht eingesteckte Platte als nicht erreichbar gemeldet wird, statt dass ihre
Bilder als verschwunden gelten. `laufwerk` gruppiert die Quellen für den parallelen Durchlauf:
zwei Quellen auf derselben Platte nacheinander, zwei Platten gleichzeitig. Der Datenbankzugriff
bleibt dabei einsträngig — die Durchläufe sammeln in eine Warteschlange, verbucht wird im
Hauptstrang. SQLite-Verbindungen sind nicht dafür gebaut, aus mehreren Strängen beschrieben zu
werden; so bleibt das Sammelschreiben aus §6 unverändert.

### Tabelle `lauf_ereignisse` — was zu keiner Datei gehört

`lauf_nummer`, `art`, `pfad`, `anzahl`, `text` (SPEC §6). Mehrere Listen des Berichts gehören zu
keiner Zeile in `dateien`: ein durch `ausschlussmuster` übersprungener Pfad kommt gar nicht erst
in die Datenbank, eine nicht verfolgte Ordner-Verknüpfung ebenso wenig, und ein Zähler wie „so
oft wurde auf Kopieren zurückgefallen" gehört zu gar keiner Datei. Ohne eigene Tabelle müsste der
Bericht das aus dem Speicher des laufenden Prozesses nehmen — und wäre nach einem Absturz
unvollständig. Genau das soll die Datenbank verhindern.

### Geschwindigkeit

- Statuswechsel gesammelt schreiben (alle 500 Dateien oder alle 2 Sekunden, je nachdem was
  zuerst kommt). Einzelne Schreibvorgänge würden den ganzen Lauf ausbremsen.
- Indizes auf `status`, `hash`, `gruppe`, `zielpfad` — das sind die vier Spalten, nach
  denen tatsächlich gesucht wird.
- WAL-Modus durchgehend. Der frühere Vorbehalt galt nur Netzlaufwerken; da die Datenbank
  jetzt immer lokal liegt, entfällt er.

---

## 3. Abhängigkeiten

Jede zusätzliche Bibliothek ist etwas, das später im Docker-Container installiert sein muss
und kaputtgehen kann. Darum bewusst wenige:

| Paket | Wofür | Warum nicht anders |
|---|---|---|
| `blake3` | Prüfsummen | BLAKE3 ist beides zugleich: kryptografisch und schnell. Es ist deutlich schneller als SHA-256 aus der Standardbibliothek und meist schneller, als die Platte liefern kann — der Hash kostet also praktisch keine Extrazeit. Weil derselbe Hash hier über eine Löschung mitentscheidet, darf es keine reine Prüfsumme wie `xxh3` sein (SPEC §7). Die Hashlänge bleibt auf dem Standard der Bibliothek: 256 Bit. Sie wird nirgends gekürzt, und sie wird auch nicht verlängert — 256 Bit sind der Wert, auf den sich die Kollisionsrechnung in 4.6 bezieht. |
| `tzdata` | Zeitzonendatenbank | Videos ohne Zeitzonen-Offset werden von UTC in die Heimat-Zeitzone umgerechnet (SPEC §3). Python bringt dafür `zoneinfo` mit, holt sich die Zeitzonendaten aber aus dem Betriebssystem. Windows hat keine, dort scheitert `Europe/Berlin` ohne dieses Paket. Aufgenommen wird es trotzdem **unbedingt**, nicht als bedingte Abhängigkeit für Windows: Die Alternative wäre die Annahme, dass jedes Container-Image eine Zeitzonendatenbank mitbringt, und schlanke Images bringen sie oft nicht mit. Das Paket ist klein und schadet unter Linux nicht — dort wird es schlicht nicht gebraucht. In `pyproject.toml` steht es deshalb ohne jede Bedingung, insbesondere **nicht** mit einer Markierung wie `platform_system == "Windows"`. |
| `rich` | Fortschrittsbalken, Tabellen | Ein Balken mit Restzeit ist bei stundenlangen Läufen kein Luxus. Selbstgebaut wäre das mehr Code als die Bibliothek. |
| `tomli-w` | `config.toml` schreiben | Python kann TOML seit 3.11 **lesen** (`tomllib`), aber nicht schreiben. Wird nur beim ersten Start gebraucht. |
| `fastapi`, `uvicorn` | Oberfläche (Phase 7) | Der Server hinter der Seite: kleine JSON-Anfragen, nur auf 127.0.0.1. FastAPI liefert Routing und Fehlerbehandlung, uvicorn den Server in einem eigenen Strang des Programms. Kein Rahmenwerk auf der Seite selbst. |
| `PySide6-Essentials` | Desktop-Fenster (Phase 7) | Qt: ein richtiges Windows-Programm mit Taskleisten-Symbol und den normalen Ordnerdialogen, ohne Browser und ohne weitere Laufzeit auf dem PC. pywebview/pythonnet (WebView2) fielen in v0.3 auf dem echten PC aus. Nur „Essentials" (Core, Gui, Widgets), nicht das volle Qt. Im Container (Phase 8) wird es nicht gebraucht, dort läuft `--ohne-fenster`. |
| `pytest`, `httpx` | Tests | Standard; `httpx` nur für den Testclient der Schnittstelle. Nur zum Entwickeln, nicht im Betrieb. |

Ausdrücklich **nicht**:

- **Keine CLI-Bibliothek** (Typer, Click). Das mitgelieferte `argparse` reicht für die
  Unterbefehle aus der SPEC.
- **`exiftool` ist kein Python-Paket**, sondern ein externes Programm. Es wird beim Start
  gesucht und mit einer verständlichen Meldung samt Download-Adresse angemahnt, wenn es fehlt.
- **Kein Rahmenwerk auf der Seite** (React, Vue …). Die Seite der Oberfläche ist eine HTML-Datei
  mit etwas JavaScript; sie zeigt nur, was der Server fertig formatiert liefert.

---

## 4. Wo Bilder verloren gehen könnten

Die ehrliche Liste. Je Risiko: wodurch es abgesichert ist und welcher Test das beweist.

### 4.1 Löschen auf Basis eines veralteten Hashes

**Der gefährlichste Punkt.** Der Ziel-Index speichert Hashes, prüft aber später nur noch
Größe und Änderungsdatum. Wurde die Zieldatei außerhalb des Programms verändert, gilt die
Quelldatei fälschlich als gesichert und wird gelöscht.

*Absicherung:* Der Ziel-Index findet nur **Kandidaten** für Duplikate, er entscheidet nie
über eine Löschung. Vor jeder Löschung werden Zieldatei **und** Quelldatei im aktuellen Lauf
frisch gelesen und gehasht — bei `geprueft` genauso wie bei `duplikat_bestaetigt`. Die
Frischlesung hängt nicht am Status, sondern am Lauf: Sie zählt nur, wenn
`bestaetigt_in_lauf` die Nummer des laufenden Laufs trägt (SPEC §6). Erst die frisch gelesene
Zieldatei ergibt `duplikat_bestaetigt`; warum zusätzlich die Quelle gelesen wird, steht in
4.10. Keine Abschaltmöglichkeit, keine Option, kein Schnellmodus (SPEC §5 und §6).

*Test:* Zieldatei nach dem Kopieren verändern, Größe und Änderungsdatum künstlich gleich
lassen — die Quelldatei darf nicht gelöscht werden.

### 4.2 Abbruch mitten im Kopieren

Stromausfall oder Strg+C hinterlässt eine halb geschriebene Zieldatei, die beim nächsten Lauf
für vollständig gehalten wird.

*Absicherung:* Geschrieben wird in `<name>.part`. Erst wenn die Datei vollständig und
gehasht ist, wird sie atomar umbenannt — ein Vorgang, der entweder ganz oder gar nicht
passiert. Eine Datei unter ihrem richtigen Namen ist damit immer vollständig. Der Name der
temporären Datei ist der vollständige Zieldateiname plus `.part` (SPEC §5) — nicht der
Stammname, sonst ergäbe ein RAW+JPG-Paar zweimal denselben `.part`-Namen. Liegengebliebene
`.part`-Dateien werden beim nächsten Start erkannt und nur dann entfernt, wenn keine Zeile in
der Datenbank sie beansprucht; eine beanspruchte Datei wird vom zugehörigen Kopiervorgang neu
geschrieben.

*Test (Pflicht laut SPEC §11):* Prozess mitten im Kopieren hart beenden, neu starten.
Ergebnis muss identisch zu einem ungestörten Lauf sein.

### 4.3 Überschreiben bei Namenskonflikt

Zwei Kameras vergeben denselben Dateinamen (`DSC01234.ARW` gibt es mehrfach, sobald der Zähler
überläuft). Ohne Vorkehrung überschreibt das zweite Bild das erste.

*Absicherung:* Vor jedem Schreiben wird geprüft, ob der Zielname existiert. Gleicher Hash →
Duplikat, nicht kopieren. Anderer Inhalt → Anhang `_1`. Überschrieben wird nie, unter keinen
Umständen.

*Gebaut (Phase 3):* `kopieren.py` kopiert in `<Zielname>.part` und rechnet dabei den Hash. Erst
danach fällt die Entscheidung: Liegt unter dem Zielnamen (oder laut Ziel-Index unter einem
anderen Namen) dieselbe Datei, wird die eigene `.part`-Datei entfernt und die Zeile `duplikat`.
Sonst bekommt die ganze Gruppe den kleinsten freien Anhang, eingefügt hinter dem Stammnamen der
Hauptdatei, und `pfade.umbenennen_ohne_ueberschreiben` bringt die Datei an ihren Namen. Die
Kopier-Worker fassen nur das Dateisystem an; entscheiden, umbenennen und in die Datenbank
schreiben tut allein der Hauptstrang. Zwei Quellen mit demselben Zielnamen gleichzeitig kann es
nicht geben: Wessen Zielname gerade „in Arbeit" ist, wartet. Der Anspruch (`kopieren_laeuft`,
`kopiert_in_lauf`) wird vor dem ersten Schreiben festgeschrieben, nicht gesammelt — sonst wüsste
der nächste Start nach einem Absturz nicht, wem eine liegengebliebene Datei gehört.

*Test:* Zwei verschiedene Bilder mit identischem Namen und identischem Aufnahmedatum — beide
müssen im Ziel ankommen.

### 4.4 Ziel liegt innerhalb der Quelle

Sortiert man `D:\Fotos` nach `D:\Fotos\Sortiert`, liest der Scan die eigenen Ergebnisse wieder
ein — eine Endlosschleife, die sich selbst füttert.

*Absicherung:* Beim Start werden beide Pfade in `pfade.py` aufgelöst und verglichen — dort
liegt auch diese Prüfung, zusammen mit der Netz- und Laufwerkserkennung. Liegt eines im
anderen, wird das Ziel vom Scan ausgeschlossen oder mit klarer Meldung abgebrochen.

*Test:* Ziel als Unterordner der Quelle setzen.

### 4.5 Groß- und Kleinschreibung zwischen Windows und Linux

Windows behandelt `IMG_1234.JPG` und `img_1234.jpg` als dieselbe Datei, Linux als zwei
verschiedene. Auf dem NAS könnten also zwei Dateien liegen, die Windows später für eine hält.

*Absicherung:* Vergleiche laufen immer über den Hash, nie über den Namen. Beim Prüfen auf
Namenskonflikte wird zusätzlich ohne Rücksicht auf Groß-/Kleinschreibung verglichen, damit
sich das Verhalten auf beiden Systemen gleich anfühlt.

*Test:* Zwei Dateien, die sich nur in der Schreibweise unterscheiden.

### 4.6 Prüfsummen-Kollision

Zwei verschiedene Bilder ergäben denselben Hash, das zweite gilt als Duplikat und wird nie
kopiert — die Quelle dürfte gelöscht werden. Der Hash ist hier die letzte Absicherung vor
dem Verlust.

*Absicherung:* BLAKE3 ist ein kryptografischer Hash mit 256 Bit. Eine Kollision zufällig zu
treffen ist um viele Größenordnungen unwahrscheinlicher als ein unbemerkter Lesefehler der
Festplatte, und eine absichtlich erzeugte Kollision ist nach heutigem Stand niemandem
möglich. Genau deshalb steht hier BLAKE3 und keine reine Prüfsumme.

Zusätzlich gibt es die Option `byte_vergleich_vor_loeschen` (Standard: **aus**, SPEC §5). Ist
sie an, werden Quelle und Ziel vor dem Löschen Byte für Byte verglichen.

*Was sie kostet:* Quelldatei und Zieldatei werden vor jeder Löschung ohnehin beide
vollständig frisch gelesen (SPEC §5, Begründung in 4.10). Die Option kostet deshalb **keinen
zusätzlichen Lesevorgang**, sondern nur den Vergleich selbst: Statt die beiden Hashes
gegeneinander zu halten, werden die Inhalte blockweise verglichen. Das ist Rechenzeit auf
Daten, die ohnehin durch den Speicher laufen — spürbar bei mehreren Terabyte, aber kein
zweiter Durchgang über die Platte.

*Warum „aus" trotzdem vertretbar ist:* Die Option schützt einzig gegen die Kollision eines
kryptografischen Hashes mit 256 Bit — gegen ein Risiko also, das um Größenordnungen kleiner
ist als die Fehlerrate der Hardware, auf der verglichen wird. Wäre hier eine reine Prüfsumme
im Einsatz, müsste der Standard „an" lauten. Weil BLAKE3 kryptografisch ist, kauft die Option
Rechenzeit gegen keinen messbaren Sicherheitsgewinn. Wer sie trotzdem will, schaltet sie
mit einer Zeile in der `config.toml` ein (SPEC §9).

*Test:* Byte-Vergleich eingeschaltet, Ziel künstlich verändert — die Löschung muss verweigert
werden.

### 4.7 Einzelne Dateien brechen den Lauf ab

Eine unlesbare Datei beendet den ganzen Vorgang nach zwei Stunden, alles bisher Erreichte
wäre unklar.

*Absicherung:* Fehler werden pro Datei aufgefangen, bekommen Status `fehler` mit Klartext-Grund
und landen im Bericht. Der Lauf geht weiter.

*Test:* Datei ohne Leserechte, defekte EXIF-Daten, Pfad jenseits der 260 Zeichen — alle drei
im Testbaum. Der lange Pfad muss unter Windows über das Präfix aus `pfade.py` trotzdem
gelingen; der Fehlergrund „Pfad zu lang" greift nur, wenn auch das scheitert (SPEC §5).

### 4.8 Falsch erkanntes „gleiches Laufwerk"

Beim Verschieben wird umbenannt statt kopiert, wenn Quelle und Ziel auf demselben Laufwerk
liegen (SPEC §4 Phase 3). Der Laufwerksbuchstabe beweist das aber nicht: Unter Windows kann
ein Ordner ein Einhängepunkt auf ein anderes Volume sein, unter Linux ein eigenes Dateisystem,
und `\\server\freigabe1` und `\\server\freigabe2` sehen gleich aus, liegen aber womöglich auf
verschiedenen Datenträgern.

Wird das falsch erkannt, ist das Umbenennen kein geänderter Verzeichniseintrag mehr, sondern
in Wahrheit ein Kopiervorgang über eine Laufwerksgrenze. Der übliche Ausgang ist eine
Fehlermeldung des Betriebssystems, die Datei bleibt stehen. Der schlimme Ausgang ist ein
Abbruch mittendrin: Dann liegt im Ziel eine halb geschriebene Datei unter ihrem endgültigen
Namen, und der nächste Lauf hält sie für vollständig — genau die Zusicherung aus 4.2 wäre
verletzt, ohne dass es jemand merkt.

*Absicherung:* Ob zwei Pfade auf demselben Laufwerk liegen, stellt `pfade.py` über die
Kennung des Dateisystems fest (unter Linux `st_dev`, unter Windows die Volume-Kennung), nie
über den Pfadtext. Lässt es sich nicht sicher feststellen, wird kopiert und geprüft — die
langsamere, aber nachweisbare Variante. Nach dem Umbenennen werden Existenz und Größe der
Zieldatei geprüft; schlägt das fehl, bekommt die Datei Status `fehler` und wird im Bericht
aufgeführt.

Dazu kommt eine zweite, härtere Absicherung: **Ein Netzlaufwerk gilt nie als „gleiches
Laufwerk"** (SPEC §4 Phase 3). Liegt auch nur einer der beiden Pfade auf einem Netzlaufwerk,
gilt die Frage als nicht nachgewiesen, und es wird kopiert. Erkannt wird das mit dem
Verfahren aus §2 (UNC-Präfix und `DRIVE_REMOTE` unter Windows, Dateisystemtyp des
Einhängepunkts unter Linux). Der Grund: Gerade bei Freigaben sieht der Pfadtext nach einem
gemeinsamen Laufwerk aus, während auf der Serverseite zwei verschiedene Datenträger liegen
können, und die Kennung des Dateisystems ist über SMB nicht verlässlich.

*Test:* Zwei Pfade auf verschiedenen Dateisystemen — das Programm muss kopieren statt
umbenennen. Dazu ein Test, in dem `pfade.py` künstlich „gleiches Laufwerk" meldet, obwohl es
nicht stimmt: Das Umbenennen scheitert, die Quelle muss unangetastet bleiben. Dazu der
Pflicht-Test aus SPEC §11: Bei einem Netzpfad auf einer der beiden Seiten wird kopiert, nicht
umbenannt.

### 4.9 Umbenennen überschreibt stillschweigend

`os.rename` und `Path.rename` ersetzen unter POSIX eine vorhandene Zieldatei ohne Fehler und
ohne Rückfrage. Das ist kein theoretischer Fall: Umbenannt wird an zwei Stellen — beim
Verschieben auf demselben Laufwerk (SPEC §4 Phase 3) und beim abschließenden Umbenennen der
`.part`-Datei auf ihren endgültigen Namen (4.2). Ist der Zielname bereits belegt, weil dort
schon ein Bild liegt, verschwindet dieses Bild, und zwar spurlos: Das Programm bekommt keinen
Fehler zu sehen, die Datei erscheint in keinem Bericht, und die Datenbank hält den Vorgang
für gelungen. Alle Vorkehrungen aus 4.3 nützen nichts, wenn zwischen Prüfung und Umbenennen
etwas dazwischenkommt oder der Zielname aus einem früheren Lauf stammt.

*Absicherung:* Überall, wo umbenannt wird, wird ein nicht überschreibendes Verfahren benutzt
(SPEC §5). Unter Linux `os.link` auf den Zielnamen und danach `os.unlink` der Quelle — `link`
scheitert, wenn der Name belegt ist —, alternativ `renameat2` mit `RENAME_NOREPLACE`. Unter
Windows `MoveFileEx` **ohne** `MOVEFILE_REPLACE_EXISTING`. Damit wird aus dem stillen
Überschreiben ein Fehler, und auf einen Fehler greift die Regel „Niemals überschreiben" aus
SPEC §5: gleicher Hash ergibt ein Duplikat, anderer Inhalt einen neuen Namen mit Anhang `_1`,
`_2` … Der Umweg über `link` und `unlink` kostet nichts — auch er ändert nur
Verzeichniseinträge und kopiert keine Daten. `pfade.py` kapselt beide Wege, damit `kopieren.py`
nur eine Funktion kennt und niemand versehentlich `Path.rename` benutzt.

*Test (Pflicht laut SPEC §11):* Auf einen bereits belegten Zielnamen umbenennen. Die
vorhandene Zieldatei muss unverändert bleiben, und die Quelldatei muss danach noch da sein.

### 4.10 Quelle ändert sich nach dem Kopieren

Der Verlustpfad, den ein reiner Ziel-Vergleich offen lässt — und der einzige dieser Liste,
den keine der übrigen Absicherungen auffängt. 4.1 schützt gegen eine veränderte **Zieldatei**;
hier ändert sich die **Quelle**.

Wird vor dem Löschen nur die Zieldatei frisch gelesen, wird ihr Hash gegen den beim Kopieren
gespeicherten Quell-Hash gehalten. Beide Werte beschreiben denselben alten Stand. Ändert sich
die Quelldatei nach dem Kopieren — jemand bearbeitet sie, ein Synchronisierungsdienst spielt
eine neue Fassung ein, eine Kamera-Software schreibt sie neu —, stimmen die beiden Werte
weiterhin überein. Die Prüfung meldet, alles sei in Ordnung, und die geänderte Quelle wird
gelöscht. Im Ziel liegt dann die alte Fassung, die neue ist weg, und kein Fehler ist
aufgetreten: Das Programm hat die Frage, die es stellen wollte, nie gestellt.

*Absicherung:* Vor jeder Löschung wird **auch die Quelldatei im aktuellen Lauf** vollständig
neu gelesen und ihr Hash mit dem gespeicherten Quell-Hash verglichen (SPEC §5, §4 Phase 5).
Gelöscht wird nur, wenn Quelle und Ziel in diesem Lauf beide frisch gelesen wurden und beide
denselben Hash tragen wie der gespeicherte Quell-Hash. Bei Abweichungen:

- **Die Quelle weicht ab:** nicht löschen. Der Status fällt auf `analysiert` zurück, denn die
  Datei muss neu kopiert werden; gespeicherter Hash und `bestaetigt_in_lauf` werden geleert.
  Der Hash wird beim nächsten Kopieren neu berechnet. Liegt unter dem berechneten Zielnamen
  schon die alte Fassung, greift „Niemals überschreiben": Die neue Fassung bekommt den Anhang
  `_1`, `_2` … Damit bleiben beide Fassungen erhalten. Die Datei erscheint im Bericht unter
  „Quelle seit dem Kopieren geändert" (SPEC §10) — die wichtigste Liste des Berichts, denn
  jeder Eintrag darin ist ein Bild, das ohne diese Prüfung verloren gewesen wäre.
- **Das Ziel weicht ab:** ebenfalls nicht löschen. Die Datei bekommt Status `fehler` mit
  Grund und erscheint im Bericht (4.1).

*Was es kostet:* Beide Dateien zu lesen bedeutet im Aufräum-Schritt einen vollständigen
Durchgang durch die Quelle zusätzlich zu dem durch das Ziel. Das ist bewusst bezahlt. Die
Alternative ist eine Löschung, die sich auf eine Annahme über die Quelle stützt statt auf eine
Messung — und die oberste Regel des Projekts lässt für Annahmen an dieser Stelle keinen Platz.

*Test (Pflicht laut SPEC §11):* Datei kopieren und prüfen lassen, bis der Status `geprueft`
steht. Dann den Inhalt der Quelldatei ändern. Dann aufräumen lassen. Erwartung: Die
Quelldatei ist danach noch da und trägt ihren neuen Inhalt, die Zieldatei ist unverändert,
der Status steht auf `analysiert`, und die Datei erscheint im Bericht unter „Quelle seit dem
Kopieren geändert". Ohne diesen Test darf nicht gelöscht werden.

---

## 5. Was als Nächstes passiert

Alle elf Punkte aus [`offene_fragen.md`](offene_fragen.md) sind entschieden und in
[`SPEC.md`](SPEC.md) eingearbeitet. Damit gibt es nichts mehr zu klären, bevor gebaut wird.

Als Nächstes Phase 1 laut [`PROMPTS.md`](PROMPTS.md): Grundgerüst mit `pyproject.toml` und
dem Befehl `fotosort`, `config.toml`, das SQLite-Schema samt Ziel-Index, das Skript für den
künstlichen Testbaum (SPEC §11), `fotosort scan` und `fotosort status`, dazu die Prüfungen
beim Start — ExifTool vorhanden, Ziel nicht in der Quelle und umgekehrt, Datenbankpfad nicht
auf einem Netzlaufwerk.

Entwickelt und getestet wird im Linux-Container mit dem künstlichen Testbaum; ExifTool ist
dort installiert. Echte Fotos bleiben außen vor (`CLAUDE.md`, SPEC §11).
