# To-do

Offene Punkte, nach der Phase sortiert, in der sie behandelt werden. Die Phasen stehen in
[`PROMPTS.md`](PROMPTS.md), der verbindliche Stand in [`SPEC.md`](SPEC.md).

Die Punkte unter „Aus der Prüfung" stammen aus drei Prüfrunden über die Dokumentation. Sie sind
bewusst nicht vorab in die SPEC eingearbeitet worden: Sie verhindern Phase 1 nicht, und sie
lassen sich besser entscheiden, wenn der betroffene Code gebaut wird. Beim Bau der jeweiligen
Phase werden sie abgearbeitet — nicht als Kür, sondern als Teil der Phase.

---

## Phase 1 — Grundgerüst, Testbaum, Scan

- [ ] Grundgerüst bauen: `pyproject.toml`, Paket `src/fotosort/`, Kommandozeile
- [ ] `config.toml` mit Kommentaren aus der Vorlage in SPEC §9
- [ ] SQLite-Schema: `dateien`, `ziel_index`, `laeufe`, `lauf_ereignisse`
- [ ] Testbaum-Skript mit allen Fällen aus SPEC §11
- [ ] `fotosort scan`, `fotosort status`, `fotosort config`
- [ ] Archiv-ID, Sicherungskopie von Datenbank und `config.toml`
- [ ] Prüfung auf ExifTool, Prüfung „Ziel in Quelle"

### Aus der Abnahme von Phase 1

Diese Punkte sind beim Abarbeiten der Abnahme-Befunde entstanden. Der Code ist jeweils schon
so gebaut; offen ist nur noch, ob die SPEC beim nächsten Durchgang nachgezogen wird.

- [ ] **Frage an den Nutzer: Legen `status` und `config` einen Lauf an?** SPEC §6 sagt wörtlich
      „Ein Lauf ist ein Programmstart. Jeder Start legt in der Tabelle `laeufe` eine Zeile an."
      SPEC §8 verlangt aber, dass `status` „den letzten Lauf" nennt — was sinnlos wäre, wenn
      `status` dabei selbst einen Lauf anlegt und sich dann selbst nennt. Die SPEC widerspricht
      sich hier. Gebaut ist die Lesart „nur verändernde Befehle legen einen Lauf an" (nur
      `scan`). Das ist **bewusst nicht geändert** worden: Nach `CLAUDE.md` wird bei einem
      Widerspruch nachgefragt, nicht geraten. Zu entscheiden ist eines von beidem:
      (a) SPEC §6 klarstellen — nur verändernde Befehle legen eine Zeile an (dann bleibt alles,
      wie es ist), oder (b) auch `status` und `config` schreiben eine Zeile, und `status` zeigt
      dann ausdrücklich den letzten Lauf **vor** dem eigenen.
- [ ] **Neue Ereignisarten in SPEC §6 nachtragen.** Die Aufzählung in §6 ist mit „z. B."
      eingeleitet und damit offen; der Code führt jetzt zusätzlich `ordner_nicht_lesbar`
      (ein Ordner ließ sich nicht öffnen), `quelle_veraendert` (die Berichtsliste „Quelle
      verändert, wird neu eingeordnet" aus §10) und `abgebrochen` (geordneter Abbruch, im
      Unterschied zum Absturz). Sauberer wäre, sie in §6 und in der Berichtsliste in §10
      mit aufzuzählen.
- [ ] **Schalter `--ziel-anlegen` in SPEC §8 nachtragen.** Ein nicht vorhandener Zielordner
      wird nicht mehr stillschweigend angelegt: Ein Tippfehler im Pfad — oder ein Netzlaufwerk,
      das gerade nicht eingebunden ist — ergäbe sonst ein zweites, leeres Archiv mit neuer
      Kennung, und das echte Archiv gälte danach als unbekannt (§6 begründet an anderer Stelle
      genau das). Der Scan bricht jetzt mit Meldung ab; `--ziel-anlegen` legt den Ordner
      wirklich an. In der Befehlsliste in §8 steht der Schalter noch nicht.
- [ ] **Sperrdatei im Archiv-Ordner in SPEC §6 nachtragen.** Neben `fotosort.db`,
      `config.toml` und den SQLite-Hilfsdateien liegt dort jetzt `fotosort.sperre`. Sie
      verhindert, dass zwei gleichzeitige Läufe einander die Datenbank wegsperren und beide
      scheitern. Die Sperre hält das Betriebssystem; stürzt das Programm ab, gibt es sie von
      selbst wieder frei, eine liegengebliebene Datei blockiert also nichts.
- [ ] **Beispiel für `ausschlussmuster` in SPEC §9 schärfen.** Das Beispiel `"*/Papierkorb/*"`
      traf einen Papierkorb-Ordner ganz oben in der Quelle nicht, weil der relative Pfad dort
      schlicht `Papierkorb/…` lautet und `*/` mindestens ein Zeichen davor verlangt. Der Code
      prüft ein mit `*/` beginnendes Muster jetzt zusätzlich ohne diesen Anfang. In der SPEC
      und im Kommentar der erzeugten `config.toml` könnte das Beispiel entsprechend erklärt
      werden.

### Aus der Prüfung

- [ ] **Erkennung des Dateisystemtyps festklopfen.** Unter Linux über den Einhängepunkt in
      `/proc/mounts` — das ist erprobt und funktioniert. Unter Windows über `GetDriveType`
      (`DRIVE_REMOTE`) und das UNC-Präfix; das ist hier im Container nicht prüfbar und muss
      beim ersten Lauf unter Windows nachgezogen werden. Betrifft SPEC §6 (Netzlaufwerk) und
      §4 Phase 3 (gleiches Laufwerk).

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
