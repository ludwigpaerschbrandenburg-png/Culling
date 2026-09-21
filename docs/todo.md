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
      ist erprobt. Windows über `GetDriveType` (`DRIVE_REMOTE`) und das UNC-Präfix ist hier
      nicht prüfbar und muss beim ersten Lauf unter Windows nachgezogen werden. Betrifft
      SPEC §6 (Netzlaufwerk) und §4 Phase 3 (gleiches Laufwerk).

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
- [ ] **Zeitlimit beim Lesen eines ExifTool-Stapels (Phase 6).** Bleibt ExifTool an einer
      Datei hängen, steht der Lauf. Ein Zeitlimit je Stapel mit Neustart des Prozesses
      gehört in die Robustheits-Runde.
- [ ] **Eigene Vorlage mit Kamera im Datumsordner (`{jahr}-{monat}-{tag} {kamera}`).** Der
      Zusatz-Abgleich gilt je Ebene mit Datumsfeld; in einer gemischten Ebene könnte
      `2026-01-01 Geburtstag` für `2026-01-01 A7C` gewählt werden. Mit der Standardvorlage
      unmöglich; für eigene Vorlagen in der `LIESMICH.md` (Phase 6) erklären.

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
- [ ] **Gruppenmitglieder in späteren Status (Phase 4/5).** Wird eine Hauptdatei nach dem Kopieren
      neu analysiert (zweiter Scan, geänderte Quelle), ziehen nur Mitglieder mit Status
      `analysiert` mit; schon kopierte bleiben, wo sie sind. Beim Bericht entscheiden, ob das
      als Ereignis gemeldet wird.
- [ ] **Gruppenanhang im Wettlauf mit einem Fremdprozess (Phase 6).** Legt ein anderes Programm
      genau zwischen Anhang-Bestimmung und Umbenennen eine Datei unter `X_1` an, bekommt nur
      das betroffene Mitglied `_2`, die übrigen behalten `_1`. Nichts geht verloren, aber die
      Gruppe hat dann zwei Anhänge. Innerhalb des Programms kann das nicht passieren (Zielnamen
      „in Arbeit" warten). Mit `fotosort ziel-index` und dem Bericht sichtbar machen.
- [ ] **Windows-Zweig des nicht überschreibenden Umbenennens (`MoveFileExW`) ist im Container
      nicht prüfbar** und muss beim ersten Lauf unter Windows mit dem künstlichen Testbaum
      nachgezogen werden (`tests/test_pfade.py`, `tests/test_kopieren.py`).
- [ ] **Verschieben (`--verschieben`) kommt in Phase 5.** Der Schalter ist vorhanden und
      verweist dorthin; Umbenennen auf demselben Laufwerk und die Löschbedingung aus SPEC §5
      werden dort gebaut.
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

---

## Phase 6 — Geführter Modus und Tempo

- [ ] `fotosort start`, großer Testbaum, Profiler, `LIESMICH.md`

### Aus der Prüfung

- [ ] **Zwei Laufwerksbuchstaben auf derselben physischen Platte.** Die Laufwerkskennung für
      den parallelen Scan (SPEC §4 Phase 1) nimmt unter Windows den Laufwerksbuchstaben. Zwei
      Partitionen derselben Platte gelten damit als zwei Laufwerke und werden parallel gelesen,
      was auf einer Festplatte langsamer ist als nacheinander. Erkennen ließe sich das über die
      Volume-zu-Disk-Zuordnung (`IOCTL_STORAGE_GET_DEVICE_NUMBER`). Erst messen, ob es
      überhaupt ins Gewicht fällt.

- [ ] **Doppelte Lesezeit im Verschieben-Modus messen.** Seit SPEC §5 wird vor jeder Löschung
      auch die Quelldatei frisch gelesen, nicht nur die Zieldatei. Das ist richtig und schließt
      einen Verlustpfad — aber im Verschieben-Modus wird die Quelle damit zweimal vollständig
      gelesen: einmal beim Kopieren, einmal vor dem Löschen. Hier wird gemessen, wie viel das
      an echten Datenmengen ausmacht, bevor über eine Änderung überhaupt nachgedacht wird.
      Reihenfolge ist wichtig: **erst messen, dann bewerten.** Die Sicherheit steht nicht zur
      Disposition, solange die Messung nicht zeigt, dass es um wirklich relevante Zeit geht —
      und selbst dann wäre die Frage, ob man die Zeit anders holt (etwa durch eine engere
      Kopplung von Kopieren und Prüfen im selben Durchgang), nicht ob man die Prüfung streicht.

---

## Phase 7 — Weboberfläche

- [ ] FastAPI, nur Zusammenfassungen, eigener Prozess

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
