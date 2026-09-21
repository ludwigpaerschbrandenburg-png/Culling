# Offene Fragen zur SPEC

Ergebnis der Prüfung von [`SPEC.md`](SPEC.md) (Prompt 0). Elf Punkte, die vor dem Bauen
entschieden sein sollten. Zu jedem: wo es steht, was das Problem ist, und ein Vorschlag.

Beantwortet wird direkt in dieser Datei — Haken setzen und die gewählte Option markieren.
Die entschiedenen Punkte wandern anschließend in die SPEC.

**Dringlichkeit:** Punkte 1, 8, 9 und 10 betreffen den Löschpfad oder die Datenbank und
sollten vor Phase 1 stehen. Der Rest kann bis Phase 2 warten.

---

## Widersprüche

### 1. Dürfen Duplikate in der Quelle gelöscht werden?

**Dringend** — betrifft den Löschpfad.

- SPEC §4 Phase 5: gelöscht werden „ausschließlich Dateien mit Status *geprüft*".
- SPEC §5: ein Duplikat „wird nicht erneut kopiert, gilt aber als *im Ziel vorhanden*
  (und darf damit später in der Quelle gelöscht werden)".
- `PROMPTS.md` Prompt 5: löscht „Dateien mit Status *geprüft* (und Duplikate, deren Inhalt
  nachweislich per Hash im Ziel liegt)".

Ein Duplikat wird nie kopiert und bekommt darum nie den Status `geprüft`. Nach §4 wird es
also nie gelöscht, nach §5 schon. Drei Textstellen, drei Regeln.

**Vorschlag:** Eigener Status `duplikat_bestaetigt`. Er wird gesetzt, wenn die Zieldatei
frisch gelesen und ihr Hash mit dem der Quelldatei verglichen wurde — also derselbe Nachweis
wie bei `geprüft`, nur ohne Kopiervorgang davor. Gelöscht werden darf aus genau diesen beiden
Status. Damit steht in §4 und §5 dieselbe Regel.

- [ ] Vorschlag übernehmen
- [ ] Duplikate werden nie gelöscht (§5 streichen)
- [ ] anders: …

---

### 2. „Umbenennen" — ausgeschlossen oder nicht?

- SPEC §12: „Umbenennen von Dateien" gehört ausdrücklich **nicht** zum Projekt.
- SPEC §5: bei Namenskonflikt „neuer Name mit Anhang `_1`, `_2` …".

Beides zusammen liest sich widersprüchlich, gemeint ist offensichtlich zweierlei.

**Vorschlag:** §12 präzisieren auf „kein systematisches Umbenennen von Dateien (etwa nach
Datum oder Kamera)". Der `_1`-Anhang bleibt als Notausgang bei Namenskonflikten bestehen und
wird im Bericht aufgelistet, wie §10 es ohnehin vorsieht.

- [ ] Vorschlag übernehmen
- [ ] anders: …

---

### 3. Verschieben per Umbenennen lässt sich nicht prüfen

- SPEC §4 Phase 3: „Liegen Quelle und Ziel auf demselben Laufwerk, darf direkt umbenannt werden."
- SPEC §4 Phase 4: „jede Zieldatei wird erneut vollständig gelesen und ihr Hash mit dem der
  Quelle verglichen".

Nach einem Umbenennen gibt es die Quelle nicht mehr. Es gibt nichts, wogegen verglichen werden
könnte — die Prüfung vergleicht die Datei dann mit sich selbst.

Das ist nicht unsicher: ein Umbenennen innerhalb eines Laufwerks verschiebt keine Daten,
sondern ändert nur einen Verzeichniseintrag. Es ist die sicherste Variante überhaupt. Aber die
SPEC verspricht eine Prüfung, die es so nicht gibt.

**Vorschlag:** Hash vor dem Umbenennen berechnen und speichern. In der Phase „Prüfen" bekommen
diese Dateien den Status `geprüft (umbenannt)` mit dem Hinweis, dass hier keine zweite,
unabhängige Prüfung stattfand. Im Bericht getrennt ausweisen.

- [ ] Vorschlag übernehmen
- [ ] Direktes Umbenennen weglassen, immer kopieren und prüfen (langsamer, aber einheitlich)
- [ ] anders: …

---

### 4. `_Ohne_Datum/` ist fest verdrahtet

SPEC §3 macht die Ordner-Vorlage konfigurierbar
(`{jahr}/{jahr}-{monat} {monatsname}/…`), aber `_Ohne_Datum/<Kamera>` steht fest im Text.

**Vorschlag:** Auch als Konfigurationswert führen (Standard `_Ohne_Datum/{kamera}`). Kostet
nichts und ist konsistent.

- [ ] Vorschlag übernehmen
- [ ] bleibt fest
- [ ] anders: …

