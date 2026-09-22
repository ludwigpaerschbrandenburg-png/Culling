/* Bildschirmfotos jeder Ansicht der Oberflaeche (Playwright, Chromium), fuer docs/oberflaeche/.
   Laeuft gegen "fotosort fenster --ohne-fenster --port 47812" mit dem kuenstlichen Testbaum. */
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.env.S, ZIEL = process.env.ZIEL, QUELLE = process.env.QUELLE, AUS = process.env.AUS, OB = process.env.OB;
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1180, height: 800 }, deviceScaleFactor: 1 });
  const fehler = [];
  page.on('pageerror', e => fehler.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/400/.test(m.text())) fehler.push('console: ' + m.text()); });
  const foto = async (name) => { await page.waitForTimeout(400); await page.screenshot({ path: `${AUS}/${name}.png`, fullPage: false }); console.log('Foto', name); };
  const sichtbar = async (id) => page.waitForSelector('#' + id + ':not(.versteckt)', { timeout: 60000 });
  const ruhe = async () => { await sichtbar('seite-haupt'); await page.waitForFunction(() => { const a = document.querySelector('#aktionen .btn-primary'); return a && !a.disabled; }, null, { timeout: 180000 }); };
  const laufEnde = async () => { await page.waitForFunction(() => /läuft/.test((document.querySelector('#aktionen .btn-primary') || {}).textContent || ''), null, { timeout: 30000 }).catch(() => {}); await ruhe(); };
  const api = async (pfad, daten) => page.evaluate(async ([p, d]) => { const r = await fetch(p, d ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) } : {}); return r.json(); }, [pfad, daten || null]);

  await page.goto('http://127.0.0.1:47812/');
  await sichtbar('seite-start');
  await foto('01-startseite-leer');

  await page.fill('#ziel', ZIEL); await page.press('#ziel', 'Tab'); await page.waitForTimeout(400);
  await page.fill('#quelle-neu', QUELLE); await page.click('#quelle-hinzu'); await page.waitForSelector('#quellen .tag');
  await foto('02-startseite-ausgefuellt');

  await page.click('#aktionen .btn-primary');          // Los geht's -> Scan
  await sichtbar('seite-haupt');
  await laufEnde();
  await foto('03-uebersicht-nach-scan');

  await page.click('#aktionen .btn-primary');          // Analyse starten
  await laufEnde();
  await foto('04-uebersicht-nach-analyse-kameras');

  // Laufender Schritt: ein Stand wie mitten im Kopieren (die Testdateien sind dafuer zu klein).
  const pid = await page.evaluate(() => 0);
  const jetzt = Date.now() / 1000;
  fs.writeFileSync(`${OB}/status.json`, JSON.stringify({ schritt: 'kopieren', zustand: 'laeuft', pid: Number(process.env.SERVER_PID), beginn: jetzt - 312, aktualisiert: jetzt, dateien: 1284, gesamt: 3912, bytes: 18.6 * 1024 ** 3, gesamt_bytes: 48.2 * 1024 ** 3, bytes_pro_s: 186 * 1024 ** 2, restzeit_s: 720, sekunden: 312, lauf: 3, rc: null, hinweis: '' }));
  fs.writeFileSync(`${OB}/auftrag.json`, JSON.stringify({ schritt: 'kopieren', ziel: ZIEL }));
  await page.reload();
  await sichtbar('seite-haupt');
  await page.waitForFunction(() => /1\.284/.test(document.querySelector('#kennzahlen').textContent), null, { timeout: 20000 });
  await foto('05-laufender-schritt-kopieren');
  await page.click('#aktionen .btn-secondary');        // Pause (nur die Steuerdatei; der Stand ist ein Beispiel)
  await page.waitForTimeout(600);
  fs.writeFileSync(`${OB}/status.json`, JSON.stringify(Object.assign(JSON.parse(fs.readFileSync(`${OB}/status.json`)), { zustand: 'pause', aktualisiert: Date.now() / 1000 })));
  await page.waitForFunction(() => /Angehalten/.test(document.querySelector('#aktuell').textContent), null, { timeout: 20000 });
  await foto('06-laufender-schritt-pause');
  // Beispielstand wieder entfernen: Schritt als fertig markieren, dann echte Uebersicht laden.
  fs.writeFileSync(`${OB}/status.json`, JSON.stringify(Object.assign(JSON.parse(fs.readFileSync(`${OB}/status.json`)), { zustand: 'fertig', rc: 0, aktualisiert: Date.now() / 1000 })));
  await page.waitForTimeout(1200);
  await page.reload(); await sichtbar('seite-start');
  await page.click('#weitermachen');
  await ruhe();

  await page.click('#aktionen .btn-primary');          // Kopieren starten
  await laufEnde();
  await foto('07-uebersicht-nach-kopieren');

  await page.click('#aktionen .btn-primary');          // Pruefen starten
  await laufEnde();
  await foto('08-uebersicht-nach-pruefen-aufraeumen-karte');

  await page.fill('#auf-wort', 'verschieben');
  await page.waitForFunction(() => !document.querySelector('#auf-los').disabled);
  await foto('09-aufraeumen-bestaetigt');

  await page.click('#aktionen .btn-ghost:has-text("Duplikate")');
  await sichtbar('seite-liste');
  await foto('10-liste-duplikate');
  await page.click('#aktionen .btn-primary');          // Zurueck
  await ruhe();

  // Dialog (Frage) als Beispiel: Abbrechen-Dialog ueber die Verschieben-Bestaetigung geht nur im Verschieben-Modus;
  // hier der Dialog "Ordner anlegen?" von der Startseite.
  await page.fill('#auf-wort', 'verschieben');         // nach dem Seitenwechsel ist das Feld wieder leer
  await page.waitForFunction(() => !document.querySelector('#auf-los').disabled);
  await page.click('#auf-los');                        // Aufraeumen starten
  await laufEnde();
  await foto('11-uebersicht-nach-aufraeumen-fertig');

  await page.click('#aktionen .btn-secondary:has-text("Startseite")');
  await sichtbar('seite-start');
  await page.fill('#ziel', ZIEL + '_neu'); await page.press('#ziel', 'Tab'); await page.waitForTimeout(300);
  await page.fill('#quelle-neu', QUELLE); await page.click('#quelle-hinzu').catch(() => {});
  await page.waitForTimeout(300);
  await page.click('#aktionen .btn-primary');
  await page.waitForSelector('#dialog:not(.versteckt)');
  await foto('12-dialog-ordner-anlegen');
  await page.click('#dialog-nein');

  console.log('FEHLER:', fehler);
  await browser.close();
  if (fehler.length) process.exit(1);
})().catch(e => { console.error('FOTOS FEHLER', e); process.exit(1); });
