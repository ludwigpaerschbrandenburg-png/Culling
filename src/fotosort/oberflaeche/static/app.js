/* Die Seite der Oberflaeche (Phase 7). Kein Rahmenwerk, keine fremde Bibliothek.
   Alle Zahlen und Zusammenfassungen kommen fertig formatiert vom Server. */
(function () {
  "use strict";

  var Z = { zustand: null, seite: "start", vorher: "start", schritt: "", poll: null, abbruchZeit: 0, liste: { art: "", seite: 1 }, naechster: null };
  var ENDE = { fertig: 1, abgebrochen: 1, fehler: 1, abgestuerzt: 1 };

  function $(id) { return document.getElementById(id); }
  function alle(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function leer(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function el(tag, text, klasse) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = text;
    if (klasse) e.className = klasse;
    return e;
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
    m.className = "meldung" + (gut ? " gut" : "");
    window.scrollTo(0, 0);
  }
  function fehlerZeigen(f) { meldung(f && f.message ? f.message : String(f)); }

  function frage(text) {
    return new Promise(function (loesen) {
      $("frage-text").textContent = text;
      $("frage").classList.remove("versteckt");
      function ende(antwort) {
        $("frage").classList.add("versteckt");
        $("frage-ja").onclick = null; $("frage-nein").onclick = null;
        loesen(antwort);
      }
      $("frage-ja").onclick = function () { ende(true); };
      $("frage-nein").onclick = function () { ende(false); };
    });
  }

  function zeige(name) {
    if (Z.seite !== name) Z.vorher = Z.seite;
    Z.seite = name;
    alle(".seite").forEach(function (s) { s.classList.toggle("versteckt", s.id !== "seite-" + name); });
    meldung("");
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------ Startseite --
  function startseiteFuellen(z) {
    Z.zustand = z;
    $("version").textContent = "Version " + z.version;
    document.body.classList.toggle("ohne-fenster", !z.fenster);
    $("ziel").value = z.ziel || "";
    var sel = $("profil");
    leer(sel);
    z.profile.forEach(function (p) {
      var o = el("option", p.name === "hdd" ? "Festplatte" : p.name === "ssd" ? "SSD" : "Netzlaufwerk");
      o.value = p.name;
      sel.appendChild(o);
    });
    sel.value = z.profil;
    profilText();
    alle("input[name=modus]").forEach(function (r) { r.checked = (r.value === "verschieben") === !!z.verschieben; });
    quellenZeigen(z.quellen_neu, z.archiv);
    archivZeigen(z.archiv);
  }

  function profilText() {
    var z = Z.zustand; if (!z) return;
    var p = z.profile.filter(function (x) { return x.name === $("profil").value; })[0];
    $("profil-text").textContent = p ? p.text : "";
  }

  function quellenZeigen(neu, archiv) {
    var ul = $("quellen");
    leer(ul);
    var bekannt = (archiv && archiv.quellen) || [];
    bekannt.forEach(function (q) {
      var li = el("li");
      li.appendChild(el("span", q, "pfad"));
      li.appendChild(el("span", "bereits erfasst", "bekannt"));
      ul.appendChild(li);
    });
    (neu || []).forEach(function (q) {
      var li = el("li");
      li.appendChild(el("span", q, "pfad"));
      var k = el("button", "Entfernen", "knopf klein");
      k.onclick = function () {
        api("/api/quelle", { pfad: q, entfernen: true }).then(function (a) { quellenZeigen(a.quellen_neu, Z.zustand.archiv); }).catch(fehlerZeigen);
      };
      li.appendChild(k);
      ul.appendChild(li);
    });
    if (!bekannt.length && !(neu || []).length) {
      var li0 = el("li", "Noch kein Quellordner. Bitte unten einen eintragen.");
      li0.style.color = "#5a6270";
      ul.appendChild(li0);
    }
  }

  function archivZeigen(archiv) {
    var box = $("archiv-info"), wm = $("weitermachen-box"), wz = $("werkzeuge");
    box.classList.add("versteckt"); wm.classList.add("versteckt"); wz.classList.add("versteckt");
    if (!archiv || !archiv.da) {
      if (archiv && archiv.ziel_existiert === false && $("ziel").value) {
        box.textContent = "Diesen Ordner gibt es noch nicht. Er wird bei „Los geht's“ nach Rückfrage angelegt.";
        box.className = "hinweis";
      }
      return;
    }
    box.className = "hinweis gut";
    if (archiv.laeuft) {
      box.textContent = "In diesem Ordner liegt ein Archiv; gerade läuft ein Schritt.";
    } else if (archiv.fehler) {
      box.className = "hinweis";
      box.textContent = archiv.fehler;
    } else {
      box.textContent = "In diesem Ordner liegt bereits ein angefangenes Archiv. " + (archiv.phase || "");
      wz.classList.remove("versteckt");
      if (archiv.naechster && archiv.naechster !== "fertig") {
        $("weitermachen-text").textContent = "Offener Schritt: " + archiv.naechster_name;
        wm.classList.remove("versteckt");
      }
    }
    box.classList.remove("versteckt");
  }

  function zielUebernehmen() {
    return api("/api/ziel", { ziel: $("ziel").value.trim() }).then(function (a) {
      Z.zustand.ziel = a.ziel; Z.zustand.archiv = a.archiv;
      archivZeigen(a.archiv);
      quellenZeigen(Z.zustand.quellen_neu, a.archiv);
      if (a.archiv && a.archiv.profil && !Z.profilGewaehlt) { $("profil").value = a.archiv.profil; profilText(); einstellungenSenden(); }
    }).catch(fehlerZeigen);
  }

  function ordnerWaehlen(start) {
    if (!(window.pywebview && window.pywebview.api)) return Promise.resolve("");
    return window.pywebview.api.ordner_waehlen(start || "").then(function (p) { return p || ""; });
  }

  function einstellungenSenden() {
    var verschieben = alle("input[name=modus]").filter(function (r) { return r.checked; })[0].value === "verschieben";
    return api("/api/einstellungen", { verschieben: verschieben, profil: $("profil").value }).then(function (a) {
      Z.zustand.verschieben = a.verschieben; Z.zustand.profil = a.profil;
    }).catch(fehlerZeigen);
  }

  function quelleHinzu(pfad) {
    pfad = (pfad || "").trim();
    if (!pfad) { meldung("Bitte zuerst einen Ordner eintippen oder auswählen."); return; }
    api("/api/quelle", { pfad: pfad }).then(function (a) {
      $("quelle-neu").value = "";
      Z.zustand.quellen_neu = a.quellen_neu;
      quellenZeigen(a.quellen_neu, Z.zustand.archiv);
      meldung("");
    }).catch(fehlerZeigen);
  }

  function los(zielAnlegen) {
    $("los").disabled = true;
    zielUebernehmen().then(function () {
      return api("/api/los", { ziel_anlegen: !!zielAnlegen });
    }).then(function (a) {
      if (a && a.frage === "ziel_anlegen") {
        return frage(a.text).then(function (ja) { if (ja) los(true); });
      }
      if (a && a.gestartet) laufZeigen(a.gestartet);
    }).catch(fehlerZeigen).then(function () { $("los").disabled = false; });
  }

  // -------------------------------------------------------------- Laufseite --
  function laufZeigen(schritt) {
    zeige("lauf");
    if (schritt && Z.zustand) {
      $("lauf-titel").textContent = Z.zustand.schritte[schritt] || "";
      $("lauf-zustand").textContent = "Wird gestartet …";
    }
    $("lauf-log").classList.add("versteckt");
    $("sofort").classList.add("versteckt");
    Z.abbruchZeit = 0;
    if (Z.poll) clearInterval(Z.poll);
    Z.poll = setInterval(laufAbfragen, 500);
    laufAbfragen();
  }

  function laufAbfragen() {
    api("/api/lauf").then(function (l) {
      laufFuellen(l);
      if (ENDE[l.zustand]) {
        clearInterval(Z.poll); Z.poll = null;
        Z.schritt = l.schritt;
        zusammenfassungZeigen(l);
      }
    }).catch(function (f) { $("lauf-zustand").textContent = "Keine Verbindung: " + f.message; });
  }

  function laufFuellen(l) {
    $("lauf-titel").textContent = l.schritt_name || "";
    var erkl = Z.zustand && Z.zustand.erklaerungen ? Z.zustand.erklaerungen[l.schritt === "kopieren" && Z.zustand.verschieben ? "verschieben" : l.schritt] : "";
    $("lauf-erklaerung").textContent = erkl || "";
    var f = $("balken-fuellung");
    if (l.anteil === null || l.anteil === undefined) {
      f.classList.add("unbestimmt"); f.style.width = "";
      $("balken-text").textContent = l.zustand === "startet" ? "" : "wird gezählt …";
    } else {
      f.classList.remove("unbestimmt");
      f.style.width = Math.round(l.anteil * 100) + "%";
      $("balken-text").textContent = Math.round(l.anteil * 100) + " %";
    }
    if (ENDE[l.zustand]) { f.classList.remove("unbestimmt"); if (l.zustand === "fertig") { f.style.width = "100%"; $("balken-text").textContent = "100 %"; } }
    $("lauf-dateien").textContent = l.text ? l.text.dateien : "–";
    $("lauf-bytes").textContent = l.text && l.text.bytes !== "0 B" ? l.text.bytes : "–";
    $("lauf-rate").textContent = l.text && l.text.rate ? l.text.rate : "–";
    $("lauf-rest").textContent = l.text && l.text.restzeit ? l.text.restzeit : "–";
    $("lauf-dauer").textContent = l.text ? l.text.dauer : "–";
    $("lauf-zustand").textContent = (l.zustand_text || "") + (l.hinweis && l.zustand !== "abgestuerzt" ? " – " + l.hinweis : "");
    var pause = l.zustand === "pause";
    $("pause").classList.toggle("versteckt", pause || !!ENDE[l.zustand]);
    $("fortsetzen").classList.toggle("versteckt", !pause);
    $("abbrechen").classList.toggle("versteckt", !!ENDE[l.zustand]);
    if (Z.abbruchZeit && !ENDE[l.zustand] && Date.now() - Z.abbruchZeit > 20000) $("sofort").classList.remove("versteckt");
    if (l.log) { $("lauf-log").textContent = l.log; $("lauf-log").classList.remove("versteckt"); }
  }

  function steuern(wunsch) {
    api("/api/steuern", { wunsch: wunsch }).then(function (a) {
      if (wunsch === "abbrechen") Z.abbruchZeit = Date.now();
      if (a && a.text) meldung(a.text, true);
      laufAbfragen();
    }).catch(fehlerZeigen);
  }

  // -------------------------------------------------------- Zusammenfassung --
  function zusammenfassungZeigen(l) {
    zeige("zusammenfassung");
    $("zf-titel").textContent = "Erledigt: " + (l.schritt_name || l.schritt);
    $("zf-zustand").textContent = (l.zustand_text || "") + (l.hinweis && l.zustand !== "abgestuerzt" ? " – " + l.hinweis : "");
    leer($("zf-tabelle")); leer($("zf-extra"));
    $("zf-karte").classList.add("versteckt");
    $("zf-weiter").classList.remove("versteckt");
    $("zf-weiter").disabled = true;
    $("zf-weiter").textContent = "Weiter";
    $("zf-fehler").classList.add("versteckt"); $("zf-duplikate").classList.add("versteckt");
    Z.naechster = null;
    api("/api/zusammenfassung?schritt=" + encodeURIComponent(l.schritt)).then(function (zf) {
      var t = $("zf-tabelle");
      zf.zeilen.forEach(function (z) {
        var tr = el("tr");
        tr.appendChild(el("td", z[0]));
        var td = el("td", z[1], "zahl");
        tr.appendChild(td);
        t.appendChild(tr);
      });
      if (zf.fehler) $("zf-fehler").classList.remove("versteckt");
      if (zf.duplikate) $("zf-duplikate").classList.remove("versteckt");
      if (l.schritt === "scan" && zf.quellen) quellenTabelle(zf.quellen);
      if (l.schritt === "analyse") { jahreTabelle(zf.je_jahr || []); modelleTabelle(zf.modelle || [], zf.ohne_modell || 0); }
      if (l.log) { var pre = el("pre", l.log, "log"); $("zf-extra").appendChild(pre); }
      return api("/api/naechster");
    }).then(function (n) {
      Z.naechster = n;
      $("zf-weiter").disabled = false;
      $("zf-weiter").textContent = n.schritt === "fertig" ? "Weiter: Abschluss" : "Weiter: " + n.name;
    }).catch(function (f) { fehlerZeigen(f); $("zf-weiter").disabled = false; $("zf-weiter").textContent = "Weiter"; });
  }

  function quellenTabelle(quellen) {
    var box = $("zf-extra");
    box.appendChild(el("h3", "Je Quellordner"));
    var t = el("table", null, "tabelle klein");
    var kopf = el("tr");
    ["Quellordner", "Fotos", "RAW", "Videos", "Begleitdateien", "Andere", "Datenmenge"].forEach(function (k) { kopf.appendChild(el("th", k)); });
    t.appendChild(kopf);
    quellen.forEach(function (q) {
      var tr = el("tr");
      tr.appendChild(el("td", q.wurzel));
      [q.foto, q.raw, q.video, q.sidecar, q.sonstiges].forEach(function (n) { tr.appendChild(el("td", String(n), "zahl")); });
      tr.appendChild(el("td", q.groesse, "zahl"));
      t.appendChild(tr);
    });
    box.appendChild(t);
  }

  function jahreTabelle(jahre) {
    if (!jahre.length) return;
    var box = $("zf-extra");
    box.appendChild(el("h3", "Dateien je Jahr"));
    var t = el("table", null, "tabelle klein");
    jahre.forEach(function (j) {
      var tr = el("tr");
      tr.appendChild(el("td", j.jahr));
      tr.appendChild(el("td", j.n_text, "zahl"));
      t.appendChild(tr);
    });
    box.appendChild(t);
  }

  function modelleTabelle(modelle, ohneModell) {
    var box = $("zf-extra");
    box.appendChild(el("h3", "Kameras und ihre Ordnernamen"));
    box.appendChild(el("p", "Für jede Kamera entsteht im Archiv ein eigener Ordner. Sie können den Ordnernamen hier ändern, zum Beispiel „ILCE-7CM2“ in „Sony A7C“. Nach „Weiter“ werden die betroffenen Dateien noch einmal analysiert.", "erklaerung"));
    if (!modelle.length) { box.appendChild(el("p", "Es wurde kein Kameramodell gefunden.", "erklaerung")); return; }
    var t = el("table", null, "tabelle");
    var kopf = el("tr");
    ["Kameramodell (aus den Dateien)", "Dateien", "Ordnername im Archiv"].forEach(function (k) { kopf.appendChild(el("th", k)); });
    t.appendChild(kopf);
    modelle.forEach(function (m) {
      var tr = el("tr");
      tr.appendChild(el("td", m.modell));
      tr.appendChild(el("td", m.n_text, "zahl"));
      var td = el("td");
      var inp = el("input"); inp.type = "text"; inp.className = "alias"; inp.value = m.ordner; inp.setAttribute("data-modell", m.modell); inp.setAttribute("data-alt", m.ordner);
      td.appendChild(inp); tr.appendChild(td);
      t.appendChild(tr);
    });
    box.appendChild(t);
    if (ohneModell) box.appendChild(el("p", "Dateien ohne Kameramodell: " + ohneModell + " (landen im Ordner „Unbekannt“).", "erklaerung"));
  }

  function aliaseGeaendert() {
    var neue = {};
    alle("input.alias").forEach(function (i) {
      var v = i.value.trim();
      if (v && v !== i.getAttribute("data-alt")) neue[i.getAttribute("data-modell")] = v;
    });
    return neue;
  }

  function weiter() {
    var neue = aliaseGeaendert();
    if (Z.schritt === "analyse" && Object.keys(neue).length) {
      $("zf-weiter").disabled = true;
      api("/api/aliase", { aliase: neue }).then(function (a) {
        if (a.gestartet) { meldung(a.text, true); laufZeigen(a.gestartet); } else { meldung(a.text, true); naechsterSchritt(); }
      }).catch(fehlerZeigen).then(function () { $("zf-weiter").disabled = false; });
      return;
    }
    naechsterSchritt();
  }

  function naechsterSchritt() {
    var n = Z.naechster;
    var weiterMit = function (n2) {
      if (n2.schritt === "fertig") { fertigZeigen(n2); return; }
      if (n2.schritt === "analyse" || n2.schritt === "pruefen") {
        api("/api/schritt", { schritt: n2.schritt }).then(function (a) { laufZeigen(a.gestartet); }).catch(fehlerZeigen);
        return;
      }
      if (n2.schritt === "kopieren") { kopierKarte(n2); return; }
      if (n2.schritt === "aufraeumen") { aufraeumenZeigen(n2.plan); return; }
    };
    if (n) weiterMit(n); else api("/api/naechster").then(weiterMit).catch(fehlerZeigen);
  }

  function kopierKarte(n) {
    zeige("zusammenfassung");
    var k = $("zf-karte");
    leer(k);
    k.appendChild(el("h3", "Als Nächstes: " + n.name));
    k.appendChild(el("p", n.text));
    if (n.erklaerung) k.appendChild(el("p", n.erklaerung, "erklaerung"));
    var wort = null;
    if (n.wort) {
      var zeile = el("div", null, "feldzeile");
      zeile.appendChild(el("label", "Zur Bestätigung „" + n.wort + "“ eintippen:", "bez"));
      wort = el("input"); wort.type = "text"; wort.className = "feld"; wort.setAttribute("autocomplete", "off");
      zeile.appendChild(wort); k.appendChild(zeile);
    }
    var knopf = el("button", n.verschieben ? "Jetzt verschieben" : "Jetzt kopieren", "knopf gross" + (n.verschieben ? " warn" : ""));
    knopf.onclick = function () {
      knopf.disabled = true;
      api("/api/schritt", { schritt: "kopieren", wort: wort ? wort.value : "" }).then(function (a) { laufZeigen(a.gestartet); })
        .catch(function (f) { fehlerZeigen(f); knopf.disabled = false; });
    };
    k.appendChild(knopf);
    k.classList.remove("versteckt");
    $("zf-weiter").classList.add("versteckt");
    k.scrollIntoView({ behavior: "smooth" });
    if (wort) wort.focus();
  }

  // ---------------------------------------------------------------- Fertig --
  function fertigZeigen(n) {
    zeige("fertig");
    $("fertig-text").textContent = n.text || "Alle Schritte sind erledigt.";
    var t = $("fertig-tabelle"); leer(t);
    var namen = { geprueft: "Kopiert und geprüft", quelle_geloescht: "Aus der Quelle entfernt", duplikat_bestaetigt: "Doppelte Dateien (nicht kopiert)", duplikat: "Doppelte Dateien (nicht kopiert)", verschoben: "Verschoben", fehler: "Fehler", uebersprungen: "Übersprungen", kopiert: "Kopiert, noch nicht geprüft", analysiert: "Noch nicht kopiert", gefunden: "Noch nicht analysiert" };
    Object.keys(n.zaehler || {}).forEach(function (k) {
      if (!n.zaehler[k] || !namen[k]) return;
      var tr = el("tr"); tr.appendChild(el("td", namen[k])); tr.appendChild(el("td", String(n.zaehler[k]).replace(/\B(?=(\d{3})+(?!\d))/g, "."), "zahl")); t.appendChild(tr);
    });
  }

  // ------------------------------------------------------------- Aufraeumen --
  function aufraeumenZeigen(plan) {
    var zeigen = function (p) {
      zeige("aufraeumen");
      var t = $("auf-tabelle"); leer(t);
      var kopf = el("tr");
      ["Quellordner", "Dateien mit geprüfter Kopie", "Datenmenge"].forEach(function (k) { kopf.appendChild(el("th", k)); });
      t.appendChild(kopf);
      (p.je_quelle || []).forEach(function (q) {
        var tr = el("tr");
        tr.appendChild(el("td", q.wurzel)); tr.appendChild(el("td", q.n_text, "zahl")); tr.appendChild(el("td", q.groesse, "zahl"));
        t.appendChild(tr);
      });
      if (!(p.je_quelle || []).length) {
        var tr0 = el("tr"); var td0 = el("td", "Zurzeit gibt es keine Datei, die entfernt werden dürfte."); td0.colSpan = 3; tr0.appendChild(td0); t.appendChild(tr0);
      }
      $("auf-summe").textContent = p.n ? "Insgesamt " + p.n_text + " Dateien (" + p.groesse + ")." : "";
      $("auf-wort").value = ""; $("auf-wort-ordner").value = ""; $("auf-ordner").checked = false;
      $("auf-ordner-box").classList.add("versteckt");
      Z.woerter = p.woerter;
      aufWortText();
      $("auf-wort-ordner-text").textContent = "Zur Bestätigung „" + p.woerter.ordner + "“ eintippen:";
    };
    if (plan) zeigen(plan); else api("/api/aufraeumen_plan").then(zeigen).catch(fehlerZeigen);
  }

  function aufWeise() { return alle("input[name=weise]").filter(function (r) { return r.checked; })[0].value; }
  function aufWortText() {
    if (!Z.woerter) return;
    $("auf-wort-text").textContent = "Dateien entfernen? Dann „" + Z.woerter[aufWeise()] + "“ eintippen:";
  }

  function aufraeumenStarten() {
    $("auf-los").disabled = true;
    api("/api/schritt", {
      schritt: "aufraeumen", weise: aufWeise(), wort: $("auf-wort").value,
      leere_ordner: $("auf-ordner").checked, wort_ordner: $("auf-wort-ordner").value
    }).then(function (a) { laufZeigen(a.gestartet); }).catch(fehlerZeigen).then(function () { $("auf-los").disabled = false; });
  }

  // ----------------------------------------------------------------- Listen --
  var LISTEN = {
    fehler: ["Fehler", "Dateien, bei denen etwas nicht geklappt hat – mit dem Grund. Sie werden beim nächsten Lauf erneut versucht, wenn der Grund behoben ist.", ["Datei", "Grund", "Größe"]],
    duplikate: ["Doppelte Dateien", "Dateien, die inhaltlich schon im Archiv lagen. Sie wurden nicht noch einmal kopiert; rechts steht die Datei im Archiv, die denselben Inhalt hat.", ["Datei in der Quelle", "Gleiche Datei im Archiv", "Größe"]],
    ohne_datum: ["Dateien ohne Aufnahmedatum", "Für diese Dateien war kein Aufnahmedatum zu finden. Sie werden nach dem Änderungsdatum oder in den Ordner „_Ohne_Datum“ einsortiert.", ["Datei", "Zielordner", "Größe"]]
  };

  function listeZeigen(art, seite) {
    Z.liste = { art: art, seite: seite || 1 };
    api("/api/liste?art=" + encodeURIComponent(art) + "&seite=" + Z.liste.seite).then(function (l) {
      if (Z.seite !== "liste") zeige("liste");
      var info = LISTEN[art];
      $("liste-titel").textContent = info[0] + " (" + l.gesamt_text + ")";
      $("liste-erklaerung").textContent = info[1];
      $("liste-stand").textContent = "Seite " + l.seite + " von " + l.seiten;
      $("liste-zurueck").disabled = l.seite <= 1;
      $("liste-vor").disabled = l.seite >= l.seiten;
      var t = $("liste-tabelle"); leer(t);
      var kopf = el("tr");
      info[2].forEach(function (k) { kopf.appendChild(el("th", k)); });
      t.appendChild(kopf);
      l.zeilen.forEach(function (z) {
        var tr = el("tr");
        tr.appendChild(el("td", z.quellpfad));
        tr.appendChild(el("td", art === "fehler" ? z.grund : art === "duplikate" ? z.partner : z.zielpfad));
        tr.appendChild(el("td", z.groesse, "zahl"));
        t.appendChild(tr);
      });
      if (!l.zeilen.length) { var tr0 = el("tr"); var td0 = el("td", "Keine Einträge."); td0.colSpan = 3; tr0.appendChild(td0); t.appendChild(tr0); }
      Z.liste.seite = l.seite;
    }).catch(fehlerZeigen);
  }

  // ------------------------------------------------------------------ Start --
  function laden() {
    api("/api/zustand").then(function (z) {
      startseiteFuellen(z);
      var l = z.lauf || {};
      if (l.aktiv || (l.zustand && !ENDE[l.zustand] && l.zustand !== "")) laufZeigen();
      else zeige("start");
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
    alle("input[name=modus]").forEach(function (r) { r.addEventListener("change", einstellungenSenden); });
    $("profil").addEventListener("change", function () { Z.profilGewaehlt = true; profilText(); einstellungenSenden(); });
    $("los").onclick = function () { los(false); };
    $("weitermachen").onclick = function () { Z.naechster = null; naechsterSchritt(); };
    alle("[data-liste]").forEach(function (k) { k.onclick = function () { listeZeigen(k.getAttribute("data-liste"), 1); }; });
    $("bericht").onclick = $("fertig-bericht").onclick = function () {
      api("/api/bericht", {}).then(function (a) { meldung(a.text, true); }).catch(fehlerZeigen);
    };
    $("einstellungen").onclick = function () {
      api("/api/einstellungen_oeffnen", {}).then(function (a) { meldung(a.text, true); }).catch(fehlerZeigen);
    };
    $("zum-aufraeumen").onclick = $("fertig-aufraeumen").onclick = function () { aufraeumenZeigen(null); };
    $("pause").onclick = function () { steuern("pause"); };
    $("fortsetzen").onclick = function () { steuern("weiter"); };
    $("abbrechen").onclick = function () {
      frage("Diesen Schritt abbrechen? Das Bisherige bleibt gespeichert; der nächste Lauf macht dort weiter.").then(function (ja) { if (ja) steuern("abbrechen"); });
    };
    $("sofort").onclick = function () {
      frage("Der Schritt reagiert nicht auf „Abbrechen“. Sofort beenden? Angefangene Kopien räumt der nächste Lauf auf.").then(function (ja) { if (ja) steuern("sofort"); });
    };
    $("zf-weiter").onclick = weiter;
    $("zf-fehler").onclick = function () { listeZeigen("fehler", 1); };
    $("zf-duplikate").onclick = function () { listeZeigen("duplikate", 1); };
    $("zf-start").onclick = $("fertig-start").onclick = function () { laden(); };
    alle("input[name=weise]").forEach(function (r) { r.addEventListener("change", aufWortText); });
    $("auf-ordner").addEventListener("change", function () { $("auf-ordner-box").classList.toggle("versteckt", !$("auf-ordner").checked); });
    $("auf-los").onclick = aufraeumenStarten;
    $("auf-nicht").onclick = function () { api("/api/naechster").then(function (n) { fertigZeigen({ text: "Nichts gelöscht. " + (n.phase || ""), zaehler: n.zaehler }); }).catch(fehlerZeigen); };
    $("liste-zurueck").onclick = function () { listeZeigen(Z.liste.art, Z.liste.seite - 1); };
    $("liste-vor").onclick = function () { listeZeigen(Z.liste.art, Z.liste.seite + 1); };
    $("liste-schliessen").onclick = function () { var z = Z.vorher === "liste" ? "start" : Z.vorher; if (z === "start") laden(); else zeige(z); };
  }

  document.addEventListener("DOMContentLoaded", function () { verdrahten(); laden(); });
})();
