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

Datum, Kamera und Zielpfad sind genau solche Stellen — dort stecken die meisten Regeln der
SPEC und damit die meisten möglichen Fehler. Diese drei Module bekommen nur Werte herein und
geben Werte zurück, ohne die Festplatte anzufassen. So lassen sich hundert Sonderfälle in
Sekunden durchtesten, statt für jeden einen Testordner anzulegen.

```
fotosortierer/
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
│  ├─ metadaten.py           ExifTool-Prozesse verwalten, Felder auslesen
│  ├─ datum.py               Aufnahmedatum bestimmen        ← reine Logik
│  ├─ kamera.py              Modell → Ordnername, Aliase    ← reine Logik
│  ├─ dateitypen.py          Dateityp, Sidecar-Zuordnung    ← reine Logik
│  ├─ gruppen.py             RAW+JPG, Sidecars              ← reine Logik
│  ├─ ziel.py                Zielpfad bauen, Ordner mit Zusatz finden
│  ├─ hashes.py              BLAKE3-Prüfsummen, Byte-Vergleich
│  ├─ kopieren.py            Phase 3: übertragen
│  ├─ pruefen.py             Phase 4: nachrechnen
│  ├─ aufraeumen.py          Phase 5+6: löschen             ← nur nach Statusprüfung
│  └─ bericht.py             Text- und CSV-Bericht
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

`dateitypen.py` beantwortet zwei Fragen, ohne die Festplatte anzufassen: zu welchem Typ eine
Datei gehört (`foto`, `raw`, `video`, `sidecar`, `sonstiges`) und zu welcher Hauptdatei ein
Sidecar gehört. Für die Sidecar-Zuordnung gelten beide Schreibweisen — Stammname plus Endung
(`DSC01234.xmp`) und vollständiger Dateiname plus Endung (`DSC01234.ARW.xmp`), für alle
Sidecar-Endungen. `gruppen.py` benutzt das Ergebnis, um Gruppen zu bilden; die Einordnung
selbst bleibt reine Logik und damit in Sekunden durchtestbar.

`aufraeumen.py` ist das einzige Modul, das löscht. Es fragt vor jeder Datei den Status ab und
arbeitet ausschließlich mit `geprueft` und `duplikat_bestaetigt`; jeder andere Status führt
dazu, dass die Datei stehen bleibt. Gebaut wird es trotzdem erst in seiner eigenen Phase.

---

## 2. Datenbank

Eine SQLite-Datei, also eine einzelne Datei ohne Server im Hintergrund. Sie merkt sich jeden
Schritt, damit ein Lauf nach einem Absturz genau dort weitergeht, wo er war.

### Wo die Datenbank liegt

Immer auf einer lokalen Platte, nie auf einem Netzlaufwerk (SPEC §6): unter Windows in
`%LOCALAPPDATA%\fotosortierer\<archiv-id>\`, unter Linux und im Docker-Container in einem
eigenen lokalen Pfad bzw. Volume. Der Grund ist technisch: SQLite verlässt sich auf
Dateisperren, die über SMB nicht zuverlässig funktionieren. Eine Datenbank auf dem NAS wäre
nicht nur langsam, sondern im ungünstigen Fall beschädigt — und sie ist das Gedächtnis
darüber, was schon sicher im Ziel liegt.

Stellt `pfade.py` fest, dass der eingestellte Datenbankpfad auf einem Netzlaufwerk liegt,
bricht das Programm mit einer verständlichen Meldung ab. Kein stilles Ausweichen auf einen
anderen Journal-Modus, kein halb funktionierender Betrieb.

Zusammengehalten werden lokale Datenbank und Zielordner durch die **Archiv-ID**. Sie steht in
einer Datei im Ziel unter `.fotosortierer/` und im Namen des lokalen Datenbankordners. So
findet ein Lauf Monate später die richtige Datenbank wieder, auch wenn das Ziel inzwischen
unter einem anderen Laufwerksbuchstaben hängt.

Im Ziel liegen unter `.fotosortierer/` nur drei Dinge: die Archiv-ID, die Berichte und nach
jeder abgeschlossenen Phase eine Sicherungskopie der Datenbank. Die Sicherung wird über die
SQLite-Backup-Funktion geschrieben — sie erzeugt eine in sich stimmige Kopie — und danach als
ganz normale Datei ins Ziel gelegt. Gearbeitet wird nie in dieser Kopie. Geht die lokale
Datenbank verloren, holt `fotosort wiederherstellen` sie daraus zurück (SPEC §8).

### Tabelle `dateien` — eine Zeile pro Quelldatei

| Spalte | Inhalt |
|---|---|
| `id` | laufende Nummer |
| `quellpfad` | voller Pfad, eindeutig |
| `groesse`, `mtime` | Größe und Änderungsdatum, zum Wiedererkennen |
| `typ` | `foto`, `raw`, `video`, `sidecar`, `sonstiges` |
| `gruppe_id` | verweist auf die Hauptdatei der Gruppe (RAW+JPG+Sidecar) |
| `hash` | BLAKE3-Prüfsumme, wird beim Kopieren nebenbei berechnet; bei umbenannten Dateien erst in der Prüf-Phase aus der Zieldatei |
| `kamera` | fertiger Ordnername, z. B. `A7C2` |
| `aufnahme_zeit` | ermitteltes Datum mit Uhrzeit |
| `datum_quelle` | woher es kam: `exif`, `video_offset`, `video_utc`, `dateiname`, `dateiname_ohne_uhrzeit`, `mtime` |
| `datum_sicher` | Ja/Nein — steuert `_Ohne_Datum/` |
| `zielpfad` | in Phase 2 berechnet, noch nicht angelegt |
| `status` | siehe unten |
| `bestaetigt_in_lauf` | Nummer des Laufs, in dem die Zieldatei frisch gelesen und verglichen wurde — nur bei `duplikat_bestaetigt` gefüllt |
| `fehler_grund` | Klartext, landet so im Bericht |
| `aktualisiert_am` | Zeitstempel des letzten Statuswechsels |

Die drei Zusatzlisten des Berichts (SPEC §10) entstehen direkt aus diesen Spalten, ohne
zweite Buchhaltung: „Zeitzone angenommen" aus `datum_quelle = video_utc`, die Zählung der
nicht angewendeten Tagesgrenze aus `dateiname_ohne_uhrzeit`, die umbenannten Dateien aus
`status = verschoben`.

### Status

```
gefunden → analysiert → kopiert → geprueft → quelle_geloescht
                     ↘ verschoben
                     ↘ duplikat → duplikat_bestaetigt → quelle_geloescht
                     ↘ uebersprungen
                     ↘ fehler
