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
Schema-Version 3 (`kopiert_in_lauf`, Indizes auf Hash und Gruppe).

- [x] Kopieren über `.part`, nicht überschreibendes Umbenennen, BLAKE3 nebenbei
- [x] Duplikate (gleicher Name und über den Ziel-Index), Ziel-Index, Worker-Zahlen nach Profil
- [x] Absturzsicherheit: Anspruch vor dem Schreiben festgeschrieben, Reste beim nächsten Start
      (Pflichttest mit SIGKILL mitten im Kopieren und Neustart)
- [x] Rückfall ohne `.part` für exFAT/FAT32, in beiden Zweigen getestet
- [x] Zielpfad eines quellinternen Duplikats: zeigt auf die tatsächlich kopierte Partnerdatei,
      gesetzt erst, nachdem diese im Ziel steht und ihr Hash in diesem Lauf bekannt ist (SPEC §5)
- [x] Einmalige Probe je Ziel-Dateisystem mit einer Wegwerfdatei im Zielordner (SPEC §5)

### Aus dem Bau von Phase 3 (später)

- [ ] **Gruppe wird bei Inhalts-Duplikat eines Mitglieds getrennt (Phase 4, Bericht).** Ist nur
      das JPG eines RAW+JPG-Paars inhaltsgleich mit einer Datei, die schon im Ziel liegt, wird es
      `duplikat` und zeigt dorthin; das RAW wird kopiert und bekommt bei Namenskonflikt den
      Anhang. Nichts geht verloren, aber die beiden liegen dann unter verschiedenen Namen. Der
      Bericht soll solche Fälle unter „Duplikate" mit Partner ausweisen, damit man sie erkennt.
- [ ] **Gruppenmitglieder in späteren Status (Phase 4/5).** Wird eine Hauptdatei nach dem Kopieren
      neu analysiert (zweiter Scan, geänderte Quelle), ziehen nur Mitglieder mit Status
      `analysiert` mit; schon kopierte bleiben, wo sie sind. Beim Bericht entscheiden, ob das
      als Ereignis gemeldet wird.
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

- [ ] `fotosort pruefen`, `fotosort bericht`

---

## Phase 5 — Verschieben, Aufräumen, leere Ordner

- [ ] Alles, was löscht. Hier gilt SPEC §5 wörtlich.

### Aus der Prüfung

- [ ] **Zielordner aus allen Durchläufen über die Quelle ausnehmen, nicht nur aus dem Scan.**
      Liegt das Ziel innerhalb der Quelle, ist es bisher nur für den Scan ausgeschlossen
      (SPEC §4 Phase 1). Das Aufräumen der Quelle und das Entfernen leerer Ordner laufen aber
      ebenfalls über den Quellbaum und könnten in den Archivbaum hineinwandern — etwa einen
      gerade angelegten, noch leeren Tagesordner entfernen. Ein Bild geht dabei nicht verloren,
      aber es ist ein Eingriff ins Archiv, den niemand erwartet. Der Ausschluss gehört einmal
      allgemein formuliert und in jedem der drei Durchläufe geprüft.

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