---

## Lücken

### 5. Videos ohne Zeitzonen-Offset

SPEC §3 (Datumsreihenfolge, Punkt 2): „`CreateDate` / `MediaCreateDate` (Videos; liegt oft in
UTC vor – **wenn ein Zeitzonen-Offset vorhanden ist**, in Ortszeit umrechnen)".

Der Fall „kein Offset vorhanden" ist nicht geregelt — und das ist bei MP4 und MOV der
Normalfall. Die Zeit steht dann in UTC, ohne dass irgendwo steht, welche Zeitzone gemeint war.

Praktische Folge: ein Video, das um 23:30 Ortszeit in Deutschland aufgenommen wurde, trägt
`CreateDate 21:30 UTC` — das ist derselbe Tag, passt also. Aber ein Video von 01:00 Ortszeit
trägt `23:00 UTC` vom **Vortag** und landet im falschen Tagesordner. Im Sommer (UTC+2) trifft
das alle Aufnahmen zwischen 00:00 und 02:00.

**Vorschlag:** Konfigurierbarer Standard-Offset (z. B. `+01:00`), der greift, wenn im Video
keiner steht. Zusätzlich: liegt die umgerechnete Zeit nahe an der Tagesgrenze (innerhalb der
Offset-Spanne), das Datum als **unsicher** markieren und im Bericht auflisten, damit man
nachsehen kann.

- [ ] Vorschlag übernehmen
- [ ] Offset fest auf die Zeitzone des Rechners
- [ ] Videos ohne Offset immer als unsicheres Datum behandeln (sicherste, aber unbequemste Variante)
- [ ] anders: …

---

### 6. Tagesgrenze greift nicht bei Datum aus dem Dateinamen

SPEC §3: Option „Tagesgrenze" (Standard 00:00, z. B. 04:00), damit Aufnahmen nach Mitternacht
noch zum Vortag zählen.

Kommt das Datum aus dem Dateinamen (Quelle 3), gibt es oft nur ein Datum ohne Uhrzeit — etwa
`2026-01-01 Urlaub.jpg`. Ohne Uhrzeit lässt sich die Tagesgrenze nicht anwenden.

**Vorschlag:** In dem Fall die Tagesgrenze überspringen und das Datum nehmen, wie es dasteht.
Im Bericht vermerken, bei wie vielen Dateien das passiert ist. Enthält der Dateiname eine
Uhrzeit (`IMG_20260101_013000`), wird die Tagesgrenze normal angewendet.

- [ ] Vorschlag übernehmen
- [ ] anders: …

---

### 7. XMP-Sidecars heißen anders als erwartet

SPEC §3 (Zusammengehörige Dateien): „Dateien mit gleichem **Stammnamen** im selben Quellordner
wandern gemeinsam", Sidecars unter anderem `.xmp`.

Lightroom, darktable und RawTherapee legen Sidecars aber meist als **vollständigen Dateinamen
plus Endung** ab:

```
DSC01234.ARW          ← das Bild
DSC01234.ARW.xmp      ← der Sidecar
DSC01234.xmp          ← so würde die Regel ihn erwarten
```

Der Stammname von `DSC01234.ARW.xmp` ist `DSC01234.ARW`, nicht `DSC01234`. Die Regel greift
also nicht — der Sidecar bliebe liegen, und damit alle Bearbeitungen.

**Vorschlag:** Beide Schreibweisen als zusammengehörig erkennen: gleicher Stammname **oder**
vollständiger Dateiname plus Sidecar-Endung. Beides mit Tests abdecken.

- [ ] Vorschlag übernehmen
- [ ] anders: …

---

## Technische Risiken

### 8. SQLite mit WAL liegt auf einem Netzlaufwerk

**Dringend** — blockiert Phase 1.

- SPEC §6: „Eine **SQLite-Datenbank** (WAL-Modus) … liegt standardmäßig im Zielordner unter
  `.fotosortierer/`, damit sie mit dem Archiv mitwandert."
- SPEC §2: „Quelle und Ziel können … SMB-Netzlaufwerke sein (auch UNC-Pfade wie
  `\\truenas\Daten\...`)."

Der WAL-Modus braucht eine geteilte Speicherdatei (`.db-shm`), die über SMB nicht funktioniert.
SQLite lehnt WAL auf Netzpfaden entweder ab oder — schlimmer — verhält sich unzuverlässig.
Genau das wäre der Standardfall hier: Ziel ist das NAS.

Der Wunsch dahinter ist trotzdem richtig — die Datenbank soll beim Archiv bleiben, damit ein
späterer Lauf weiß, was schon im Ziel liegt.