```

Der Status ist die einzige Wahrheit darüber, was mit einer Datei passieren darf.
Gelöscht werden darf **nur** aus `geprueft` und `duplikat_bestaetigt`; kein anderer Status
berechtigt dazu (SPEC §4 Phase 5).

`duplikat_bestaetigt` bekommt eine Quelldatei nur dann, wenn die inhaltsgleiche Zieldatei
**im aktuellen Lauf** vollständig neu gelesen wurde und ihr Hash mit dem der Quelle
übereinstimmt (SPEC §5). Ein Hash aus einem früheren Lauf oder aus dem Ziel-Index genügt
nicht — das wäre genau der Fehler aus 4.1. Umgesetzt wird das über die Spalte
`bestaetigt_in_lauf`: Steht dort nicht die Nummer des laufenden Laufs, gilt die Datei wieder
als `duplikat` und wird vor dem Löschen erneut verglichen.

`verschoben` steht für Dateien, die auf demselben Laufwerk durch Umbenennen ins Ziel
gekommen sind (SPEC §4 Phase 3). Für sie gibt es keine Quelle mehr, gegen die geprüft werden
könnte: Die Prüf-Phase stellt fest, dass die Zieldatei existiert und die Größe stimmt, und
trägt ihren Hash in den Ziel-Index nach. `quelle_geloescht` folgt darauf nicht — die Quelle
ist mit dem Umbenennen verschwunden, es gibt nichts mehr aufzuräumen.

`uebersprungen` ist kein Fehler, sondern der normale Fall für Dateitypen außerhalb der Liste
aus SPEC §3. Sie werden gezählt, aber nie angefasst.

### Tabelle `ziel_index` — was liegt schon im Ziel

`pfad`, `groesse`, `mtime`, `hash`, `gesehen_am`.

Spart beim zweiten Lauf das erneute Hashen des gesamten Archivs. **Darf nur Kopien
überspringen, nie eine Löschung rechtfertigen** (SPEC §6). Für eine Löschung liefert er
höchstens Kandidaten, die anschließend frisch gelesen werden — die Begründung steht in 4.1.
Bei umbenannten Dateien (`verschoben`) wird der Hash hier in der Prüf-Phase nachgetragen.

### Tabelle `laeufe` — Verlauf

Pro Phase: Start, Ende, Anzahl Dateien, Bytes, Fehler. Daraus entsteht der Bericht, und
Geschwindigkeitsmessungen zwischen verschiedenen Einstellungen lassen sich vergleichen.

### Geschwindigkeit

- Statuswechsel gesammelt schreiben (alle 500 Dateien oder alle 2 Sekunden, je nachdem was
  zuerst kommt). Einzelne Schreibvorgänge würden den ganzen Lauf ausbremsen.
- Indizes auf `status`, `hash`, `gruppe_id`, `zielpfad` — das sind die vier Spalten, nach
  denen tatsächlich gesucht wird.
- WAL-Modus durchgehend. Der frühere Vorbehalt galt nur Netzlaufwerken; da die Datenbank
  jetzt immer lokal liegt, entfällt er.

---

## 3. Abhängigkeiten

Jede zusätzliche Bibliothek ist etwas, das später im Docker-Container installiert sein muss
und kaputtgehen kann. Darum bewusst wenige:

| Paket | Wofür | Warum nicht anders |
|---|---|---|
| `blake3` | Prüfsummen | BLAKE3 ist beides zugleich: kryptografisch und schnell. Es ist deutlich schneller als SHA-256 aus der Standardbibliothek und meist schneller, als die Platte liefern kann — der Hash kostet also praktisch keine Extrazeit. Weil derselbe Hash hier über eine Löschung mitentscheidet, darf es keine reine Prüfsumme wie `xxh3` sein (SPEC §7). |
| `tzdata` | Zeitzonendatenbank, **nur unter Windows** | Videos ohne Zeitzonen-Offset werden von UTC in die Heimat-Zeitzone umgerechnet (SPEC §3). Python bringt dafür `zoneinfo` mit, holt sich die Zeitzonendaten aber aus dem Betriebssystem. Linux und der Docker-Container haben sie, Windows hat sie nicht — dort scheitert `Europe/Berlin` ohne dieses Paket. In der `pyproject.toml` deshalb als bedingte Abhängigkeit (`platform_system == "Windows"`). |
| `rich` | Fortschrittsbalken, Tabellen | Ein Balken mit Restzeit ist bei stundenlangen Läufen kein Luxus. Selbstgebaut wäre das mehr Code als die Bibliothek. |
| `tomli-w` | `config.toml` schreiben | Python kann TOML seit 3.11 **lesen** (`tomllib`), aber nicht schreiben. Wird nur beim ersten Start gebraucht. |
| `pytest` | Tests | Standard. Nur zum Entwickeln, nicht im Betrieb. |

Ausdrücklich **nicht**:

- **Keine CLI-Bibliothek** (Typer, Click). Das mitgelieferte `argparse` reicht für die
  Unterbefehle aus der SPEC.
- **`exiftool` ist kein Python-Paket**, sondern ein externes Programm. Es wird beim Start
  gesucht und mit einer verständlichen Meldung samt Download-Adresse angemahnt, wenn es fehlt.
- **FastAPI erst in Phase 7.** Bis dahin taucht es nirgends auf.

---

## 4. Wo Bilder verloren gehen könnten

Die ehrliche Liste. Je Risiko: wodurch es abgesichert ist und welcher Test das beweist.

### 4.1 Löschen auf Basis eines veralteten Hashes

**Der gefährlichste Punkt.** Der Ziel-Index speichert Hashes, prüft aber später nur noch
Größe und Änderungsdatum. Wurde die Zieldatei außerhalb des Programms verändert, gilt die
Quelldatei fälschlich als gesichert und wird gelöscht.

*Absicherung:* Der Ziel-Index findet nur **Kandidaten** für Duplikate, er entscheidet nie
über eine Löschung. Vor jeder Löschung wird die Zieldatei im aktuellen Lauf frisch gelesen
und gehasht; erst das ergibt `duplikat_bestaetigt`. Keine Abschaltmöglichkeit, keine Option,
kein Schnellmodus (SPEC §5 und §6).

*Test:* Zieldatei nach dem Kopieren verändern, Größe und Änderungsdatum künstlich gleich
lassen — die Quelldatei darf nicht gelöscht werden.

### 4.2 Abbruch mitten im Kopieren

Stromausfall oder Strg+C hinterlässt eine halb geschriebene Zieldatei, die beim nächsten Lauf
für vollständig gehalten wird.

*Absicherung:* Geschrieben wird in `<name>.part`. Erst wenn die Datei vollständig und
gehasht ist, wird sie atomar umbenannt — ein Vorgang, der entweder ganz oder gar nicht
passiert. Eine Datei unter ihrem richtigen Namen ist damit immer vollständig. Liegengebliebene
`.part`-Dateien werden beim nächsten Start entfernt.

*Test (Pflicht laut SPEC §11):* Prozess mitten im Kopieren hart beenden, neu starten.
Ergebnis muss identisch zu einem ungestörten Lauf sein.

### 4.3 Überschreiben bei Namenskonflikt

Zwei Kameras vergeben denselben Dateinamen (`DSC01234.ARW` gibt es mehrfach, sobald der Zähler
überläuft). Ohne Vorkehrung überschreibt das zweite Bild das erste.

*Absicherung:* Vor jedem Schreiben wird geprüft, ob der Zielname existiert. Gleicher Hash →
Duplikat, nicht kopieren. Anderer Inhalt → Anhang `_1`. Überschrieben wird nie, unter keinen
Umständen.

*Test:* Zwei verschiedene Bilder mit identischem Namen und identischem Aufnahmedatum — beide
müssen im Ziel ankommen.

### 4.4 Ziel liegt innerhalb der Quelle

Sortiert man `D:\Fotos` nach `D:\Fotos\Sortiert`, liest der Scan die eigenen Ergebnisse wieder
ein — eine Endlosschleife, die sich selbst füttert.

*Absicherung:* Beim Start werden beide Pfade aufgelöst und verglichen. Liegt eines im anderen,
wird das Ziel vom Scan ausgeschlossen oder mit klarer Meldung abgebrochen.

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

*Warum „aus" vertretbar ist:* Die Option schützt gegen die Kollision eines kryptografischen
Hashes — gegen ein Risiko also, das kleiner ist als die Fehlerrate der Hardware, auf der
verglichen wird. Bezahlt wird sie mit einem zusätzlichen vollständigen Lesen beider Dateien,
und zwar im Aufräum-Schritt, der ohnehin der langsamste ist. Der ehrliche Satz dazu: Sie
erhöht die Sicherheit nicht messbar, sie kostet aber messbar Zeit. Wer sie trotzdem will,
schaltet sie mit einer Zeile in der `config.toml` ein (SPEC §9).

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

*Test:* Zwei Pfade auf verschiedenen Dateisystemen — das Programm muss kopieren statt
umbenennen. Dazu ein Test, in dem `pfade.py` künstlich „gleiches Laufwerk" meldet, obwohl es
nicht stimmt: Das Umbenennen scheitert, die Quelle muss unangetastet bleiben.

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
