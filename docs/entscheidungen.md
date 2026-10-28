# Entscheidungen

Kurzes Log: was wurde entschieden, und vor allem warum. Hilft später, wenn die
Begründung nicht mehr präsent ist.

Neueste Einträge nach oben.

---

## 2026-10-28 — Alles automatisch: ein Wort beim Start, dann bis zum Aufräumen

**Entscheidung (des Nutzers):** Im Fenster laufen Scan, Analyse, Kopieren, Prüfen und Aufräumen
nach „Los geht's“ von selbst nacheinander. Ein Schalter „Ablauf: Alles automatisch | Schritt für
Schritt“ steht auf der Startseite, Standard ist „Alles automatisch“. Auch das Aufräumen läuft
automatisch – nur in den Ordner `_geloescht_`, nie endgültig, nie leere Ordner. Einmal beim Start
wird das Wort `verschieben` verlangt. Verschieben läuft nie von selbst. Hat Prüfen Abweichungen
gefunden, wird nicht aufgeräumt. Solange gearbeitet wird, schläft Windows nicht ein (SPEC §8).

**Begründung:** Der Nutzer will das Programm starten, nach 1–5 Stunden wiederkommen und alles
fertig vorfinden, statt nach jedem Schritt „Weiter“ zu drücken. Das Wort beim Start ersetzt die
Bestätigung, die das Aufräumen sonst verlangt: Ohne Wort gäbe es keinen Schutz vor einem
versehentlichen Klick, und ein Wort am Ende widerspräche dem Wunsch. Der Ordner `_geloescht_`
macht das Aufräumen umkehrbar („Zurücklegen…“). Verschieben dagegen löscht endgültig und benutzt
dasselbe Wort – darum nie automatisch. Findet Prüfen Abweichungen, gilt „im Zweifel anhalten“
(CLAUDE.md §1). Die Kette geht nur vorwärts, wie `fotosort start`; so gibt es keine Schleife.
Die Bestätigung lebt nur im Speicher und erlischt bei jedem anderen Start, bei Abbrechen und
beim Schließen des Fensters.

**Alternativen:** Aufräumen weiter von Hand (vom Programm empfohlen, vom Nutzer verworfen).
Verschieben mit einer zweiten Bestätigung automatisch (verworfen: endgültiges Löschen nie ohne
eigenen Klick). Die Kette im Arbeitsprozess statt im Fenster (verworfen: ein Schritt je Prozess
bleibt, und das Fenster muss ohnehin offen sein). Die Browser-Fassung gleich mitziehen
(verschoben auf Phase 8 – unter Windows gibt es sie nicht mehr).

---

## 2026-09-21 — Toleranz beim Vergleich des Änderungsdatums bleibt bei 0,001 s

**Entscheidung:** Die Toleranz in `db._gleiche_zeit` bleibt bei einer Tausendstelsekunde
(`db.ZEIT_TOLERANZ`). Der Kommentar, der sie mit der Zwei-Sekunden-Rundung von FAT begründete,
war falsch und ist berichtigt.

**Begründung:** FAT rundet das Änderungsdatum zwar auf volle zwei Sekunden ab, liefert für
dieselbe Datei aber bei jedem Lesen denselben Wert; ein Versatz zwischen zwei Scans entsteht
dadurch nicht. Die Toleranz fängt allein die Rundung beim Hin- und Herrechnen der
Fließkommazahl ab. Eine Toleranz von zwei Sekunden würde dagegen echte Änderungen
verschlucken, die kurz nacheinander geschehen und die Dateigröße nicht ändern — und die
Änderungserkennung ist nach SPEC §6 genau `groesse` plus `mtime`.

**Alternativen:** Toleranz auf zwei Sekunden anheben. Verworfen, weil die sichere Seite die
andere ist: Verschiebt sich das Änderungsdatum wirklich (Sommerzeit auf exFAT-Karten,
verschiedene Uhren auf derselben SMB-Freigabe), gilt die Datei als verändert und wird neu
eingeordnet. Dabei geht nichts verloren, es wird nur noch einmal gearbeitet. Umgekehrt wäre
eine übersehene Änderung ein stiller Fehler. Tests halten das Verhalten bei 1 s und 3 s
Versatz fest.

---

## 2026-09-21 — Verknüpfungen stehen unter ihrem eigenen Pfad in der Datenbank

**Entscheidung:** In der Spalte `quellpfad` steht der Pfad, unter dem die Datei in der Quelle
gefunden wurde — nicht der aufgelöste Pfad, auf den eine Verknüpfung zeigt. Die Ordner darüber
sind aufgelöst (der Durchlauf beginnt an der aufgelösten Quellwurzel), die Datei selbst nicht.

**Begründung:** SPEC §6 nennt `quellpfad` den „absoluten, aufgelösten Pfad der Quelldatei".
Wörtlich genommen führte das in genau den Verlustpfad, den SPEC §4 Phase 1 für den Fall
„zeigt ins Ziel" schon schließt: Der gespeicherte Pfad zeigte aus der Quelle heraus, ein
späteres Aufräumen löschte die Originaldatei außerhalb der Quelle. Dazu kam, dass zwei
Verknüpfungen auf dieselbe Datei auf eine einzige Zeile fielen und die Zähler des Scans
auseinanderliefen (dieselbe Datei galt zugleich als neu und als unverändert).

**Alternativen:** Verknüpfungen auf Dateien gar nicht erfassen. Verworfen: Nach SPEC §3
bekommt jede gefundene Datei eine Zeile, und ohne Zeile ließe sich später nicht feststellen,
ob sie schon einmal gesehen wurde.

---

## JJJJ-MM-TT — Thema

**Entscheidung:** <!-- Was gilt ab jetzt. -->

**Begründung:** <!-- Warum so und nicht anders. -->

**Alternativen:** <!-- Was sonst noch zur Auswahl stand. Optional. -->
