# Bildschirmfotos der Oberfläche

Jede Ansicht des Programmfensters (PySide6/Qt, 1180 × 800), erzeugt am künstlichen Testbaum
aus SPEC §11 — nie mit echten Fotos. So entstehen sie, ohne Bildschirm (Qt offscreen):

```
QT_QPA_PLATFORM=offscreen fotosort fenster --durchlauf <Ziel> <Quelle> --fotos docs/oberflaeche
```

Der Durchlauf bedient das Fenster selbst: Startseite → Scan → Analyse → Kopieren → Prüfen →
Aufräumen. Der „laufende Schritt" (Bilder 05 und 06) ist ein eingespielter Beispielstand, weil
der Testbaum zu klein ist, um ihn mitten im Kopieren zu erwischen. Dieselbe Prüfung läuft in
der CI gegen das Windows-Paket.

| Bild | Ansicht |
|---|---|
| [01](01-startseite-leer.png) | Startseite, leer |
| [02](02-startseite-ausgefuellt.png) | Startseite mit Ziel, Quelle, Modus und Profil |
| [03](03-uebersicht-nach-scan.png) | Übersicht nach dem Scan (Phasenleiste, Zähler, Karten) |
| [04](04-uebersicht-nach-analyse-kameras.png) | Übersicht nach der Analyse mit Kamera-Tabelle (Alias tippbar) |
| [05](05-laufender-schritt-kopieren.png) | Laufender Schritt: Balken, Kennzahlen, Pause/Abbrechen |
| [06](06-laufender-schritt-pause.png) | Laufender Schritt angehalten |
| [07](07-uebersicht-nach-kopieren.png) | Übersicht nach dem Kopieren |
| [08](08-uebersicht-nach-pruefen-aufraeumen-karte.png) | Übersicht nach dem Prüfen, Aufräumen-Karte aktiv |
| [09](09-aufraeumen-bestaetigt.png) | Aufräumen: Bestätigungswort getippt, Knopf aktiv |
| [10](10-liste-duplikate.png) | Liste (Duplikate), seitenweise |
| [11](11-uebersicht-nach-aufraeumen-fertig.png) | Übersicht nach dem Aufräumen, alle Phasen erledigt |
| [12](12-dialog-ordner-anlegen.png) | Dialog „Ordner anlegen?" |

Design-Übergabe: [`../design/DESIGN.md`](../design/DESIGN.md).
