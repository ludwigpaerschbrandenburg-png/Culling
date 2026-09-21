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

- [ ] Metadaten über ExifTool im Stapelbetrieb (`-stay_open`)
- [ ] Datumsermittlung mit allen sechs Quellen aus SPEC §3
- [ ] Kamera-Aliase, Gruppen, Zielpfad-Berechnung

### Aus der Prüfung

- [ ] **Testbaum um den vorbelegten Zielnamen erweitern.** Der Fall „im Ziel liegt schon eine
      Datei unter dem berechneten Zielnamen" braucht die Zielpfad-Berechnung und entsteht
      deshalb erst hier (SPEC §11). In Phase 1 erzeugt das Skript nur den Quellbaum.

---

## Phase 3 — Kopieren

- [ ] Kopieren über `.part`, nicht überschreibendes Umbenennen, BLAKE3 nebenbei
- [ ] Duplikate, Ziel-Index, Worker-Zahlen, Absturzsicherheit

### Aus der Prüfung

- [ ] **Zielpfad eines quellinternen Duplikats festlegen.** Zwei inhaltsgleiche Quelldateien
      haben meist verschiedene Namen und damit verschiedene berechnete Zielpfade; kopiert wird
      nur eine. Für die andere ist offen, worauf ihr `zielpfad` zeigt und welche Datei vor dem
      Löschen als „die Zieldatei" frisch gelesen wird. Vorschlag: Sie bekommt den tatsächlichen
      Zielpfad der bereits kopierten Partnerdatei, und zwar erst, nachdem diese dort
      nachweislich existiert und geprüft ist. Solange der `zielpfad` leer ist, darf sie nicht
      gelöscht werden. Betrifft SPEC §5 und §6.
- [ ] **Einmalige Probe je Ziel-Dateisystem.** Die SPEC verlangt, dass das Programm feststellt,
      ob ein Dateisystem nicht überschreibendes Umbenennen kann (exFAT/FAT32 können es nicht).
      *Wie* es das feststellt, ist Umsetzungssache und wird hier entschieden — naheliegend ist
      ein einmaliger Versuch mit einer Wegwerfdatei je Ziel-Dateisystem, dessen Ergebnis für
      den Lauf gemerkt wird.

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
