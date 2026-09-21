# Architekturvorschlag

Vorschlag aus Prompt 0, noch nichts davon gebaut. Grundlage ist [`SPEC.md`](SPEC.md);
die Punkte aus [`offene_fragen.md`](offene_fragen.md) können ihn noch verändern.

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
│  │
│  ├─ scan.py                Phase 1: Quelle durchlaufen, zählen
│  ├─ metadaten.py           ExifTool-Prozesse verwalten, Felder auslesen
│  ├─ datum.py               Aufnahmedatum bestimmen        ← reine Logik
│  ├─ kamera.py              Modell → Ordnername, Aliase    ← reine Logik
│  ├─ gruppen.py             RAW+JPG, Sidecars              ← reine Logik
│  ├─ ziel.py                Zielpfad bauen, Ordner mit Zusatz finden
│  ├─ hashes.py              Prüfsummen, Byte-Vergleich
│  ├─ kopieren.py            Phase 3: übertragen
│  ├─ pruefen.py             Phase 4: nachrechnen
│  ├─ aufraeumen.py          Phase 5+6: löschen      ← gesperrt bis Frage 1 geklärt
│  └─ bericht.py             Text- und CSV-Bericht
└─ tests/
   ├─ testbaum.py            erzeugt den künstlichen Testbaum
   └─ test_*.py              ein Test je Modul
```

`meldungen.py` als eigene Datei hat einen praktischen Grund: alle deutschen Ausgaben stehen
an einer Stelle. Ändert sich eine Formulierung, muss man nicht den ganzen Code durchsuchen —
und beim Bauen der Weboberfläche in Phase 7 lassen sich dieselben Texte wiederverwenden.

`aufraeumen.py` wird zwar mitgeplant, aber erst gebaut, wenn Frage 1 in
[`offene_fragen.md`](offene_fragen.md) entschieden ist.

---

## 2. Datenbank

Eine SQLite-Datei, also eine einzelne Datei ohne Server im Hintergrund. Sie merkt sich jeden
Schritt, damit ein Lauf nach einem Absturz genau dort weitergeht, wo er war.

### Tabelle `dateien` — eine Zeile pro Quelldatei

| Spalte | Inhalt |
|---|---|
| `id` | laufende Nummer |
| `quellpfad` | voller Pfad, eindeutig |
| `groesse`, `mtime` | Größe und Änderungsdatum, zum Wiedererkennen |
| `typ` | `foto`, `raw`, `video`, `sidecar`, `sonstiges` |
| `gruppe_id` | verweist auf die Hauptdatei der Gruppe (RAW+JPG+Sidecar) |
| `hash` | Prüfsumme, wird beim Kopieren nebenbei berechnet |
| `kamera` | fertiger Ordnername, z. B. `A7C2` |
| `aufnahme_zeit` | ermitteltes Datum mit Uhrzeit |
| `datum_quelle` | woher es kam: `exif`, `video`, `dateiname`, `mtime` |
| `datum_sicher` | Ja/Nein — steuert `_Ohne_Datum/` |
| `zielpfad` | in Phase 2 berechnet, noch nicht angelegt |
| `status` | siehe unten |
| `fehler_grund` | Klartext, landet so im Bericht |
| `aktualisiert_am` | Zeitstempel des letzten Statuswechsels |

### Status

```
gefunden → analysiert → kopiert → geprueft → quelle_geloescht
                     ↘ duplikat → duplikat_bestaetigt → quelle_geloescht
                     ↘ uebersprungen
                     ↘ fehler
```

Der Status ist die einzige Wahrheit darüber, was mit einer Datei passieren darf.
Gelöscht werden darf **nur** aus `geprueft` und `duplikat_bestaetigt` — und
`duplikat_bestaetigt` setzt voraus, dass die Zieldatei frisch gelesen und verglichen wurde
(siehe Fragen 1 und 9).

`uebersprungen` ist kein Fehler, sondern der normale Fall für Dateitypen außerhalb der Liste
aus SPEC §3. Sie werden gezählt, aber nie angefasst.

### Tabelle `ziel_index` — was liegt schon im Ziel

`pfad`, `groesse`, `mtime`, `hash`, `gesehen_am`.

Spart beim zweiten Lauf das erneute Hashen des gesamten Archivs. **Darf nur Kopien
überspringen, nie eine Löschung rechtfertigen** — die Begründung steht in Frage 9.

### Tabelle `laeufe` — Verlauf

Pro Phase: Start, Ende, Anzahl Dateien, Bytes, Fehler. Daraus entsteht der Bericht, und
Geschwindigkeitsmessungen zwischen verschiedenen Einstellungen lassen sich vergleichen.

### Geschwindigkeit

- Statuswechsel gesammelt schreiben (alle 500 Dateien oder alle 2 Sekunden, je nachdem was
  zuerst kommt). Einzelne Schreibvorgänge würden den ganzen Lauf ausbremsen.
- Indizes auf `status`, `hash`, `gruppe_id`, `zielpfad` — das sind die vier Spalten, nach
  denen tatsächlich gesucht wird.
- WAL-Modus nur auf lokalen Platten, siehe Frage 8.

---

## 3. Abhängigkeiten

Jede zusätzliche Bibliothek ist etwas, das später im Docker-Container installiert sein muss
und kaputtgehen kann. Darum bewusst wenige:

| Paket | Wofür | Warum nicht anders |
|---|---|---|
| `xxhash` | schnelle Prüfsummen | Die Standardbibliothek kennt nur kryptografische Hashes (SHA), die hier um ein Vielfaches langsamer wären. Bei hunderten Gigabyte macht das Stunden aus. |
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

*Absicherung:* Vor jeder Löschung wird die Zieldatei frisch gelesen und gehasht. Der Index
darf nur Kopien überspringen. Keine Abschaltmöglichkeit. Siehe Frage 9.

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
kopiert — die Quelle darf gelöscht werden. Bei 128 Bit ist das praktisch ausgeschlossen, aber
es ist die letzte Absicherung vor dem Verlust.

*Absicherung:* Vor einer Löschung, bei der Quelle und Ziel beide noch existieren,
zusätzlich byteweise vergleichen. Kostet fast nichts, weil beide Dateien dafür ohnehin
gelesen werden. Siehe Frage 10.

*Test:* Byte-Vergleich künstlich scheitern lassen, Löschung muss verweigert werden.

### 4.7 Einzelne Dateien brechen den Lauf ab

Eine unlesbare Datei beendet den ganzen Vorgang nach zwei Stunden, alles bisher Erreichte
wäre unklar.

*Absicherung:* Fehler werden pro Datei aufgefangen, bekommen Status `fehler` mit Klartext-Grund
und landen im Bericht. Der Lauf geht weiter.

*Test:* Datei ohne Leserechte, zu langer Pfad, defekte EXIF-Daten — alle drei im Testbaum.

---

## 5. Was als Nächstes passiert

1. Die dringenden Fragen 1, 8, 9, 10 aus [`offene_fragen.md`](offene_fragen.md) entscheiden.
2. Dann Phase 1 laut [`PROMPTS.md`](PROMPTS.md): Grundgerüst, Testbaum, `fotosort scan`.
