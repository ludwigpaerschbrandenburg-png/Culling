# To-do

Offene Punkte, nach der Phase sortiert, in der sie behandelt werden. Die Phasen stehen in
[`PROMPTS.md`](PROMPTS.md), der verbindliche Stand in [`SPEC.md`](SPEC.md).

Die Punkte unter „Aus der Prüfung" stammen aus drei Prüfrunden über die Dokumentation. Sie sind
bewusst nicht vorab in die SPEC eingearbeitet worden: Sie verhindern Phase 1 nicht, und sie
lassen sich besser entscheiden, wenn der betroffene Code gebaut wird. Beim Bau der jeweiligen
Phase werden sie abgearbeitet — nicht als Kür, sondern als Teil der Phase.

---

## Phase 1 — Grundgerüst, Testbaum, Scan

Abgenommen (`847f014`). Nachträge aus der Abnahme sind in die SPEC eingearbeitet:
nur verändernde Befehle legen einen Lauf an (§6), Ereignisarten (§6), `--ziel-anlegen` (§8),
`fotosort.sperre` (§6), Beispiel `ausschlussmuster` (§9).

- [x] Grundgerüst, `config.toml`, Schema, Testbaum, `scan`/`status`/`config`, Archiv-ID,
      Sicherung, ExifTool-Prüfung, „Ziel in Quelle"
- [x] Mehrere Quellen je Archiv (SPEC §4 Phase 1, §6 `quellen`, §8) — Schema direkt geändert

### Aus der Prüfung

- [ ] **Erkennung des Dateisystemtyps unter Windows festklopfen.** Linux über `/proc/mounts`
      ist erprobt. Windows über `GetDriveType` (`DRIVE_REMOTE`) und das UNC-Präfix läuft seit der
      Windows-CI auf der lokalen NTFS-Platte des Läufers (`tests/test_pfade.py`, Windows-Tests);
      ein echtes Netzlaufwerk (SMB, Laufwerksbuchstabe auf eine Freigabe) gibt es dort nicht —
      das prüft der erste Lauf mit dem NAS. Betrifft SPEC §6 (Netzlaufwerk) und §4 Phase 3.

---

## Phase 2 — Analyse

Gebaut: `metadaten.py` (ExifTool-Pool mit `-stay_open`, Videos ohne `-fast2`, weil das
eingebettete Sony-XML sonst fehlt), `datum.py`, `kamera.py`, `gruppen.py`, `ziel.py`,
`analyse.py`, `fotosort analyse`. Testbaum um ein Video ohne jede Offset-Quelle, ein Sony-MP4
mit eingebettetem XML und `ziel_vorbelegen()` erweitert.

- [x] Metadaten über ExifTool im Stapelbetrieb (`-stay_open`)
- [x] Datumsermittlung mit allen sechs Quellen aus SPEC §3, Sony-Felder mit Offset bevorzugt
- [x] Kamera-Aliase, Gruppen, Zielpfad-Berechnung, Ordner mit Zusatz
- [x] Testbaum um den vorbelegten Zielnamen erweitert (`ziel_vorbelegen`)

### Aus der Abnahme von Phase 2 (nicht in Phase 2 gebaut)

- [x] **Entscheidung: „Duplikate erkennen" in SPEC §4 Phase 2.** Entschieden: Duplikate erkennt
      Phase 3 über den Hash. §4 Phase 2 ist umformuliert; die Analyse zeigt nur die Schätzung
      „mögliche Duplikate" (gleiche Größe und Aufnahmezeit), die nichts entscheidet.
- [x] **Zeitlimit beim Lesen eines ExifTool-Stapels.** Gebaut (Nacht-Auftrag Teil 4): 60 s plus
      1 s je Datei des Stapels; danach wird der Prozess beendet und neu gestartet, der Stapel Datei
      für Datei nachgelesen, nur die hängende Datei bekommt `fehler` (Zeitlimit). Test mit einem
      nachgebauten ExifTool (`tests/exiftool_haengt.py`), das an einer Datei hängen bleibt.
