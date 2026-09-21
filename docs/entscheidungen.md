# Entscheidungen

Kurzes Log: was wurde entschieden, und vor allem warum. Hilft später, wenn die
Begründung nicht mehr präsent ist.

Neueste Einträge nach oben.

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
