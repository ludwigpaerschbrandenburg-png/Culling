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
Sidecar gehört. Für die Sidecar-Zuordnung gelten die drei Formen aus SPEC §3 — Stammname plus
Endung (`DSC01234.xmp`), vollständiger Dateiname plus Endung (`DSC01234.ARW.xmp`) und
Stammname plus konfigurierbares Zusatzmuster plus Endung (`C0001M01.XML` zu `C0001.MP4`). Die
ersten beiden gelten für alle Sidecar-Endungen; die dritte fängt die Sony-Video-Sidecars ab,
die sonst durchfallen würden. `gruppen.py` benutzt das Ergebnis, um Gruppen zu bilden; die
Einordnung selbst bleibt reine Logik und damit in Sekunden durchtestbar.

`aufraeumen.py` ist das einzige Modul, das löscht. Bei Quelldateien aus dem Bestand der
Datenbank fragt es vor jeder Datei den Status ab und arbeitet ausschließlich mit `geprueft`
und `duplikat_bestaetigt`; jeder andere Status führt dazu, dass die Datei stehen bleibt. Der
Status allein reicht nicht — dazu kommt die Frischlesung der Zieldatei im aktuellen Lauf
(SPEC §5). Davon getrennt und eng begrenzt sind die beiden Dateiarten, die nie in der
Datenbank stehen: die Reste-Dateien aus Phase 6 und liegengebliebene `.part`-Dateien. Gebaut
wird das Modul trotzdem erst in seiner eigenen Phase.

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
- **Linux:** der Dateisystemtyp des Einhängepunkts, zu dem der Pfad gehört. Als Netz gelten
  `cifs`, `smb3`, `nfs`, `nfs4` und `fuse.sshfs`.

Lässt sich der Typ nicht bestimmen, gilt der Pfad als Netzpfad. Die vorsichtige Antwort
kostet im schlimmsten Fall einen Kopiervorgang statt eines Umbenennens; die unvorsichtige
kostet im schlimmsten Fall Bilder.

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
| `bestaetigt_in_lauf` | Nummer des Laufs, in dem die Zieldatei frisch gelesen und ihr Hash verglichen wurde — gilt für `geprueft` und `duplikat_bestaetigt` gleichermaßen |
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

Die hier genannten Werte sind genau die, die in der Datenbank stehen — ohne Umlaute, eine
zweite Schreibweise gibt es nicht (SPEC §6).

Der Status ist die Voraussetzung dafür, dass mit einer Datei überhaupt etwas passieren darf.
Gelöscht werden darf **nur** aus `geprueft` und `duplikat_bestaetigt`; kein anderer Status
berechtigt dazu (SPEC §4 Phase 5). Der Status allein genügt aber nicht: Vor jeder Löschung
kommt die Frischlesung im aktuellen Lauf dazu (SPEC §5).

`duplikat_bestaetigt` bekommt eine Quelldatei nur dann, wenn die inhaltsgleiche Zieldatei
**im aktuellen Lauf** vollständig neu gelesen wurde und ihr Hash mit dem der Quelle
übereinstimmt (SPEC §5). Ein Hash aus einem früheren Lauf oder aus dem Ziel-Index genügt
nicht — das wäre genau der Fehler aus 4.1. Umgesetzt wird das über die Spalte
`bestaetigt_in_lauf`: Steht dort nicht die Nummer des laufenden Laufs, gilt die Datei wieder
als `duplikat` und wird vor dem Löschen erneut verglichen.

Dieselbe Spalte gilt für `geprueft`. Auch eine geprüfte Datei wird vor dem Löschen noch
einmal frisch gegen ihre Zieldatei verglichen; die Prüfung aus Phase 4 kann Wochen her sein
und sagt nichts darüber, wie die Zieldatei jetzt aussieht. Steht in `bestaetigt_in_lauf`
nicht die Nummer des laufenden Laufs, bleibt die Datei stehen und wird im Bericht aufgeführt.
`bestaetigt_in_lauf` ist damit keine Eigenschaft eines einzelnen Status, sondern die
Buchführung über die Frischlesung — für beide löschberechtigenden Status.

`verschoben` steht für Dateien, die auf demselben Laufwerk durch Umbenennen ins Ziel
gekommen sind (SPEC §4 Phase 3). Dass die Zieldatei existiert und die Größe stimmt, wird
direkt nach dem Umbenennen in Phase 3 geprüft; erst danach wird der Status gesetzt. Für sie
gibt es keine Quelle mehr, gegen die gehasht werden könnte: Die Prüf-Phase berechnet deshalb
nur noch den Hash aus der Zieldatei und trägt ihn in den Ziel-Index nach.
`quelle_geloescht` folgt darauf nicht — die Quelle ist mit dem Umbenennen verschwunden, es
gibt nichts mehr aufzuräumen.

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
| `blake3` | Prüfsummen | BLAKE3 ist beides zugleich: kryptografisch und schnell. Es ist deutlich schneller als SHA-256 aus der Standardbibliothek und meist schneller, als die Platte liefern kann — der Hash kostet also praktisch keine Extrazeit. Weil derselbe Hash hier über eine Löschung mitentscheidet, darf es keine reine Prüfsumme wie `xxh3` sein (SPEC §7). Die Hashlänge bleibt auf dem Standard der Bibliothek: 256 Bit. Sie wird nirgends gekürzt, und sie wird auch nicht verlängert — 256 Bit sind der Wert, auf den sich die Kollisionsrechnung in 4.6 bezieht. |
| `tzdata` | Zeitzonendatenbank | Videos ohne Zeitzonen-Offset werden von UTC in die Heimat-Zeitzone umgerechnet (SPEC §3). Python bringt dafür `zoneinfo` mit, holt sich die Zeitzonendaten aber aus dem Betriebssystem. Windows hat keine, dort scheitert `Europe/Berlin` ohne dieses Paket. Aufgenommen wird es trotzdem **unbedingt**, nicht als bedingte Abhängigkeit für Windows: Die Alternative wäre die Annahme, dass jedes Container-Image eine Zeitzonendatenbank mitbringt, und schlanke Images bringen sie oft nicht mit. Das Paket ist klein und schadet unter Linux nicht — dort wird es schlicht nicht gebraucht. |
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

*Was sie kostet:* Die Zieldatei wird vor jeder Löschung ohnehin frisch gelesen (SPEC §5), das
ist nicht der Aufwand. Die Quelldatei dagegen wird vor dem Löschen **nicht** zwingend noch
einmal gelesen — ihr Hash steht seit dem Kopieren in der Datenbank. Der Byte-Vergleich
bedeutet also ein zusätzliches vollständiges Lesen der Quelldatei plus den Vergleich selbst,
und zwar im Aufräum-Schritt. Das ist echter Zeitaufwand, kein Rundungsfehler; bei einem
Archiv von mehreren Terabyte ist es ein zweiter vollständiger Durchgang durch die Quelle.

*Warum „aus" trotzdem vertretbar ist:* Die Option schützt einzig gegen die Kollision eines
kryptografischen Hashes mit 256 Bit — gegen ein Risiko also, das um Größenordnungen kleiner
ist als die Fehlerrate der Hardware, auf der verglichen wird. Wäre hier eine reine Prüfsumme
im Einsatz, müsste der Standard „an" lauten. Weil BLAKE3 kryptografisch ist, kauft die Option
messbare Zeit gegen keinen messbaren Sicherheitsgewinn. Wer sie trotzdem will, schaltet sie
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
