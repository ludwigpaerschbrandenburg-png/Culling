/* fotosort - die Seite der Oberflaeche (Phase 7). Kein Rahmenwerk.
   Aufbau und Zustaende: docs/design/DESIGN.md. Alle Zahlen und Texte kommen
   fertig formatiert vom Server; hier wird nur gezeigt und geklickt. */
(function () {
  "use strict";

  var SCHRITTE = ["scan", "analyse", "kopieren", "pruefen", "aufraeumen"];
  var ENDE = { fertig: 1, abgebrochen: 1, fehler: 1, abgestuerzt: 1 };
  var Z = {
    zustand: null,        // /api/zustand
    ansicht: "start",     // start | haupt | liste
    vorher: "start",
    poll: null,
    letzterSchritt: "",   // zuletzt gelaufener Schritt (fuer die Zusammenfassung)
    naechster: null,      // /api/naechster
    zf: null,             // /api/zusammenfassung
    liste: { art: "", seite: 1 },
    abbruchZeit: 0,
    lauf: null
  };

  function $(id) { return document.getElementById(id); }
  function alle(sel, wurzel) { return Array.prototype.slice.call((wurzel || document).querySelectorAll(sel)); }
  function leer(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function el(tag, text, klasse) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = text;
    if (klasse) e.className = klasse;
    return e;
  }
  function knopf(text, klasse, klick) {
    var k = el("button", text, "btn " + klasse);
    k.type = "button";
    if (klick) k.onclick = klick;
    return k;
  }

  // ---------------------------------------------------------------- Server --
  function api(pfad, daten) {
    var opt = daten === undefined ? { method: "GET" }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(daten) };
    return fetch(pfad, opt).then(function (r) {
      return r.json().catch(function () { return { fehler: "Antwort nicht lesbar (" + r.status + ")" }; })
        .then(function (j) {
          if (!r.ok) throw new Error(j.fehler || ("Fehler " + r.status));
          return j;
        });
    });
  }

  function meldung(text, gut) {
    var m = $("meldung");
    if (!text) { m.classList.add("versteckt"); m.textContent = ""; return; }
    m.textContent = text;
    m.className = "meldung" + (gut ? "" : " fehler");
    $("meldung").scrollIntoView({ block: "nearest" });
  }
  function fehlerZeigen(f) { meldung(f && f.message ? f.message : String(f)); }

  // Dialog: Frage mit Ja/Nein; mit eingabe=true ein Feld (z. B. Bestaetigungswort).
  function dialog(titel, text, opt) {
    opt = opt || {};
    return new Promise(function (loesen) {
      $("dialog-titel").textContent = titel;
      $("dialog-text").textContent = text || "";
      var eingabe = $("dialog-eingabe");
      eingabe.value = "";
      eingabe.classList.toggle("versteckt", !opt.eingabe);
      $("dialog-ja").textContent = opt.ja || "Ja";
      $("dialog-nein").textContent = opt.nein || "Abbrechen";
      $("dialog").classList.remove("versteckt");
      function ende(ja) {
        $("dialog").classList.add("versteckt");
        $("dialog-ja").onclick = null; $("dialog-nein").onclick = null; eingabe.onkeydown = null;
        loesen({ ja: ja, wert: eingabe.value });
      }
      $("dialog-ja").onclick = function () { ende(true); };
      $("dialog-nein").onclick = function () { ende(false); };
      eingabe.onkeydown = function (e) { if (e.key === "Enter") ende(true); };
      if (opt.eingabe) eingabe.focus(); else $("dialog-ja").focus();
    });
  }

  function zeige(name) {
    if (Z.ansicht !== name) Z.vorher = Z.ansicht;
    Z.ansicht = name;
    alle(".ansicht").forEach(function (s) { s.classList.toggle("versteckt", s.id !== "seite-" + name); });
    leer($("aktionen"));   // nie Knoepfe der vorigen Ansicht stehen lassen
    meldung("");
    $("meldung").parentNode.scrollTop = 0;
  }

  function radio(name) {
    var r = alle("input[name=" + name + "]").filter(function (x) { return x.checked; })[0];
    return r ? r.value : "";
  }
  function radioSetzen(name, wert) {
    alle("input[name=" + name + "]").forEach(function (r) { r.checked = r.value === wert; });
  }

  // ---------------------------------------------------- Titel und Statusleiste --
  function rahmen() {
    var z = Z.zustand; if (!z) return;
    $("titel-ziel").textContent = z.ziel || "kein Zielordner";
    var laeuft = Z.lauf && !ENDE[Z.lauf.zustand] && Z.lauf.zustand;
    var nr = (laeuft && Z.lauf.lauf) || (z.archiv && z.archiv.lauf_nr) || 0;
    $("titel-lauf").textContent = nr ? "Lauf " + nr : "Lauf –";
    $("leiste-db").textContent = z.archiv && z.archiv.da ? "lokal" : "–";
    $("leiste-sicherung").textContent = (z.archiv && z.archiv.sicherung) || "–";
    $("leiste-sperre").textContent = laeuft ? "Archiv gesperrt · dieser Lauf" : (z.archiv && z.archiv.da ? "Archiv frei" : "");
    var b = (z.archiv && z.archiv.bericht) || {};
    $("bericht-name").textContent = b.name || "noch keiner";
    $("bericht-oeffnen").disabled = !b.txt;
    $("bericht-csv").disabled = !b.csv;
  }

  // -------------------------------------------------------------- Startseite --
  function startFuellen(z) {
    $("ziel").value = z.ziel || "";
    radioSetzen("modus", z.verschieben ? "verschieben" : "kopieren");
    radioSetzen("profil", z.profil);
    modusText(); profilText();
    quellenZeigen(z.quellen_neu);
    archivZeigen(z.archiv);
  }

  function modusText() {
    $("modus-text").textContent = radio("modus") === "verschieben"
      ? "Jede Datei wird erst nach geprüfter Kopie in der Quelle gelöscht."
      : "Die Quelle bleibt unverändert · aufräumen später.";
  }
  function profilText() {
    var z = Z.zustand; if (!z) return;
    var p = z.profile.filter(function (x) { return x.name === radio("profil"); })[0];
    $("profil-text").textContent = p ? p.text : "";
  }

  function quellenZeigen(neu) {
    var box = $("quellen");
    leer(box);
    (neu || []).forEach(function (q) {
      var t = el("span", null, "tag tag-neutral mono");
      t.appendChild(el("span", q, "ellipse"));
      var weg = el("span", "×", "weg");
      weg.title = "Entfernen";
      weg.onclick = function () {
        api("/api/quelle", { pfad: q, entfernen: true }).then(function (a) { Z.zustand.quellen_neu = a.quellen_neu; quellenZeigen(a.quellen_neu); }).catch(fehlerZeigen);
      };
      t.appendChild(weg);
      box.appendChild(t);
    });
    if (!(neu || []).length && !((Z.zustand && Z.zustand.archiv && Z.zustand.archiv.quellen) || []).length) {
      box.appendChild(el("span", "noch keine Quelle", "hinweis"));
    }
  }

  function archivZeigen(archiv) {
    var kicker = $("archiv-kicker"), text = $("archiv-text"), tags = $("archiv-quellen"), wm = $("weitermachen");
    leer(tags);
    wm.disabled = true;
    wm.textContent = "Weitermachen";
    if (!$("ziel").value.trim()) {
      kicker.textContent = "Zielordner"; text.textContent = "Noch kein Zielordner gewählt."; return;
    }
    if (!archiv || !archiv.da) {
      kicker.textContent = "Neues Archiv";
      text.textContent = archiv && archiv.ziel_existiert === false ? "Ordner wird bei „Los geht's“ nach Rückfrage angelegt." : "Ordner ist da · noch kein Archiv darin.";
      return;
    }
    kicker.textContent = "Angefangenes Archiv";
    if (archiv.laeuft) { text.textContent = "Gerade läuft ein Schritt."; return; }
    if (archiv.fehler) { text.textContent = archiv.fehler; return; }
    text.textContent = archiv.phase || "";
    (archiv.quellen || []).forEach(function (q) {
      var t = el("span", q, "tag tag-neutral mono bekannt"); t.title = "bereits erfasst"; tags.appendChild(t);
    });
    if (archiv.naechster && archiv.naechster !== "fertig") {
      wm.disabled = false;
      wm.textContent = "Weitermachen: " + kurzName(archiv.naechster);
    } else {
      wm.textContent = "Alles erledigt";
    }
  }

  function kurzName(schritt) {
    return { scan: "Scan", analyse: "Analyse", kopieren: Z.zustand && Z.zustand.verschieben ? "Verschieben" : "Kopieren", pruefen: "Prüfen", aufraeumen: "Aufräumen" }[schritt] || schritt;
  }

  function zielUebernehmen() {
    return api("/api/ziel", { ziel: $("ziel").value.trim() }).then(function (a) {
      Z.zustand.ziel = a.ziel; Z.zustand.archiv = a.archiv;
      archivZeigen(a.archiv); quellenZeigen(Z.zustand.quellen_neu); rahmen();
      if (a.archiv && a.archiv.profil && !Z.profilGewaehlt) { radioSetzen("profil", a.archiv.profil); profilText(); einstellungenSenden(); }
    }).catch(fehlerZeigen);
  }

  function ordnerWaehlen(start) {
    if (!(window.pywebview && window.pywebview.api)) return Promise.resolve("");
    return window.pywebview.api.ordner_waehlen(start || "").then(function (p) { return p || ""; });
  }

  function einstellungenSenden() {
    return api("/api/einstellungen", { verschieben: radio("modus") === "verschieben", profil: radio("profil") }).then(function (a) {
      Z.zustand.verschieben = a.verschieben; Z.zustand.profil = a.profil;
    }).catch(fehlerZeigen);
  }

  function quelleHinzu(pfad) {
    pfad = (pfad || "").trim();
    if (!pfad) { meldung("Bitte zuerst einen Ordner eintippen oder auswählen."); return; }
    api("/api/quelle", { pfad: pfad }).then(function (a) {
      $("quelle-neu").value = "";
      Z.zustand.quellen_neu = a.quellen_neu;
      quellenZeigen(a.quellen_neu);
      meldung("");
    }).catch(fehlerZeigen);
  }

  function los(zielAnlegen) {
    zielUebernehmen().then(function () {
      return api("/api/los", { ziel_anlegen: !!zielAnlegen });
    }).then(function (a) {
      if (a && a.frage === "ziel_anlegen") {
        return dialog("Ordner anlegen?", a.text, { ja: "Anlegen" }).then(function (r) { if (r.ja) los(true); });
      }
      if (a && a.gestartet) { hauptZeigen(); laufStarten(a.gestartet); }
    }).catch(fehlerZeigen);
  }

  function startAktionen() {
    var a = $("aktionen"); leer(a);
    a.appendChild(knopf("Los geht's", "btn-primary", function () { los(false); }));
    if (Z.zustand.archiv && Z.zustand.archiv.da) {
      a.appendChild(knopf("Übersicht", "btn-secondary", function () { hauptZeigen(); ruheZeigen(); }));
      a.appendChild(knopf("Einstellungen", "btn-secondary", einstellungenOeffnen));
    }
  }

  // ------------------------------------------------------------ Hauptansicht --
  function hauptZeigen() {
    zeige("haupt");
    pfadeZeigen();
  }

  function pfadeZeigen() {
    var z = Z.zustand, box = $("pfade");
    leer(box);
    var quellen = ((z.archiv && z.archiv.quellen) || []).concat(z.quellen_neu || []);
    quellen.forEach(function (q) { box.appendChild(el("span", q, "tag tag-neutral mono")); });
    box.appendChild(el("span", "→", "pfeil"));
    box.appendChild(el("span", z.ziel || "–", "tag tag-outline mono"));
    var rechts = el("span", null, "push flex-gap");
    rechts.appendChild(el("span", z.profil, "tag tag-neutral"));
    rechts.appendChild(el("span", z.verschieben ? "verschieben" : "kopieren", "tag tag-neutral"));
    box.appendChild(rechts);
  }

  function phasenSetzen(aktiv, anteil) {
    var idx = SCHRITTE.indexOf(aktiv);
    alle("#phasen-liste li").forEach(function (li, i) {
      li.className = idx < 0 ? "ist-fertig" : (i < idx ? "ist-fertig" : (i === idx ? "ist-aktiv" : ""));
      if (i === idx) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    var fuellung = idx < 0 ? 1 : (idx + (anteil || 0)) / SCHRITTE.length;
    $("phasen-fill").style.width = Math.round(fuellung * 100) + "%";
  }

  function kennzahlen(l) {
    var box = $("kennzahlen"); leer(box);
    function paar(text, einheit) {
      var s = el("span");
      var teile = String(text).split(" von ");
      s.appendChild(el("b", teile[0]));
      s.appendChild(document.createTextNode(teile.length > 1 ? " / " + teile[1] + " " + einheit : " " + einheit));
      return s;
    }
    if (!l || !l.text) return;
    box.appendChild(paar(l.text.dateien || "0", "Dateien"));
    if (l.bytes || l.gesamt_bytes) box.appendChild(paar(l.text.bytes, ""));
    if (l.text.rate) { var r = el("span"); r.appendChild(el("b", l.text.rate.replace(" MB/s", ""))); r.appendChild(document.createTextNode(" MB/s")); box.appendChild(r); }
    if (l.text.restzeit) { var t = el("span"); t.appendChild(document.createTextNode("Rest ")); t.appendChild(el("b", l.text.restzeit)); box.appendChild(t); }
    if (l.text.dauer && !ENDE[l.zustand]) { var d = el("span"); d.appendChild(document.createTextNode("bisher ")); d.appendChild(el("b", l.text.dauer)); box.appendChild(d); }
  }

  function zaehlerZeigen(zeilen) {
    var dl = $("zaehler"); leer(dl);
    (zeilen || []).forEach(function (z) {
      var div = el("div");
      div.appendChild(el("dt", z[0]));
      var wert = String(z[1]);
      div.appendChild(el("dd", wert, wert === "0" ? "null" : ""));
      dl.appendChild(div);
    });
  }

  // -- laufender Schritt ----------------------------------------------------
  function laufStarten(schritt) {
    Z.letzterSchritt = schritt || Z.letzterSchritt;
    Z.abbruchZeit = 0;
    $("kameras").classList.add("versteckt");
    $("log").classList.add("versteckt");
    zaehlerZeigen([]);
    $("aktuell").textContent = "Wird gestartet …";
    $("aktuell").classList.add("pulse");
    phasenSetzen(Z.letzterSchritt, 0);
    kartenSperren(true);
    laufAktionen({ zustand: "startet", schritt: Z.letzterSchritt });
    if (Z.poll) clearInterval(Z.poll);
    Z.poll = setInterval(laufAbfragen, 500);
    laufAbfragen();
  }

  function laufAbfragen() {
    api("/api/lauf").then(function (l) {
      Z.lauf = l;
      if (l.schritt) Z.letzterSchritt = l.schritt;
      laufFuellen(l);
      rahmen();
      if (ENDE[l.zustand]) {
        clearInterval(Z.poll); Z.poll = null;
        ruheZeigen(l);
      }
    }).catch(function (f) { $("aktuell").textContent = "Keine Verbindung: " + f.message; });
  }

  function laufFuellen(l) {
    var f = $("balken-fill");
    f.style.width = (l.anteil === null || l.anteil === undefined ? (ENDE[l.zustand] ? 100 : 0) : Math.round(l.anteil * 100)) + "%";
    kennzahlen(l);
    var text = (l.schritt_name || "") + " · " + (l.zustand_text || "");
    $("aktuell").textContent = text;
    $("aktuell").style.animationPlayState = ENDE[l.zustand] || l.zustand === "pause" ? "paused" : "running";
    $("aktuell").style.opacity = ENDE[l.zustand] ? "1" : "";
    phasenSetzen(l.schritt, l.anteil || 0);
    if (!ENDE[l.zustand]) laufAktionen(l);
    if (l.log) { $("log").textContent = l.log; $("log").classList.remove("versteckt"); }
  }

  function laufAktionen(l) {
    var a = $("aktionen"); leer(a);
    var weiter = knopf(Z.letzterSchritt ? kurzName(Z.letzterSchritt) + " läuft …" : "läuft …", "btn-primary");
    weiter.disabled = true;
    a.appendChild(weiter);
    if (l.zustand === "pause") a.appendChild(knopf("Fortsetzen", "btn-secondary", function () { steuern("weiter"); }));
    else a.appendChild(knopf("Pause", "btn-secondary", function () { steuern("pause"); }));
    a.appendChild(knopf("Abbrechen", "btn-secondary", function () {
      dialog("Schritt abbrechen?", "Das Bisherige bleibt gespeichert; der nächste Lauf macht dort weiter.", { ja: "Abbrechen", nein: "Weiterlaufen lassen" })
        .then(function (r) { if (r.ja) steuern("abbrechen"); });
    }));
    if (Z.abbruchZeit && Date.now() - Z.abbruchZeit > 20000) {
      a.appendChild(knopf("Sofort beenden", "btn-secondary", function () {
        dialog("Sofort beenden?", "Der Schritt reagiert nicht. Angefangene Kopien räumt der nächste Lauf auf.", { ja: "Sofort beenden" })
          .then(function (r) { if (r.ja) steuern("sofort"); });
      }));
    }
  }

  function steuern(wunsch) {
    api("/api/steuern", { wunsch: wunsch }).then(function (a) {
      if (wunsch === "abbrechen") Z.abbruchZeit = Date.now();
      if (a && a.text) meldung(a.text, true);
      laufAbfragen();
    }).catch(fehlerZeigen);
  }

  // -- Ruhe: Zusammenfassung des letzten Schritts, naechster Schritt --------
  function ruheZeigen(l) {
    kartenSperren(true);
    api("/api/zustand").then(function (z) {
      Z.zustand = z; rahmen(); pfadeZeigen();
      var lauf = l || z.lauf || {};
      Z.lauf = lauf;
      if (lauf.zustand && !ENDE[lauf.zustand] && lauf.zustand !== "") { laufStarten(lauf.schritt); return; }
      return api("/api/naechster").then(function (n) {
        Z.naechster = n;
        var letzter = Z.letzterSchritt || (ENDE[lauf.zustand] && lauf.schritt) || vorherigerSchritt(n.schritt, z.archiv && z.archiv.zaehler);
        Z.letzterSchritt = letzter;
        return api("/api/zusammenfassung?schritt=" + encodeURIComponent(letzter)).then(function (zf) {
          Z.zf = zf;
          $("balken-fill").style.width = "100%";
          kennzahlen(ENDE[lauf.zustand] ? lauf : null);
          $("aktuell").textContent = (zf.name || "") + " · " + (ENDE[lauf.zustand] && lauf.schritt === letzter ? lauf.zustand_text : "erledigt");
          $("aktuell").style.animationPlayState = "paused";
          $("aktuell").style.opacity = "1";
          zaehlerZeigen(zf.zeilen);
          if (lauf.log && lauf.schritt === letzter) { $("log").textContent = lauf.log; $("log").classList.remove("versteckt"); }
          else $("log").classList.add("versteckt");
          kamerasZeigen(letzter === "analyse" ? zf.modelle : null, zf.ohne_modell);
          phasenSetzen(n.schritt === "fertig" ? "" : n.schritt, 0);
          if (n.schritt === "fertig") { alle("#phasen-liste li").forEach(function (li) { li.className = "ist-fertig"; }); $("phasen-fill").style.width = "100%"; }
          kartenFuellen(n, z);
          ruheAktionen(n, zf);
        });
      });
    }).catch(fehlerZeigen);
  }

  function vorherigerSchritt(naechster, zaehler) {
    if (naechster === "fertig") return (zaehler && zaehler.quelle_geloescht) ? "aufraeumen" : "pruefen";
    var i = SCHRITTE.indexOf(naechster);
    return i > 0 ? SCHRITTE[i - 1] : "scan";
  }

  function ruheAktionen(n, zf) {
    var a = $("aktionen"); leer(a);
    var v = Z.zustand.verschieben;
    if (n.schritt === "analyse") a.appendChild(knopf("Analyse starten", "btn-primary", function () { schrittStarten("analyse"); }));
    else if (n.schritt === "pruefen") a.appendChild(knopf("Prüfen starten", "btn-primary", function () { schrittStarten("pruefen"); }));
    else if (n.schritt === "kopieren") a.appendChild(knopf((v ? "Verschieben" : "Kopieren") + " starten · " + n.n + " Dateien", "btn-primary", function () { kopierenStarten(n); }));
    else if (n.schritt === "aufraeumen") a.appendChild(knopf("Aufräumen · Wort rechts eintippen", "btn-primary", function () { $("auf-wort").focus(); }));
    else a.appendChild(knopf("Bericht öffnen", "btn-primary", function () { berichtOeffnen("neu"); }));
    if (zf && zf.fehler) a.appendChild(knopf("Fehler " + zf.fehler, "btn-ghost", function () { listeZeigen("fehler", 1); }));
    if (zf && zf.duplikate) a.appendChild(knopf("Duplikate " + zf.duplikate, "btn-ghost", function () { listeZeigen("duplikate", 1); }));
    a.appendChild(knopf("Ohne Datum", "btn-ghost", function () { listeZeigen("ohne_datum", 1); }));
    a.appendChild(knopf("Einstellungen", "btn-secondary", einstellungenOeffnen));
    a.appendChild(knopf("Startseite", "btn-secondary", function () { laden("start"); }));
  }

  function schrittStarten(schritt, extra) {
    var daten = { schritt: schritt };
    Object.keys(extra || {}).forEach(function (k) { daten[k] = extra[k]; });
    api("/api/schritt", daten).then(function (a) { laufStarten(a.gestartet); }).catch(fehlerZeigen);
  }

  function kopierenStarten(n) {
    if (!n.wort) { schrittStarten("kopieren"); return; }
    dialog("Verschieben bestätigen", n.text + " Zum Bestätigen „" + n.wort + "“ tippen:", { eingabe: true, ja: "Verschieben" })
      .then(function (r) { if (r.ja) schrittStarten("kopieren", { wort: r.wert }); });
  }

  // -- Kamera-Tabelle ---------------------------------------------------------
  function kamerasZeigen(modelle, ohne) {
    var box = $("kameras"); leer(box);
    if (!modelle || !modelle.length) { box.classList.add("versteckt"); return; }
    box.classList.remove("versteckt");
    var t = el("table", null, "table");
    var thead = el("thead"), kopf = el("tr");
    ["Kameramodell", "Dateien", "Ordnername im Archiv"].forEach(function (k, i) { kopf.appendChild(el("th", k, i === 1 ? "zahl" : "")); });
    thead.appendChild(kopf); t.appendChild(thead);
    var tbody = el("tbody");
    modelle.forEach(function (m) {
      var tr = el("tr");
      tr.appendChild(el("td", m.modell, "mono"));
      tr.appendChild(el("td", m.n_text, "zahl"));
      var td = el("td");
      var inp = el("input"); inp.type = "text"; inp.className = "input alias"; inp.value = m.ordner;
      inp.setAttribute("data-modell", m.modell); inp.setAttribute("data-alt", m.ordner); inp.setAttribute("spellcheck", "false");
      td.appendChild(inp); tr.appendChild(td);
      tbody.appendChild(tr);
    });
    t.appendChild(tbody);
    box.appendChild(t);
    var zeile = el("div", null, "zeile");
    zeile.appendChild(knopf("Ordnernamen übernehmen", "btn-ghost", aliaseSenden));
    if (ohne) zeile.appendChild(el("span", "ohne Modell: " + ohne + " → Ordner „Unbekannt“", "hinweis"));
    box.appendChild(zeile);
  }

  function aliaseSenden() {
    var neue = {};
    alle("input.alias").forEach(function (i) {
      var v = i.value.trim();
      if (v && v !== i.getAttribute("data-alt")) neue[i.getAttribute("data-modell")] = v;
    });
    if (!Object.keys(neue).length) { meldung("Kein Ordnername geändert.", true); return; }
    api("/api/aliase", { aliase: neue }).then(function (a) {
      meldung(a.text, true);
      if (a.gestartet) laufStarten(a.gestartet);
    }).catch(fehlerZeigen);
  }

  // -- Karten rechts ------------------------------------------------------------
  function kartenSperren(gesperrt) {
    ["auf-wort", "auf-los", "ordner-wort", "ordner-los"].forEach(function (id) { $(id).disabled = true; });
    $("karte-aufraeumen").classList.toggle("inaktiv", gesperrt);
    $("karte-ordner").classList.toggle("inaktiv", gesperrt);
  }

  function kartenFuellen(n, z) {
    var plan = n.plan || null;
    var box = $("auf-quellen"); leer(box);
    if (plan) {
      plan.je_quelle.forEach(function (q) {
        var d = el("div");
        d.appendChild(el("span", q.wurzel, "pfad mono"));
        d.appendChild(el("span", q.n_text + " · " + q.groesse, "zahl"));
        box.appendChild(d);
      });
      Z.woerter = plan.woerter;
    } else {
      box.appendChild(el("span", n.schritt === "fertig" ? "nichts mehr zu entfernen" : "erst nach dem Prüfen", "hinweis"));
    }
    var darf = !!(plan && plan.n > 0);
    $("karte-aufraeumen").classList.toggle("inaktiv", !darf);
    $("auf-wort").disabled = !darf;
    $("auf-wort").value = "";
    aufWortPruefen();
    var archivDa = !!(z.archiv && z.archiv.da);
    $("karte-ordner").classList.toggle("inaktiv", !archivDa);
    $("ordner-wort").disabled = !archivDa;
    $("ordner-wort").value = "";
    ordnerWortPruefen();
  }

  function aufWortSoll() { return (Z.woerter || { papierkorb: "verschieben", endgueltig: "loeschen" })[radio("weise")]; }
  function aufWortPruefen() {
    var soll = aufWortSoll();
    $("auf-wort-soll").textContent = soll;
    $("auf-los").textContent = radio("weise") === "endgueltig" ? "Endgültig löschen" : "Nach _geloescht_ verschieben";
    $("auf-los").disabled = $("auf-wort").disabled || $("auf-wort").value.trim().toLowerCase() !== soll;
  }
  function ordnerWortPruefen() {
    $("ordner-los").disabled = $("ordner-wort").disabled || $("ordner-wort").value.trim().toLowerCase() !== "entfernen";
  }

  // -- Bericht, Einstellungen ------------------------------------------------------
  function berichtOeffnen(art) {
    api("/api/bericht", { art: art }).then(function (a) {
      meldung(a.text, true);
      if (Z.zustand && Z.zustand.archiv) { Z.zustand.archiv.bericht = a.bericht; rahmen(); }
    }).catch(fehlerZeigen);
  }
  function einstellungenOeffnen() {
    api("/api/einstellungen_oeffnen", {}).then(function (a) { meldung(a.text, true); }).catch(fehlerZeigen);
  }

  // ------------------------------------------------------------------ Listen --
  var LISTEN = {
    fehler: ["Fehler", ["Datei", "Grund", "Größe"], function (z) { return [z.quellpfad, z.grund, z.groesse]; }],
    duplikate: ["Duplikate", ["Datei in der Quelle", "gleiche Datei im Archiv", "Größe"], function (z) { return [z.quellpfad, z.partner, z.groesse]; }],
    ohne_datum: ["Ohne Aufnahmedatum", ["Datei", "Zielordner", "Größe"], function (z) { return [z.quellpfad, z.zielpfad, z.groesse]; }]
  };

  function listeZeigen(art, seite) {
    Z.liste = { art: art, seite: seite || 1 };
    api("/api/liste?art=" + encodeURIComponent(art) + "&seite=" + Z.liste.seite).then(function (l) {
      if (Z.ansicht !== "liste") zeige("liste");
      var info = LISTEN[art];
      $("liste-titel").textContent = info[0];
      $("liste-gesamt").textContent = l.gesamt_text + (l.gesamt === 1 ? " Eintrag" : " Einträge") + " · 100 je Seite";
      $("liste-stand").textContent = l.seite + " / " + l.seiten;
      $("liste-zurueck").disabled = l.seite <= 1;
      $("liste-vor").disabled = l.seite >= l.seiten;
      var t = $("liste-tabelle"); leer(t);
      var thead = el("thead"), kopf = el("tr");
      info[1].forEach(function (k, i) { kopf.appendChild(el("th", k, i === 2 ? "zahl" : "")); });
      thead.appendChild(kopf); t.appendChild(thead);
      var tbody = el("tbody");
      l.zeilen.forEach(function (z) {
        var tr = el("tr");
        info[2](z).forEach(function (w, i) { tr.appendChild(el("td", w, i === 2 ? "zahl" : (i === 0 || art === "duplikate" || art === "ohne_datum" ? "mono" : ""))); });
        tbody.appendChild(tr);
      });
      if (!l.zeilen.length) { var tr0 = el("tr"); var td0 = el("td", "keine Einträge", "hinweis"); td0.colSpan = 3; tr0.appendChild(td0); tbody.appendChild(tr0); }
      t.appendChild(tbody);
      Z.liste.seite = l.seite;
      var a = $("aktionen"); leer(a);
      a.appendChild(knopf("Zurück", "btn-primary", function () { if (Z.vorher === "haupt") { hauptZeigen(); ruheZeigen(); } else laden("start"); }));
      Object.keys(LISTEN).forEach(function (k) { if (k !== art) a.appendChild(knopf(LISTEN[k][0], "btn-ghost", function () { listeZeigen(k, 1); })); });
    }).catch(fehlerZeigen);
  }

  // ------------------------------------------------------------------ Start --
  function laden(ansicht) {
    api("/api/zustand").then(function (z) {
      Z.zustand = z;
      Z.lauf = z.lauf || {};
      document.body.classList.toggle("ohne-fenster", !z.fenster);
      rahmen();
      startFuellen(z);
      var l = z.lauf || {};
      if (l.zustand && !ENDE[l.zustand] && l.zustand !== "") { hauptZeigen(); laufStarten(l.schritt); return; }
      if (ansicht === "haupt") { hauptZeigen(); ruheZeigen(); return; }
      zeige("start");
      startAktionen();
    }).catch(fehlerZeigen);
  }

  function verdrahten() {
    $("ziel").addEventListener("change", zielUebernehmen);
    $("ziel-waehlen").onclick = function () {
      ordnerWaehlen($("ziel").value).then(function (p) { if (p) { $("ziel").value = p; zielUebernehmen(); } });
    };
    $("quelle-hinzu").onclick = function () { quelleHinzu($("quelle-neu").value); };
    $("quelle-neu").addEventListener("keydown", function (e) { if (e.key === "Enter") quelleHinzu($("quelle-neu").value); });
    $("quelle-waehlen").onclick = function () { ordnerWaehlen("").then(function (p) { if (p) quelleHinzu(p); }); };
    alle("input[name=modus]").forEach(function (r) { r.addEventListener("change", function () { modusText(); einstellungenSenden(); }); });
    alle("input[name=profil]").forEach(function (r) { r.addEventListener("change", function () { Z.profilGewaehlt = true; profilText(); einstellungenSenden(); }); });
    $("weitermachen").onclick = function () { zielUebernehmen().then(function () { Z.letzterSchritt = ""; hauptZeigen(); ruheZeigen(); }); };
    alle("input[name=weise]").forEach(function (r) { r.addEventListener("change", aufWortPruefen); });
    $("auf-wort").addEventListener("input", aufWortPruefen);
    $("auf-wort").addEventListener("keydown", function (e) { if (e.key === "Enter" && !$("auf-los").disabled) $("auf-los").click(); });
    $("auf-los").onclick = function () { schrittStarten("aufraeumen", { weise: radio("weise"), wort: $("auf-wort").value }); };
    $("ordner-wort").addEventListener("input", ordnerWortPruefen);
    $("ordner-los").onclick = function () { schrittStarten("aufraeumen", { leere_ordner: true, wort_ordner: $("ordner-wort").value, wort: "" }); };
    $("bericht-oeffnen").onclick = function () { berichtOeffnen("txt"); };
    $("bericht-csv").onclick = function () { berichtOeffnen("csv"); };
    $("bericht-neu").onclick = function () { berichtOeffnen("neu"); };
    $("liste-zurueck").onclick = function () { listeZeigen(Z.liste.art, Z.liste.seite - 1); };
    $("liste-vor").onclick = function () { listeZeigen(Z.liste.art, Z.liste.seite + 1); };
  }

  document.addEventListener("DOMContentLoaded", function () { verdrahten(); laden("start"); });
})();