- [x] **Eigene Vorlage mit Kamera im Datumsordner (`{jahr}-{monat}-{tag} {kamera}`).** Der
      Zusatz-Abgleich gilt je Ebene mit Datumsfeld; in einer gemischten Ebene könnte
      `2026-01-01 Geburtstag` für `2026-01-01 A7C` gewählt werden. Mit der Standardvorlage
      unmöglich; in der `LIESMICH.md` §9 („Eigene Ordnervorlage") erklärt.

### Offen, mit echten Dateien zu prüfen

- [ ] **Echte Sony-Dateien (A7C, A7C II).** Das eingebettete XML (`CreationDateValue`) und der
      Sidecar `C0001M01.XML` sind mit nachgebauten Dateien geprüft; echte Aufnahmen prüft der
      Nutzer lokal. Wenn ExifTool dort andere Feldnamen liefert, ist `metadaten.FELDER_VIDEO`
      die eine Stelle zum Nachziehen.

---

## Phase 3 — Kopieren

Gebaut: `hashes.py` (BLAKE3 beim Kopieren mitgerechnet, exklusives Anlegen), `kopieren.py`,
`fotosort kopieren` mit `--dry-run`, `--profil`, `--kopier-worker`, `--hash-worker`;
`pfade.umbenennen_ohne_ueberschreiben`, `kann_ohne_ueberschreiben` (Probe), `freier_platz`.
Schema-Version 4 (`kopiert_in_lauf`, `schreibpfad`, Indizes auf Hash und Gruppe).
Ein Prüf-Agent hat den Stand gegen SPEC §4/§5/§6 gelesen; sein Verlustpfad-Befund (Anspruch im
Rückfall auf dem berechneten statt dem geschriebenen Namen) ist behoben und mit Tests belegt.

- [x] Kopieren über `.part`, nicht überschreibendes Umbenennen, BLAKE3 nebenbei
- [x] Duplikate (gleicher Name und über den Ziel-Index), Ziel-Index, Worker-Zahlen nach Profil
- [x] Absturzsicherheit: Anspruch vor dem Schreiben festgeschrieben, Reste beim nächsten Start
      (Pflichttest mit SIGKILL mitten im Kopieren und Neustart)
- [x] Rückfall ohne `.part` für exFAT/FAT32, in beiden Zweigen getestet
- [x] Zielpfad eines quellinternen Duplikats: zeigt auf die tatsächlich kopierte Partnerdatei,
      gesetzt erst, nachdem diese im Ziel steht und ihr Hash in diesem Lauf bekannt ist (SPEC §5)
- [x] Einmalige Probe je Ziel-Dateisystem mit einer Wegwerfdatei im Zielordner (SPEC §5)

### Aus dem Bau von Phase 3 (später)

- [x] **Gruppe wird bei Inhalts-Duplikat eines Mitglieds getrennt.** Der Bericht (Phase 4) weist
      jedes Duplikat mit Partnerdatei aus.
- [ ] **Gruppenmitglieder in späteren Status.** Wird eine Hauptdatei nach dem Kopieren
      neu analysiert (zweiter Scan, geänderte Quelle), ziehen nur Mitglieder mit Status
      `analysiert` mit; schon kopierte bleiben, wo sie sind. Ob das als eigenes Ereignis in den
      Bericht soll, ist eine Entscheidung des Nutzers (bisher: nur über den Status je Datei
      sichtbar). Nichts geht verloren.
- [x] **Gruppenanhang im Wettlauf mit einem Fremdprozess.** Legt ein anderes Programm
      genau zwischen Anhang-Bestimmung und Umbenennen eine Datei unter `X_1` an, bekommt nur
      das betroffene Mitglied `_2`, die übrigen behalten `_1`. Nichts geht verloren; seit der
      Prüfung von Phase 5 steht der Fall als Ereignis `anhang_abweichend` im Bericht.
- [x] **Windows-Zweig des nicht überschreibenden Umbenennens (`MoveFileExW`):** läuft seit der
      Windows-CI bei jedem Push auf `windows-latest` mit (`tests/test_pfade.py`,
      `tests/test_kopieren.py`, ohne Windows-Ausnahme), NTFS auf dem Läufer.
- [x] **Verschieben (`--verschieben`)** ist in Phase 5 gebaut (Umbenennen auf demselben
      Laufwerk, Löschbedingung aus SPEC §5).
- [ ] **Durchsatz auf echten Platten messen (Phase 6).** Die Zahlen aus `tests/tempo_kopieren.py`
      stammen aus dem Container mit Dateisystem-Cache und sagen nichts über HDD, SSD oder SMB.
      Die Profil-Werte (hdd 2, netzwerk 4, ssd 8) sind Startwerte, die auf dem Ryzen und gegen
      TrueNAS nachgemessen werden müssen.

---

## Phase 4 — Prüfen und Bericht

Gebaut: `pruefen.py` (Zieldateien vollständig neu lesen, `kopiert` → `geprueft`, `duplikat` →
`duplikat_bestaetigt`, `verschoben` → Hash nachgetragen, Hash-Worker des Profils, fortsetzbar,
Strg+C), `bericht.py` (Text und zwei CSV nach SPEC §10, nach jedem Lauf und auf Verlangen),
`fortschritt.py` (gemeinsame Anzeige), Schema 5 (`laeufe.zusammenfassung`). Nach fehlgeschlagener
Prüfung gibt `kopieren` die Zeile wieder frei und legt eine frische Kopie an; die fehlerhafte
Zieldatei bleibt liegen.

- [x] `fotosort pruefen`, `fotosort bericht`
- [x] Pflichttests: Zieldatei um ein Byte verändert, abgeschnitten, fehlt; Abbruch und Fortsetzen
- [x] Prüf-Agent: kein Verlustpfad; behoben: Lesung je Zielpfad prüft Größe je Zeile, CSV mit
      Roh-Pfaden, `verschoben` nur bis zum Hash, Uhrzeit-Kenntnis in `aufnahme_zeit` gespeichert
      (Tagesgrenze bei Neuberechnung), Zähler und Listen des Berichts ergänzt
- [x] Gruppe bei Inhalts-Duplikat eines Mitglieds getrennt: Der Bericht listet jedes Duplikat mit
      Partnerdatei und Status, so ist der Fall sichtbar (Punkt aus Phase 3)

### Entscheidungen für den Nutzer

- **CSV mit Semikolon und UTF-8-BOM.** Gewählt, damit Excel unter Windows die Datei per Doppelklick
  richtig öffnet. Wer die Datei in ein anderes Programm lädt, wählt dort „Semikolon" als Trenner.
- **`pruefen` bestätigt auch Duplikate** (`duplikat` → `duplikat_bestaetigt`), indem es die
  Partnerdatei im Ziel frisch liest. Das Aufräumen (Phase 5) liest vor jeder Löschung trotzdem
  Quelle und Ziel erneut; die Bestätigung aus Phase 4 ersetzt das nicht.
- **Überschriften des Berichts stehen in `bericht.py`,** nicht in `meldungen.py`: Der Bericht ist
  selbst ein Dokument, seine Gliederung gehört zu ihm. Alle Meldungen an der Konsole bleiben in
  `meldungen.py`.
- **Nach fehlgeschlagener Prüfung** wird die fehlerhafte Zieldatei nicht angerührt. Die frische
  Kopie bekommt bei belegtem Namen den Anhang `_1`; die alte, fehlerhafte Datei steht im Bericht
  unter „Prüfung fehlgeschlagen" und muss von Hand entfernt werden, wenn man sie nicht behalten
  will. Grund: Unter dem endgültigen Zielnamen löscht das Programm nie etwas (SPEC §5).

---

## Windows (GitHub Actions)

Die komplette Testsuite läuft bei jedem Push auf `ubuntu-latest` und `windows-latest`
(`.github/workflows/tests.yml`, Python 3.12, ExifTool über apt bzw. choco). Stand: beide grün.
Unter Windows werden nur Tests übersprungen, deren Dateinamen es dort nicht geben kann
(Zeilenumbruch, ungültige Bytes) oder die den Linux-Mechanismus `/proc/mounts` prüfen; dafür
gibt es eigene Windows-Tests (UNC-Pfad, `GetDriveType`, Laufwerkskennung, `%LOCALAPPDATA%`).
Behoben für Windows: Fehlernummer nach `MoveFileExW`, lange Pfade beim Anlegen des Testbaums,
Backslashes in TOML, ExifTool-Antwortschlüssel mit Schrägstrichen, Prozessende im Absturztest.

- [ ] **Unter echtem Windows 11 mit echten Laufwerken nachmessen** (Phase 6, `fotosort messen`):
      Die Actions-Läufer haben nur eine NTFS-Platte; exFAT-Karten, SMB-Freigaben und
      Laufwerksbuchstaben-Zuordnung sind dort nicht prüfbar.

---

## Phase 5 — Verschieben, Aufräumen, leere Ordner

Gebaut: `loeschen.py` (die einzige Löschstelle, prüft jede Bedingung aus SPEC §5 an der frisch
gelesenen Zeile; Löschweisen endgültig und Ordner `_geloescht_<Datum>`), `aufraeumen.py`
(`fotosort aufraeumen` mit Bestätigungswort je Quelle, `--quelle`, `--dry-run`, `--endgueltig`,
`--leere-ordner`), `kopieren --verschieben` (Umbenennen auf demselben Laufwerk, sonst Kopieren →
Frischlesung beider Seiten → Löschen über die Löschstelle).

- [x] `kopieren --verschieben`, `aufraeumen`, `aufraeumen --leere-ordner`
- [x] Pflichttests: ungeprüfte Datei nie gelöscht (auch nicht über die Löschstelle direkt), Quelle
      nach dem Kopieren verändert → nicht gelöscht, zurück auf `analysiert`, im Bericht; Zielkopie
      fehlt/verändert → nicht gelöscht; Duplikat mit fehlender/anderer Partnerdatei → nicht gelöscht;
      Ordner mit fremder `.txt` bleibt; nicht erreichbare Quelle → nichts, klare Meldung; Absturz
      mitten im Aufräumen (nachgestellt und als abgeschossener Prozess) → nichts doppelt, nichts
      Falsches; Umbenennen auf belegten Namen überschreibt nichts
- [x] **Zielordner aus allen Durchläufen über die Quelle ausnehmen.** Das Entfernen leerer Ordner
      fasst ein im Quellbaum liegendes Ziel nie an (und der Ordner `_geloescht_` bleibt).

### Entscheidungen für den Nutzer

- **Standard-Löschweise ist immer der Ordner `_geloescht_<Datum>`,** nicht nur beim ersten
  Aufräumen. Endgültig löscht nur `--endgueltig`. Grund: Die sichere Wahl darf nicht stillschweigend
  kippen, nur weil schon einmal aufgeräumt wurde; ein Schalter ist ausdrücklich.
- **`kopieren --verschieben` löscht endgültig** (nach Frischlesung beider Seiten). Ein Ordner
  `_geloescht_` innerhalb der Quelle würde die Quelle nicht freigeben, was der Sinn des Verschiebens
  ist. Wer den Papierkorb will, kopiert und räumt danach mit `aufraeumen` auf.
- **Bestätigungswörter:** `loeschen` (endgültig), `verschieben` (Ordner `_geloescht_`), `entfernen`
  (leere Ordner). Ohne Terminal gibt es keine Bestätigung und keine Löschung; ein Schalter, der die
  Frage überspringt, wurde bewusst nicht gebaut.
- **Nach „Quelle seit dem Kopieren geändert"** ist der Weg zur frischen Kopie `scan` → `analyse`
  → `kopieren` (die Datei hat eine andere Größe/Zeit als beim Scan; `kopieren` allein stellt sie auf
  `gefunden` zurück). `fotosort status` zeigt das als „Analyse offen".
- **Kein Test mit einer zweiten physischen Platte im Container:** „gleiches Laufwerk" wird in den
  Tests durch Nachstellen (immer nein bzw. tmp_path) geprüft; das echte Umbenennen zwischen zwei
  Laufwerksbuchstaben unter Windows prüft `fotosort messen` bzw. der erste Lauf mit Kopien.
- **Endgültiges Löschen liest die Quelle zweimal.** Nach dem Angriff „Quelle zwischen Frischlesung
  und Löschen ändern" (siehe unten) wird bei `--endgueltig` und `kopieren --verschieben` die Quelle
  unmittelbar vor dem `unlink` noch einmal vollständig gelesen. Das kostet beim Aufräumen von
  50.000 Dateien (4,2 GB) im Container rund die Hälfte mehr Lesezeit (gemessen in Phase 6, siehe
  dort). Beim Standard (Ordner `_geloescht_`) nicht nötig, weil der aktuelle Inhalt mitwandert.
- **Ein Rest muss auch nach seiner Endung „sonstiges" sein.** Ein Eintrag wie `beute.jpg` in
  `reste_dateien` löscht nie ein Foto, auch keines ohne Zeile in der Datenbank. Die Standardliste
  ist davon nicht betroffen.
- **Schema-Version 6** (neue Spalte `umbenannt`). Es gibt noch keine echten Daten, daher keine
  Migration; eine ältere Datenbank wird wie bisher abgelehnt.

### Aus der Prüfung von Phase 5 (zwei unabhängige Prüfer, einer als Angreifer)

Alle Funde sind behoben, jeder mit einem Test in `tests/test_pruefbefunde.py`:

- [x] **VERLUST MÖGLICH — Quelle und Ziel dieselbe Datei über zwei Pfade** (Bind-Mount, zweite
      Freigabe, Hardlink): Der zweite Zyklus hätte die Archivdateien selbst gelöscht. Jetzt: Vergleich
      von Geräte-/Inode-Nummer und aufgelöstem Pfad vor jeder Löschung; Scan und Lage-Prüfung erkennen
      das Ziel auch über den zweiten Pfad.
- [x] **VERLUST (Angreifer) — Quelle zwischen Frischlesung und `unlink` verändert** (gleiche Größe,
      Änderungszeit zurückgestellt): wurde bei `--endgueltig` und `--verschieben` gelöscht. Jetzt:
      Kennung der Quelle (Gerät, Inode, Größe, mtime, ctime) vor der Lesung festgehalten und direkt vor
      dem Entfernen verglichen; beim endgültigen Löschen zusätzlich vollständige zweite Lesung.
- [x] **Reste-Datei mit Fotoinhalt ohne Datenbankzeile** (`beute.jpg` in `reste_dateien`) wurde
      entfernt. Jetzt: Rest nur, wenn die Endung `sonstiges` ist.
- [x] Ordner `_geloescht_` wurde vom nächsten Scan erfasst und beim nächsten Aufräumen ein zweites
      Mal entfernt. Jetzt: Scan überspringt ihn in jeder Tiefe, Aufräumen wählt ihn nie aus.
- [x] Betriebssystemfehler beim Entfernen (Schreibschutz) brach den Lauf ab. Jetzt: nur die eine Datei
      `fehler`, Lauf läuft weiter, Bericht wird geschrieben.
- [x] Absturz nach dem Umbenennen, vor dem Festschreiben von `verschoben`, endete in „Quelldatei
      nicht mehr vorhanden". Jetzt: Spalte `umbenannt`, Status wird nachgetragen.
- [x] Frischlesung trug keine Laufnummer; `bestaetigt_in_lauf` wurde bei Neukopie nicht geleert.
- [x] Papierkorb-Rückfall (exFAT) prüfte die geschriebene Kopie nicht durch Zurücklesen.
- [x] Windows-Junctions in `--leere-ordner` wurden wie Ordner betreten (jetzt `_ist_verknuepfung`).
- [x] Abbruch im exFAT-Rückfall ließ leere Dateien unter Archivnamen liegen.
- [x] Namensanhang konnte sich in einer Gruppe aufspalten (Fremdprozess dazwischen): jetzt Ereignis
      `anhang_abweichend` im Bericht.
- [x] Fehlermeldung nannte bei kaputter Zielkopie die Quelle („Quelle 160, Ziel 159"); jetzt „Zieldatei
      hat die falsche Groesse … die Quelle ist in Ordnung".
- [x] Schwache Zusicherung in `test_standard_verschiebt_in_geloescht_ordner` ersetzt.

---

## Phase 6 — Geführter Modus und Tempo

Gebaut: `fotosort start` (geführter Ablauf mit Fragen, Zusammenfassung und OK zwischen den
Phasen, Alias-Eingabe nach der Analyse, weitermachen bei Wiederaufruf), `fotosort messen`
(Lese-/Schreibtempo, Vorschlag für `[leistung]`), `tests/tempo_phasen.py` (50.000 Dateien,
jede Phase gemessen, wahlweise mit Profiler), drei Bremsen behoben, `LIESMICH.md`,
`einrichten.bat`, `fotosort.bat`, `start.bat`.

- [x] `fotosort start`, großer Testbaum, Profiler, `LIESMICH.md`
- [x] **Drei Bremsen** (Profiler am 50.000-Dateien-Baum, Zahlen siehe unten):
      1. Scan: `Path.resolve()` wurde je Datei dreimal gerufen (150.000 Aufrufe, drei Viertel
         der Scan-Zeit). Jetzt wird der aufgelöste Pfad je Ordner mitgeführt; nur
         Verknüpfungen werden noch aufgelöst.
      2. Analyse: Die Gruppenbildung verglich jede Sidecar mit jeder Hauptdatei des Ordners
         und baute dabei je Vergleich die Endungslisten aus der Konfiguration neu (5,8 Mio.
         Aufrufe). Jetzt Nachschlagetabellen (Endung → Typ je Konfiguration; Sidecar-Kandidaten
         über Name, Stammname und Präfix), entschieden wird weiter von `sidecar_gehoert_zu`.
      3. Kopieren: je Gruppe zwei Datenbank-Commits und fünf `stat`-Aufrufe je Datei im
         Hauptstrang. Jetzt ein Commit je Runde für alle Ansprüche und ein Commit je Runde für
         alle Endnamen (die Regel „Anspruch vor dem ersten Schreiben, Name vor dem Umbenennen
         festgeschrieben" gilt unverändert), der `stat` vom Einreichen wird wiederverwendet,
         der Ziel-Index bekommt Größe und Zeit aus der eben geschriebenen Kopie.
- [x] **Tempo-Punkt „doppelte Lesezeit im Verschieben-Modus"** gemessen (unten). Ergebnis:
      Der Kopierweg des Verschiebens liest die Quelle nach dem Kopieren zweimal (Frischlesung
      und zweite Lesung unmittelbar vor dem Löschen, siehe Phase 5). Es bleibt bei der
      Sicherheit; die Zahlen stehen hier, damit der Nutzer entscheiden kann, ob ihm Verschieben
      oder Kopieren + Prüfen + Aufräumen lieber ist.

### Messwerte (Container, 4 Kerne, Dateisystem-Cache; 50.048 Dateien, 4,2 GB, JPEG/RAW/MP4/XMP gemischt)

Die Zahlen gelten für diesen Container, nicht für eine echte Platte oder ein Netzlaufwerk; dort
misst `fotosort messen`. Vorher = Stand nach Phase 5, nachher = Stand Phase 6.

| Phase | vorher | nachher |
|---|---|---|
| scan | 43,4 s (1.153 Dateien/s) | 8,0 s (6.273 Dateien/s) |
| analyse | 47,6 s (1.051 Dateien/s) | 39,4 s (1.271 Dateien/s) — der Rest ist ExifTool selbst (4 Prozesse) |
| kopieren (ssd, 8 Worker) | 82,5 s (607 Dateien/s, 51 MB/s) | 61,0 s (820 Dateien/s, 69 MB/s; sauber nachgemessen) |
| pruefen | 26,7 s (1.874 Dateien/s, 157 MB/s) | 25,3 s (1.979 Dateien/s, 166 MB/s) — unverändert, war nie eine Bremse |
| aufraeumen --endgueltig | 48,5 s (1.032 Dateien/s) | 104,7 s (478 Dateien/s) — langsamer, siehe unten |
| kopieren --verschieben (Kopierweg, wie anderes Laufwerk) | — | 160,1 s (313 Dateien/s, 26 MB/s); zum Vergleich kopieren + pruefen + aufraeumen --endgueltig nachher zusammen 192,5 s |

**Warum Aufräumen und Verschieben langsamer wurden — und die Antwort auf „doppelte
Lesezeit":** Seit der Prüfung von Phase 5 wird beim **endgültigen** Löschen (`--endgueltig` und
`kopieren --verschieben` über den Kopierweg) die Quelle unmittelbar vor dem `unlink` ein zweites
Mal vollständig gelesen — im Hauptstrang, nacheinander, damit zwischen Lesung und Löschung kein
Fenster bleibt. Im Verschieben-Modus wird die Quelle damit dreimal gelesen (Kopieren, Frischlesung
im Worker, zweite Lesung vor dem Löschen) und die Kopie einmal; das kostet hier 160 s statt 62 s
für reines Kopieren. Der Standard des Aufräumens (Ordner `_geloescht_`) ist davon **nicht**
betroffen: Dort wandert der aktuelle Inhalt mit, es genügt der Vergleich der Datei-Kennung, und
das Tempo bleibt beim alten. Die Sicherheit steht nicht zur Disposition (CLAUDE.md, oberste
Regel); eine spätere Beschleunigung wäre, die zweite Lesung samt `unlink` in den Worker zu legen
(dann parallel), was die Löschstelle umbaut und deshalb nicht mehr in diese Phase gehört.

### Entscheidungen für den Nutzer

- **`fotosort start` fragt nach dem Ziel, statt ohne `--ziel` abzubrechen** (einzige Ausnahme
  von SPEC §8). Nur so lässt sich `start.bat` per Doppelklick starten.
- **Aliase aus dem geführten Modus werden in die config.toml geschrieben.** Das ist die einzige
  Stelle, an der das Programm die Konfigurationsdatei anfasst; Kommentare bleiben, es wird nur
  ein als TOML gültiges Ergebnis geschrieben, und nur nach ausdrücklicher Eingabe.
- **Nach neuen Aliasen werden nur noch nicht kopierte Dateien neu analysiert** (Status
  `analysiert` samt Gruppe zurück auf `gefunden`). Schon kopierte bleiben, wo sie sind.
- **`fotosort messen` schreibt mit `fsync`** (jede Messdatei wird wirklich auf die Platte
  gebracht), damit der Zwischenspeicher das Schreibtempo nicht schönt; das Lesen nutzt je Stufe
  andere Dateien. Beim ersten Durchlauf kann der Cache trotzdem mitspielen — zweimal messen.
- **Nicht gebaut (bewusst, nicht in der Aufgabenliste von Phase 6):** das Zeitlimit für einen
  hängenden ExifTool-Stapel (siehe Phase 2, „Aus der Abnahme") und die Erkennung zweier
  Laufwerksbuchstaben auf derselben Platte (unten, ungemessen). Beides bleibt offen.

### Aus der Prüfung von Phase 6 (ein unabhängiger Prüfer)

Kein Fund der Stufe „Verlust möglich". Alle Funde sind behoben (Tests in `tests/test_start.py`,
`tests/test_messen.py`, `tests/test_pruefbefunde6.py`):

- [x] `start`: „nein" zum Aufräumen und „ja" zu leeren Ordnern fragte trotzdem das Löschwort für
      Dateien ab — jetzt werden die Dateien ohne Frage übersprungen.
- [x] Kopieren: Ein Duplikat derselben Runde zeigte auf den *geplanten* Namen seines Partners;
      belegte ein Fremdprozess den Namen (Anhang `_1`), zeigte die Duplikat-Zeile auf die fremde
      Datei. Jetzt werden solche Zeilen auf den tatsächlichen Endnamen umgeschrieben bzw. bei
      Fehlschlag neu zum Kopieren freigegeben.
- [x] Ziel-Index bekam die Quellzeit statt der Zeit der geschriebenen Datei (scheitert `utime`,
      rundet FAT/SMB). Jetzt liefert der Worker die tatsächliche Zeit.
- [x] Rückfall ohne `.part` (exFAT): bis zu einer Runde exklusiv angelegter Dateien vor dem
      Anspruchs-Commit. Jetzt wie vorher je Gruppe festgeschrieben.
- [x] `analyse_zuruecksetzen_nach_modell` verglich mit SQLite-`LOWER` (nur ASCII): Modell mit
      Umlaut fiel durch. Jetzt Vergleich in Python.
- [x] `aliase_ergaenzen` verlor den Kommentar am Zeilenende einer ersetzten Zeile.
- [x] `--quelle` per Schalter wurde in `start` nicht geprüft; Alias-Frage kam auch ohne
      Modell-Liste; Verschieben im geführten Modus ging mit Enter — jetzt Wort `verschieben`
      vor Schritt 3 und genauer Vergleich der Modus-Antwort; ExifTool wird je Programmlauf nur
      einmal gestartet.
- [x] `messen`: Platzprüfung deckte bei kleinem `--mb` nicht die wirklich geschriebene Menge;
      Pfad wurde vor dem exklusiven Anlegen gemerkt; Strg+C wirkte erst nach der Stufe; die
      Abbruch-Meldung sagt jetzt, wenn ein Messordner liegen blieb; Profilvorschlag `netzwerk`
      nur noch bei erkanntem Netzpfad.
- [x] `einrichten.bat`: Klammerblöcke mit Variablen (ein `)` im Pfad hätte sie gesprengt) durch
      `goto`-Ablauf ersetzt. `LIESMICH.md`: vier Abweichungen vom Code korrigiert.

### Aus der Prüfung

- [ ] **Zwei Laufwerksbuchstaben auf derselben physischen Platte.** Die Laufwerkskennung für
      den parallelen Scan (SPEC §4 Phase 1) nimmt unter Windows den Laufwerksbuchstaben. Zwei
      Partitionen derselben Platte gelten damit als zwei Laufwerke und werden parallel gelesen,
      was auf einer Festplatte langsamer ist als nacheinander. Erkennen ließe sich das über die
      Volume-zu-Disk-Zuordnung (`IOCTL_STORAGE_GET_DEVICE_NUMBER`). Erst messen, ob es
      überhaupt ins Gewicht fällt.

- [x] **Doppelte Lesezeit im Verschieben-Modus messen.** Gemessen (siehe „Messwerte" oben,
      `tests/tempo_phasen.py --szenario verschieben`): 160 s statt 62 s für reines Kopieren bei
      4,2 GB im Container — Verschieben liest die Quelle dreimal (Kopieren, Frischlesung, zweite
      Lesung vor dem Löschen). Bewertung: Die Sicherheit bleibt; eine spätere Beschleunigung
      (zweite Lesung samt `unlink` im Worker) wäre ein Umbau der Löschstelle und braucht eine
      eigene Entscheidung. Auf einer echten Platte misst `fotosort messen` bzw. der Testlauf.

---

## Windows-Paket (eigenständiges Programm)

Gebaut: `paket/bauen.py` mit `paket/fotosort.spec` (PyInstaller, Ordner-Variante, kein Einzel-exe
wegen Startzeit und Virenscanner; seit Phase 7 zwei Programme auf einem gemeinsamen `_internal`:
`fotosort.exe` mit Konsole und `fotosort-fenster.exe` ohne), `paket/exiftool_holen.py` (ExifTool
64 Bit mit dem Ordner `exiftool_files`, den die Windows-Fassung neben der exe braucht),
`paket/pruefen.py` (das gepackte Programm läuft in der CI wirklich durch `--version`, scan,
analyse, kopieren, pruefen, den Fenster-Selbsttest beider Programme und einen Schritt als
Arbeitsprozess), Workflow `paket.yml` (Artefakt `fotosort-windows` je Push, Release mit
`fotosort-windows.zip` bei Tag `v*` oder `release_tag`).
`fotosort --version` nennt Programm- und ExifTool-Version; das mitgelieferte ExifTool wird vor
`PATH` gefunden (SPEC §2). `fotosort.bat` erkennt selbst, ob es im Paket oder im Quellcode liegt.

- [x] Paket, Artefakt, Release v0.1, Prüfung in der CI
- [x] **Release anlegen ohne Tag-Push:** Aus der Entwicklungsumgebung lassen sich keine Tags
      pushen (Verbindung bricht ab). Deshalb kann der Workflow auch von Hand gestartet werden
      („Run workflow" mit `release_tag`, z. B. `v0.2`); er legt Tag und Release dann selbst auf
      dem aktuellen Stand an. Ein gepushter Tag `v*` funktioniert weiterhin genauso.
- [ ] **Signatur:** Das Programm ist nicht signiert; SmartScreen warnt beim ersten Start (LIESMICH
      §1 sagt, was zu klicken ist). Eine Signatur bräuchte ein Zertifikat.
- [ ] **ExifTool-Version:** Der Bau nimmt die jeweils aktuelle Version von exiftool.org; die
      benutzte steht in `exiftool\VERSION.txt` im Paket. Zum Festnageln `--version` in
      `paket/exiftool_holen.py` bzw. im Workflow angeben.

---

## Phase 7 — Oberfläche mit Fenster

Gebaut: `fotosort fenster` (SPEC §8). Paket `src/fotosort/oberflaeche/` mit `ablauf.py` (Zustand,
Arbeitsprozess, Zusammenfassungen und Listen aus der Datenbank), `server.py` (FastAPI, nur
127.0.0.1, Origin-Prüfung), `fenster.py` (Server im eigenen Strang, pywebview-Fenster,
Ordnerdialog, Selbsttest) und `static/` (eine Seite ohne Rahmenwerk). `steuerung.py` im Kern:
Statusdatei (≤ 2×/s, Herzschlag 2 s) und Steuerdatei (Pause/Weiter/Abbruch) je Schritt;
`fotosort arbeit --auftrag` führt einen Schritt als eigenen, losgelösten Prozess aus. Windows-Paket
mit `fotosort-fenster.exe` (ohne Konsole) neben `fotosort.exe`; `start.bat` öffnet das Fenster;
die CI startet das Fenster im Selbsttest und lässt einen Schritt als Arbeitsprozess laufen.
Version 0.2.0, Release v0.2.

- [x] Startseite (Ziel, Quellen, Kopieren/Verschieben, Profil, „Los geht's“, „Weitermachen“)
- [x] Eine Seite je Schritt: Balken, Dateien/MB erledigt/gesamt, MB/s, Restzeit, Pause/Fortsetzen/Abbrechen
- [x] Zusammenfassung je Schritt mit „Weiter“, Alias-Tabelle nach der Analyse, Aufräumen-Seite mit Wort
- [x] Listen Fehler/Duplikate/ohne Datum seitenweise (100 je Seite), Bericht und config.toml per Knopf
- [x] Fenster schließen bricht den Lauf nicht ab; laufender Schritt wird beim Öffnen übernommen
- [x] **Desktop-Programm mit Qt** (v0.4): Nach dem Test von v0.3 (Absturz beim ersten Start, weil
      der Protokollordner fehlte; kein Fenster, weil pythonnet/WebView2 nicht luden) ist die
      Windows-Oberfläche ein richtiges Programm: `oberflaeche/desktop.py` (PySide6), `stil.py`
      (Nocturne als Qt-Stylesheet, Inter als TrueType), `meldungsfenster.py` (Startfehler als
      Windows-Meldung mit Rat und Protokollpfad). pywebview und pythonnet sind entfernt; die
      Browser-Fassung bleibt als `fenster --ohne-fenster` für Phase 8. Paket: `fotosort.exe` (Fenster,
      ohne Konsole, Symbol) und `fotosort-konsole.exe` (Befehle, Arbeitsprozesse). `start.bat` und
      `fotosort.bat` ohne Klammerblöcke (Pfade mit Leerzeichen und Klammern). CI-Prüfung wie auf
      einem frischen PC: Paket in „fotosort-windows (1)\fotosort", leeres `%LOCALAPPDATA%`, Start
      nur über `start.bat`, Fenster in 20 s, Durchlauf über die Oberfläche (offscreen), Befehle.
- [x] **Design übernommen** (v0.3): Übergabe in `docs/design/` (Nocturne-Tokens, Hauptansicht). Eine
      Ansicht mit Titelzeile, Phasenleiste, Fortschrittstafel, Karten und Statusleiste; Startseite,
      Kamera-Tabelle (`.table` mit tippbarem Alias), Aufräumen-Karte und geblätterte Listen im
      selben Stil. Inter als woff2 im Paket (`fonts.css`), nichts aus dem Internet. Bildschirmfotos
      jeder Ansicht (Playwright) unter `docs/oberflaeche/`.
- [ ] **Ordner-Browser für den Server (Phase 8):** Im Browser (`--ohne-fenster`) wird der Pfad
      eingetippt; der einfache Ordner-Browser aus SPEC §8 kommt mit dem Container.

### Aus dem ersten echten Testlauf (v0.3, 36.000 Dateien auf einer Festplatte)

- [x] **Schwarze Fenster:** Je ExifTool-Prozess ging ein Konsolenfenster auf (über 30), der
      Virenscanner schlug an. Ursache: Ein Konsolenprogramm, das aus einem Programm ohne Konsole
      (Fenster, losgelöster Arbeitsprozess) gestartet wird, bekommt von Windows eine neue Konsole.
      Behoben: `prozesse.py` gibt ExifTool-Pool, ExifTool-Prüfung und `--version`
      `CREATE_NO_WINDOW` + `SW_HIDE`, dem Arbeitsprozess `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
      + `SW_HIDE`. Die Paketprüfung beobachtet während des Durchlaufs alle Fenster (`EnumWindows`,
      alle 50 ms, Konsolenfenster auch unsichtbar) und scheitert bei jedem neuen Konsolenfenster;
      zwei Gegenproben (`CREATE_NEW_CONSOLE`, `CREATE_NO_WINDOW`) zeigen vorher, was die Umgebung
      beobachtbar macht. **Vorbehalt:** Auf dem GitHub-Läufer ohne Bildschirm war beim ersten Lauf
      kein Konsolenfenster sichtbar (die Wache meldet das ehrlich und findet dann nichts); die
      Flaggen selbst prüft `tests/test_prozesse.py` unter Windows. Der Beweis „keine schwarzen
      Fenster" kommt vom nächsten Test auf dem echten PC.
- [x] **32 Prozesse auf einer Festplatte, 8 Dateien/s:** Die Prozesszahl war „Anzahl Kerne“.
      Jetzt nach Profil: `hdd` 4, `netzwerk` 4, `ssd` Kerne bis 16; `metadaten_prozesse` und
      `analyse --prozesse N` bleiben als feste Vorgabe, `analyse --profil` gibt das Profil an
      (Fenster und geführter Modus reichen ihr Profil durch). Die Prozesse starten mit 200 ms
      Abstand. Messung im Container (4 Kerne, Dateien im Cache, 8.000 Dateien): 4 Prozesse
      ≈ 1.500 Dateien/s, 16 ≈ 1.350, 32 ≈ 1.000 — mehr Prozesse als Kerne sind selbst ohne
      Platte langsamer. Eine echte Festplatte lässt sich im Container nicht messen; 4 ist die
      begründete Wahl (ein Lesekopf, wenige Positionen).
- [x] **Reihenfolge und Stapel geprüft:** Die Analyse holt die Dateien nach Quellpfad sortiert
      (seitenweise 5.000), sammelt sie je Ordner und bildet Stapel gleichen Typs zu 200 Dateien in
      Ordnerreihenfolge. Ein Stapel wird von einem ExifTool-Prozess nacheinander gelesen — mit
      4 Prozessen liest die Platte an höchstens 4 Stellen. Die Stapelgröße bleibt 200.
- [x] **Rückfragen auf der Startseite:** Laufwerksstamm, Benutzerordner oder Ordner aller
      Benutzer als Quelle → Frage mit Erklärung, „Trotzdem nehmen“. Zielordner nicht leer und
      ohne Archiv-Kennung → Frage vor dem Scan. Fenster und Browser-Fassung.
- [x] **„Archiv verwerfen…“** auf der Startseite (Karte des angefangenen Archivs): entfernt den
      lokalen Archiv-Ordner und `.fotosortierer` im Ziel, nie kopierte Dateien, nie eine Quelle;
      Wort `verwerfen`; nicht bei laufendem Schritt oder belegtem Archiv (Archivsperre direkt, ohne
      die Datenbank zu öffnen — geht auch bei kaputter Datenbank); nie über eine Verknüpfung;
      Sicherheitsnetz gegen Foto-, RAW-, Video- und Sidecar-Dateien in den Programmordnern, alle
      Prüfungen vor der ersten Löschung. Danach Startseite leer.
- [x] **Prüf-Agent zu Teil 2** (ein unabhängiger Prüfer): kein Verlustpfad. Behoben: Verwerfen
      öffnete die Datenbank zum Sperren und scheiterte damit bei kaputter/veralteter Datenbank
      (unbehandelter `sqlite3`-Fehler); Verknüpfung als `.fotosortierer` wurde erst nach dem Löschen
      des lokalen Ordners erkannt (Sackgasse); Sidecars fehlten im Sicherheitsnetz; `--prozesse -2`
      wurde angenommen; der Durchlauf (`--durchlauf`) hätte an den neuen Rückfragen gehangen;
      „Ziel nicht leer" wurde vor der Quellen-/ExifTool-Prüfung gefragt (doppelte Frage); Fensterwache
      alle 200 ms hätte ein kurzes `exiftool -ver` verpassen können; vier Doku-Abweichungen. Jeder
      Punkt mit Test.
- [x] **Datenmenge je Quelle** im Scan-Ergebnis (Fenster, `status`, Befehl `scan`) zählt nur
      erfasste Dateien (Foto, RAW, Video, Sidecar), nicht die „sonstigen“.
- [x] **Unterbrechungen in jeder Kombination geprüft** (`tests/test_unterbrechungen.py`, dazu ein
      Test im Fenster): Abbrechen mitten im Kopieren → Fenster zu → neu auf → Weitermachen; harter
      Abschuss des Arbeitsprozesses (SIGKILL/TerminateProcess) dreimal an verschiedenen Stellen;
      „Sofort beenden“; Pause → Fenster zu → neues Fenster übernimmt den pausierten Lauf →
      Fortsetzen; Fenster zu während des Scans, Abbruch in der Analyse; zweites Fenster kann
      nichts doppelt starten. Maßstab ist ein ungestörter Referenzlauf über dieselbe Quelle
      (2.000 eindeutige Dateien): Zielbaum Datei für Datei gleich, keine `.part`-Reste, kein
      Zielpfad doppelt, kein offener Anspruch, Zähler je Status identisch, Anzeige nennt den Stand
      (abgebrochen / unerwartet beendet mit Protokoll / Weitermachen beim richtigen Schritt).
      Kein Fehler gefunden. Bekannte Eigenheit: Pause und Abbruch greifen bei der nächsten
      Fortschrittsmeldung, frühestens 0,5 s nach der vorigen — ein Schritt, der schneller fertig
      ist, läuft einfach zu Ende.

### Entscheidungen für den Nutzer

- [ ] **4 ExifTool-Prozesse für Festplatte und Netzlaufwerk** sind eine begründete Schätzung, keine
      Messung an echter Hardware. Wenn der nächste Testlauf auf der Festplatte immer noch langsam
      ist: `analyse --prozesse 2` oder `--prozesse 1` ausprobieren und die Dateien/s vergleichen.
- [ ] **Welche Ordner eine Rückfrage auslösen:** nur Laufwerksstamm, der eigene Benutzerordner und
      der Ordner aller Benutzer (`C:\Users`). „Dokumente“, „Downloads“ oder „Desktop“ fragen nicht.
      Reicht das?
- [ ] **„Ziel nicht leer“ fragt bei jedem Eintrag,** auch wenn nur eine `Thumbs.db` darin liegt —
      lieber einmal zu oft fragen. Ist das Archiv einmal angelegt, kommt die Frage nicht mehr.
- [ ] **„Archiv verwerfen“ behält die Protokolle der Oberfläche** (`oberflaeche/arbeit.log`,
      `fenster.log`) und lässt die kopierten Dateien im Ziel liegen. Wer das Ziel komplett leeren
      will, löscht die Ordner selbst — das Programm löscht nie Bilder aus dem Ziel.

- [ ] **Paketgröße:** Mit Qt ist das Paket etwa doppelt so groß wie vorher (Qt-Bibliotheken).
      Reicht das, oder soll das Paket noch verkleinert werden (Module ausschließen, UPX)?
- [ ] **Zwei Programme im Paket:** `fotosort.exe` (Fenster) und `fotosort-konsole.exe` (Befehle mit
      Ausgabe, wird von `fotosort.bat` und vom Fenster für die Arbeitsprozesse genutzt). Ein
      einzelnes Programm ginge, dann aber entweder ohne Konsolenausgabe oder mit schwarzem Fenster
      hinter der Oberfläche. So lassen?
- [ ] **„Weitermachen“ scannt nicht neu.** Der Knopf springt zum offenen Schritt. Wer inzwischen
      Dateien in die Quelle gelegt hat, drückt „Los geht's“ — das durchsucht immer zuerst.
- [ ] **Pause greift bei der nächsten Fortschrittsmeldung,** also nach der laufenden Datei (bei der
      Analyse nach dem laufenden Stapel, beim Scan nach 50 Dateien). Eine große Videodatei wird
      erst zu Ende kopiert. Reicht das, oder soll Pause mitten in einer Datei anhalten?
- [ ] **„Sofort beenden“** erscheint 20 s nach einem Abbruch, auf den der Schritt nicht reagiert.
      Es beendet den Prozess hart; die Datenbank übersteht das (WAL), angefangene `.part`-Dateien
      räumt der nächste Lauf auf. Ist der Knopf erwünscht, oder lieber nur der sanfte Abbruch?
- [ ] **Probelauf-Knopf:** Der Entwurf zeigt „Probelauf“ neben dem Hauptknopf. Im Fenster steht die
      Zahl der anstehenden Dateien und die Datenmenge schon im Hauptknopf („Kopieren starten · N
      Dateien“); ein eigener Probelauf (`kopieren --dry-run`) ist deshalb nicht eingebaut. Gewünscht?
- [ ] **Zusammenfassung ohne Fließtext:** Nach dem Entwurf („nur Beschriftungen, Zahlen, Pfade“) sind
      die Zeilen der Zusammenfassung jetzt knappe Bezeichnungen (`ohne sicheres Datum`,
      `Namenskonflikte`, `quelle_geloescht (gesamt)`). Die erklärenden Sätze aus Phase 7 (erster
      Stand) stehen nur noch in der LIESMICH. Reicht das für die Bedienung ohne Fachkenntnis?
- [ ] **styles.css und Internet:** Die Übergabe lädt Inter über eine `@import`-Zeile von Google. Im
      Programm ist genau diese Zeile entfernt (sonst würde jeder Start mit Internet die Schrift von
      Google holen); alles andere ist unverändert. `docs/design/styles.css` bleibt das Original.
- [ ] **Ein Fenster, ein Archiv zugleich.** Die Oberfläche merkt sich ein Ziel und lässt einen
      Schritt zugleich laufen. Zwei Fenster für zwei Archive gleichzeitig sind nicht vorgesehen
      (das zweite sähe den Lauf des ersten). Reicht das?

---

## Phase 8 — Server

- [ ] Dockerfile, Volumes, TrueNAS-Anleitung

### Aus der Prüfung

- [ ] **Zeitzonendatenbank im Container sicherstellen.** `tzdata` ist als Abhängigkeit
      aufgenommen (`architektur.md` §3), aber im Image sollte geprüft werden, dass die
      Heimat-Zeitzone aus SPEC §3 tatsächlich auflösbar ist. Ein Container ohne
      Zeitzonendatenbank würde jede Video-Umrechnung scheitern lassen.

---

## Ohne feste Phase

- [ ] Nichts offen.