**Vorschlag:** Beim Start prüfen, ob der Datenbankpfad auf einem Netzlaufwerk liegt.
Wenn ja: Datenbank lokal führen (Temp-Ordner) und am Ende jeder Phase ins Ziel kopieren.
Beim nächsten Start von dort wieder holen. Der Nutzer merkt nichts, die Datenbank wandert
trotzdem mit dem Archiv mit. Fallback, falls das Kopieren scheitert: Journal-Modus `TRUNCATE`
statt WAL — langsamer, aber netzwerktauglich.

- [ ] Vorschlag übernehmen
- [ ] Datenbank immer lokal, Pfad in der Konfiguration (wandert dann nicht mit)
- [ ] anders: …

---

### 9. Der Ziel-Index darf keine Löschung rechtfertigen

**Dringend** — direkter Weg zum Bildverlust.

SPEC §6: „Bei späteren Läufen wird das Ziel nur auf Änderungen geprüft (Größe +
Änderungsdatum), nicht komplett neu gehasht."

Als Beschleunigung ist das richtig. Gefährlich wird es in Verbindung mit §5 und Punkt 1 oben:
Der gespeicherte Hash entscheidet, ob eine Quelldatei als Duplikat gilt — und ein Duplikat
darf gelöscht werden.

Größe und Änderungsdatum sind kein Beweis für gleichen Inhalt. Wird eine Zieldatei außerhalb
des Programms verändert (Reparaturprogramm, Synchronisierung, defekte Platte, Bearbeitung mit
erhaltenem Zeitstempel), steht in der Datenbank ein Hash, der nicht mehr stimmt. Das Programm
hält die Quelldatei dann für gesichert und löscht sie. Die einzige gute Kopie ist weg.

**Vorschlag:** Klare Trennung nach Folgenschwere.

- Der Ziel-Index darf entscheiden, ob **kopiert** wird (harmlos: im schlimmsten Fall wird eine
  Datei unnötig kopiert).
- Er darf **nie** entscheiden, ob **gelöscht** wird. Vor jeder Löschung wird die Zieldatei
  frisch gelesen und gehasht — ohne Ausnahme und ohne Abschaltmöglichkeit.

Das kostet Zeit, aber nur in Phase 5, die ohnehin selten und bewusst gestartet wird.

- [ ] Vorschlag übernehmen
- [ ] anders: …

---

### 10. `xxh3_128` ist nicht kollisionssicher

SPEC §7: „schneller Hash (`xxh3_128` oder `blake3`)".

`xxh3` ist eine Prüfsumme, kein kryptografischer Hash. Für das Erkennen von Duplikaten ist das
völlig ausreichend und schnell. Aber wenn eine Hash-Gleichheit eine **Löschung** erlaubt, ist
sie das letzte Sicherheitsnetz vor dem Datenverlust.

Bei 128 Bit ist eine zufällige Kollision praktisch ausgeschlossen. „Praktisch ausgeschlossen"
ist nur kein schöner Satz, wenn es um die einzige Kopie eines Fotos geht.

**Vorschlag:** `xxh3_128` überall dort, wo es um Tempo geht (Kopieren, Duplikate erkennen).
Unmittelbar vor einer Löschung, bei der Quelle und Ziel noch beide existieren, zusätzlich
byteweise vergleichen. Das liest die Dateien ohnehin schon (siehe Punkt 9) und kostet damit
fast nichts extra.

- [ ] Vorschlag übernehmen
- [ ] durchgehend `blake3` (kryptografisch, etwas langsamer, dann kein Byte-Vergleich nötig)
- [ ] anders: …

---

### 11. Lange Pfade unter Windows

SPEC §5 nennt „Pfad zu lang" als Fehlergrund, der eine Datei mit Status `fehler` zurücklässt.

Windows begrenzt Pfade standardmäßig auf 260 Zeichen. Bei tiefen Quellordnern plus der
Zielstruktur (`2026/2026-01 Januar/2026-01-01 Geburtstag Oma/A7C2/`) ist das schneller
erreicht, als man denkt. Diese Dateien würden dann einfach nicht einsortiert.

Das lässt sich vermeiden statt nur melden: mit dem Präfix `\\?\` (bzw. `\\?\UNC\` bei
Netzpfaden) hebt Windows die Grenze auf.

**Vorschlag:** Pfade unter Windows intern mit diesem Präfix ansprechen. „Pfad zu lang" bleibt
als Fehlergrund bestehen, sollte dann aber praktisch nie auftreten.

- [ ] Vorschlag übernehmen
- [ ] anders: …

---

## Kleinigkeiten, keine Entscheidung nötig

- Das Repository heißt `Culling`, das Projekt laut SPEC `Foto-Sortierer`. Nur kosmetisch.
- `docs/files.zip` enthält `SPEC.md` byteidentisch zur Datei im Repo — die Kopie im Zip ist
  überflüssig, schadet aber nicht.
