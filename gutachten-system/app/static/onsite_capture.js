/*
 * Schritt 5 - Vor-Ort-Erfassung (OnSiteCapture)
 * Mobile-first, offline-faehig. Daten liegen lokal in IndexedDB und werden
 * optional mit dem Projekt-Backend synchronisiert. Dieser Schritt sammelt nur
 * strukturierte Vor-Ort-Daten - keine Laborauswertung, keine Endtabelle.
 */
(function () {
  "use strict";

  // ----- Konstanten / Auswahllisten -------------------------------------
  const COMPONENT_TYPES = ["Saeule", "Wandscheibe / WS", "Decke", "Boden", "Sonstiges"];
  const NOTE_TYPES = [
    "keiner",
    "Eisen getroffen",
    "Bewehrung getroffen",
    "Wert nicht vorhanden",
    "Position unklar",
    "Hoehe nicht vorhanden",
    "Sonstiges",
  ];
  const PHOTO_TYPES = [
    "Positionsbild",
    "Bohrloch / Tiefenmessung",
    "Karbonatisierungsbild",
    "Schadensbild",
    "Sonstiges",
  ];
  const CARBONATION_VALUES = ["", "an Bewehrung", "nicht bestimmbar", "-"];
  const NOTE_REQUIRES_COMMENT = new Set(["Eisen getroffen", "Bewehrung getroffen"]);
  const SAMPLE_NUMBER_RE = /^P\d{2,}$/;

  // ----- IndexedDB Schicht ----------------------------------------------
  const DB_NAME = "onsite_capture_db";
  const DB_VERSION = 1;
  const STORES = ["locations", "samples", "photos"];
  let dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        const db = req.result;
        if (!db.objectStoreNames.contains("locations")) {
          const s = db.createObjectStore("locations", { keyPath: "id" });
          s.createIndex("projectId", "projectId", { unique: false });
        }
        if (!db.objectStoreNames.contains("samples")) {
          const s = db.createObjectStore("samples", { keyPath: "id" });
          s.createIndex("projectId", "projectId", { unique: false });
          s.createIndex("samplingLocationId", "samplingLocationId", { unique: false });
        }
        if (!db.objectStoreNames.contains("photos")) {
          const s = db.createObjectStore("photos", { keyPath: "id" });
          s.createIndex("projectId", "projectId", { unique: false });
          s.createIndex("samplingLocationId", "samplingLocationId", { unique: false });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
    return dbPromise;
  }

  async function idbGetAllByIndex(store, index, value) {
    const db = await openDb();
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(store, "readonly");
      const req = tx.objectStore(store).index(index).getAll(value);
      req.onsuccess = function () { resolve(req.result || []); };
      req.onerror = function () { reject(req.error); };
    });
  }

  async function idbPut(store, obj) {
    const db = await openDb();
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(store, "readwrite");
      tx.objectStore(store).put(obj);
      tx.oncomplete = function () { resolve(obj); };
      tx.onerror = function () { reject(tx.error); };
    });
  }

  async function idbDelete(store, key) {
    const db = await openDb();
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(store, "readwrite");
      tx.objectStore(store).delete(key);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  }

  // ----- Hilfen ----------------------------------------------------------
  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "id-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }
  function nowIso() { return new Date().toISOString(); }
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function pad2(n) { return String(n).padStart(2, "0"); }

  function nextLocationNumber(locations) {
    let max = 0;
    locations.forEach(function (loc) {
      const m = /BS\s*0*(\d+)/i.exec(loc.number || "");
      if (m) max = Math.max(max, parseInt(m[1], 10));
    });
    return "BS" + pad2(max + 1);
  }
  function nextSampleNumber(samples) {
    let max = 0;
    samples.forEach(function (s) {
      const m = /P\s*0*(\d+)/i.exec(s.sampleNumber || "");
      if (m) max = Math.max(max, parseInt(m[1], 10));
    });
    return "P" + pad2(max + 1);
  }

  // ----- App State -------------------------------------------------------
  const root = document.getElementById("onsite-root");
  const body = document.body;
  const PROJECT_ID = (body.getAttribute("data-project-id") || "").trim();
  const PROJECT_NAME = (body.getAttribute("data-project-name") || "").trim();
  const SYNC_URL = (body.getAttribute("data-sync-url") || "").trim();
  const BACK_URL = (body.getAttribute("data-back-url") || "/prototype/vor-ort").trim();

  const state = {
    view: "list", // "list" | "location"
    currentLocationId: null,
    locations: [],
    samples: [],
    photos: [],
    busy: false,
  };
  let objectUrls = [];

  function samplesForLocation(locId) {
    return state.samples
      .filter(function (s) { return s.samplingLocationId === locId; })
      .sort(function (a, b) { return (a.sampleNumber || "").localeCompare(b.sampleNumber || ""); });
  }
  function photosForLocation(locId) {
    return state.photos.filter(function (p) { return p.samplingLocationId === locId; });
  }
  function locationById(id) {
    return state.locations.find(function (l) { return l.id === id; }) || null;
  }

  // ----- Validierung -----------------------------------------------------
  function duplicateSampleNumbers() {
    const seen = {};
    const dups = new Set();
    state.samples.forEach(function (s) {
      const key = (s.sampleNumber || "").trim().toUpperCase();
      if (!key) return;
      if (seen[key]) dups.add(key);
      seen[key] = true;
    });
    return dups;
  }

  function validateLocation(loc) {
    const warnings = [];
    const samples = samplesForLocation(loc.id);
    const photos = photosForLocation(loc.id);
    const dups = duplicateSampleNumbers();
    const hasPositionPhoto = photos.some(function (p) { return p.type === "Positionsbild"; });
    const hasCarbPhoto = photos.some(function (p) { return p.type === "Karbonatisierungsbild"; });
    const hasCarbValue = !!((loc.carbonationDepth && String(loc.carbonationDepth).trim()) ||
      (loc.carbonationSpecialValue && loc.carbonationSpecialValue.trim()));

    if (!loc.position || !loc.position.trim()) warnings.push("Beprobungsstelle ohne Position.");
    if (!hasPositionPhoto) warnings.push("Kein Positionsbild vorhanden.");
    if (hasCarbValue && !hasCarbPhoto) warnings.push("Karbonatisierungswert ohne Karbonatisierungsbild.");
    if (hasCarbPhoto && !hasCarbValue) warnings.push("Karbonatisierungsbild ohne Karbonatisierungswert.");
    if (samples.length === 0) warnings.push("Noch keine Probe erfasst.");

    samples.forEach(function (s) {
      const label = s.sampleNumber || "(ohne Nr.)";
      if (!s.drillingDepthMm || !String(s.drillingDepthMm).trim()) {
        warnings.push("Probe " + label + " ohne Bohrtiefe.");
      }
      const height = (s.heightCm == null ? "" : String(s.heightCm)).trim();
      if (!height && s.noteType !== "Hoehe nicht vorhanden") {
        warnings.push("Probe " + label + " ohne Hoehe (oder bewusst '-').");
      }
      if (NOTE_REQUIRES_COMMENT.has(s.noteType) && !(s.comment && s.comment.trim())) {
        warnings.push("Probe " + label + ": '" + s.noteType + "' ohne Kommentar.");
      }
      const num = (s.sampleNumber || "").trim().toUpperCase();
      if (num && !SAMPLE_NUMBER_RE.test(num)) {
        warnings.push("Probe " + label + ": ungueltiges Probennummernformat (erwartet P01, P02 ...).");
      }
      if (num && dups.has(num)) {
        warnings.push("Doppelte Proben-Nr. " + label + ".");
      }
    });
    return warnings;
  }

  function statusForLocation(loc) {
    if (loc.reviewed) return "geprueft";
    const samples = samplesForLocation(loc.id);
    const photos = photosForLocation(loc.id);
    const warnings = validateLocation(loc);
    const empty = samples.length === 0 && photos.length === 0 && !(loc.position && loc.position.trim());
    if (empty) return "offen";
    return warnings.length ? "unvollstaendig" : "vollstaendig";
  }

  function allWarnings() {
    const list = [];
    state.locations.forEach(function (loc) {
      validateLocation(loc).forEach(function (msg) {
        list.push({ samplingLocationId: loc.id, number: loc.number, message: msg });
      });
    });
    return list;
  }

  // ----- Persistenz ------------------------------------------------------
  async function loadProjectData() {
    const [locations, samples, photos] = await Promise.all([
      idbGetAllByIndex("locations", "projectId", PROJECT_ID),
      idbGetAllByIndex("samples", "projectId", PROJECT_ID),
      idbGetAllByIndex("photos", "projectId", PROJECT_ID),
    ]);
    locations.sort(function (a, b) { return (a.number || "").localeCompare(b.number || ""); });
    state.locations = locations;
    state.samples = samples;
    state.photos = photos;
  }

  async function persistLocation(loc) {
    loc.updatedAt = nowIso();
    await idbPut("locations", loc);
  }
  async function persistSample(sample) {
    sample.updatedAt = nowIso();
    await idbPut("samples", sample);
  }
  async function persistPhoto(photo) {
    photo.updatedAt = nowIso();
    await idbPut("photos", photo);
  }

  function newLocation() {
    return {
      id: uid(),
      projectId: PROJECT_ID,
      number: nextLocationNumber(state.locations),
      position: "",
      positionUncertain: false,
      componentType: COMPONENT_TYPES[0],
      comment: "",
      carbonationDepth: "",
      carbonationSpecialValue: "",
      carbonationComment: "",
      reviewed: false,
      status: "offen",
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
  }
  function newSample(locId) {
    return {
      id: uid(),
      projectId: PROJECT_ID,
      samplingLocationId: locId,
      sampleNumber: nextSampleNumber(state.samples),
      drillingDepthMm: "",
      heightCm: "",
      noteType: "keiner",
      comment: "",
      status: "automatisch erstellt",
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
  }

  // ----- Foto-Handling ---------------------------------------------------
  function fileToDataUrl(file) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsDataURL(file);
    });
  }

  async function addPhotos(locId, fileList, defaultType) {
    const loc = locationById(locId);
    const files = Array.prototype.slice.call(fileList || []);
    for (const file of files) {
      if (!file || !file.type || file.type.indexOf("image/") !== 0) continue;
      const photo = {
        id: uid(),
        projectId: PROJECT_ID,
        samplingLocationId: locId,
        samplingLocationNumber: loc ? loc.number : "",
        sampleId: null,
        type: defaultType || "Positionsbild",
        comment: "",
        mime: file.type,
        blob: file, // Blob bleibt lokal in IndexedDB erhalten, bis synchronisiert
        createdAt: nowIso(),
        updatedAt: nowIso(),
      };
      await persistPhoto(photo);
      state.photos.push(photo);
    }
  }

  function previewUrl(photo) {
    if (!photo.blob) return "";
    const url = URL.createObjectURL(photo.blob);
    objectUrls.push(url);
    return url;
  }
  function clearObjectUrls() {
    objectUrls.forEach(function (u) { URL.revokeObjectURL(u); });
    objectUrls = [];
  }

  // ----- Export / Sync ---------------------------------------------------
  function blobToDataUrl(blob) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsDataURL(blob);
    });
  }

  function summaryCounts() {
    const ready = state.locations.filter(function (l) {
      const st = statusForLocation(l);
      return st === "geprueft" || st === "vollstaendig";
    }).length;
    return {
      locations: state.locations.length,
      samples: state.samples.length,
      photos: state.photos.length,
      locationsReady: ready,
      warnings: allWarnings().length,
    };
  }

  async function buildExport(includePhotoData) {
    const photos = [];
    for (const p of state.photos) {
      const entry = {
        id: p.id,
        projectId: p.projectId,
        samplingLocationId: p.samplingLocationId,
        samplingLocationNumber: p.samplingLocationNumber || "",
        sampleId: p.sampleId || null,
        type: p.type,
        comment: p.comment || "",
        mime: p.mime || (p.blob && p.blob.type) || "",
        createdAt: p.createdAt,
        updatedAt: p.updatedAt,
      };
      if (includePhotoData && p.blob) {
        try { entry.dataUrl = await blobToDataUrl(p.blob); } catch (e) { entry.dataUrl = null; }
      }
      photos.push(entry);
    }
    return {
      schema: "onsite_capture.v1",
      exportedAt: nowIso(),
      projectId: PROJECT_ID,
      projectName: PROJECT_NAME,
      samplingLocations: state.locations.map(function (l) {
        return {
          id: l.id, projectId: l.projectId, number: l.number, position: l.position,
          positionUncertain: !!l.positionUncertain, componentType: l.componentType,
          comment: l.comment || "", carbonationDepth: l.carbonationDepth || "",
          carbonationSpecialValue: l.carbonationSpecialValue || "",
          carbonationComment: l.carbonationComment || "",
          status: statusForLocation(l), reviewed: !!l.reviewed,
          createdAt: l.createdAt, updatedAt: l.updatedAt,
        };
      }),
      samples: state.samples.map(function (s) {
        return {
          id: s.id, projectId: s.projectId, samplingLocationId: s.samplingLocationId,
          sampleNumber: s.sampleNumber, drillingDepthMm: s.drillingDepthMm,
          heightCm: (s.heightCm == null || s.heightCm === "") ? "-" : s.heightCm,
          noteType: s.noteType, comment: s.comment || "", status: s.status,
          createdAt: s.createdAt, updatedAt: s.updatedAt,
        };
      }),
      photos: photos,
      validationWarnings: allWarnings(),
      summary: summaryCounts(),
    };
  }

  async function downloadExport() {
    const data = await buildExport(true);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "vor_ort_erfassung_" + (PROJECT_ID || "projekt") + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast("JSON-Export erstellt.");
  }

  async function syncToProject() {
    if (!SYNC_URL) { toast("Keine Sync-Adresse - bitte Projekt waehlen."); return; }
    try {
      setBusy(true);
      const data = await buildExport(true);
      const res = await fetch(SYNC_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const result = await res.json();
      localStorage.setItem("onsite_last_sync_" + PROJECT_ID, nowIso());
      toast("Mit Projekt synchronisiert (" + (result.counts ? result.counts.photos : 0) + " Fotos).");
    } catch (e) {
      toast("Sync fehlgeschlagen - Daten bleiben lokal gespeichert.");
    } finally {
      setBusy(false);
      render();
    }
  }

  function lastSyncLabel() {
    const raw = localStorage.getItem("onsite_last_sync_" + PROJECT_ID);
    if (!raw) return "noch nicht synchronisiert";
    const d = new Date(raw);
    return "zuletzt synchronisiert " + d.toLocaleString("de-AT");
  }

  // ----- UI Bausteine ----------------------------------------------------
  function statusChip(status) {
    const labels = {
      offen: "offen", unvollstaendig: "unvollstaendig",
      vollstaendig: "vollstaendig", geprueft: "geprueft",
    };
    return '<span class="os-chip os-status-' + status + '">' + (labels[status] || status) + "</span>";
  }

  function selectOptions(options, current) {
    return options.map(function (opt) {
      const label = opt === "" ? "(leer)" : opt;
      return '<option value="' + esc(opt) + '"' + (opt === current ? " selected" : "") + ">" + esc(label) + "</option>";
    }).join("");
  }

  function toast(message) {
    let el = document.getElementById("os-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "os-toast";
      el.className = "os-toast";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("visible");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.remove("visible"); }, 2600);
  }

  function setBusy(v) { state.busy = v; body.classList.toggle("os-busy", v); }

  // ----- Render: kein Projekt -------------------------------------------
  function renderNoProject() {
    root.innerHTML =
      '<div class="os-app">' +
      '<header class="os-appbar"><strong>Vor-Ort-Erfassung</strong></header>' +
      '<div class="os-empty">' +
      "<h2>Kein Projekt gewaehlt</h2>" +
      "<p>Bitte zuerst ein Projekt oeffnen, danach die Vor-Ort-Erfassung starten.</p>" +
      '<a class="os-btn os-btn-primary" href="/prototype">Zur Projektauswahl</a>' +
      "</div></div>";
  }

  // ----- Render: Liste ---------------------------------------------------
  function renderList() {
    const counts = summaryCounts();
    const cards = state.locations.map(function (loc) {
      const samples = samplesForLocation(loc.id);
      const photos = photosForLocation(loc.id);
      const sampleNos = samples.map(function (s) { return esc(s.sampleNumber); }).join("/") || "&ndash;";
      const depths = samples.map(function (s) { return esc(s.drillingDepthMm || "?"); }).join(" / ") || "&ndash;";
      const heights = samples.map(function (s) {
        return esc((s.heightCm == null || s.heightCm === "") ? "-" : s.heightCm);
      }).join(" / ") || "&ndash;";
      const hasPos = photos.some(function (p) { return p.type === "Positionsbild"; });
      const hasCarb = photos.some(function (p) { return p.type === "Karbonatisierungsbild"; });
      return (
        '<button class="os-card" data-open="' + loc.id + '">' +
        '<div class="os-card-top"><strong>' + esc(loc.number) + "</strong>" + statusChip(statusForLocation(loc)) + "</div>" +
        '<div class="os-card-pos">' + (loc.position ? esc(loc.position) : '<em>Position offen</em>') + "</div>" +
        '<div class="os-card-meta">' +
        "<span>" + esc(loc.componentType) + "</span>" +
        "<span>Proben: " + sampleNos + "</span>" +
        "<span>Bohrtiefe: " + depths + " mm</span>" +
        "<span>Hoehe: " + heights + " cm</span>" +
        "</div>" +
        '<div class="os-card-flags">' +
        "<span>" + photos.length + " Bilder</span>" +
        '<span class="' + (hasPos ? "ok" : "miss") + '">Positionsbild ' + (hasPos ? "&#10003;" : "&#10007;") + "</span>" +
        '<span class="' + (hasCarb ? "ok" : "miss") + '">Karbonat.-Bild ' + (hasCarb ? "&#10003;" : "&#10007;") + "</span>" +
        "</div>" +
        "</button>"
      );
    }).join("");

    root.innerHTML =
      '<div class="os-app">' +
      '<header class="os-appbar">' +
      '<a class="os-back" href="' + esc(BACK_URL) + '">&#8592;</a>' +
      "<div><strong>Vor-Ort-Erfassung</strong><small>" + esc(PROJECT_NAME || PROJECT_ID) + "</small></div>" +
      "</header>" +
      '<div class="os-summary">' +
      '<span class="os-chip">' + counts.locations + " Stellen</span>" +
      '<span class="os-chip">' + counts.samples + " Proben</span>" +
      '<span class="os-chip">' + counts.photos + " Fotos</span>" +
      '<span class="os-chip ' + (counts.warnings ? "warn" : "ok") + '">' + counts.warnings + " Warnungen</span>" +
      "</div>" +
      '<button class="os-btn os-btn-primary os-btn-block" data-new-location>+ Neue Beprobungsstelle</button>' +
      '<div class="os-list">' + (cards || '<p class="os-muted">Noch keine Beprobungsstelle erfasst.</p>') + "</div>" +
      '<div class="os-footer">' +
      '<button class="os-btn" data-export>JSON exportieren</button>' +
      '<button class="os-btn" data-sync ' + (SYNC_URL ? "" : "disabled") + ">Mit Projekt synchronisieren</button>" +
      '<div class="os-sync-label">' + esc(lastSyncLabel()) + "</div>" +
      "</div>" +
      "</div>";

    root.querySelector("[data-new-location]").addEventListener("click", onNewLocation);
    root.querySelectorAll("[data-open]").forEach(function (btn) {
      btn.addEventListener("click", function () { openLocation(btn.getAttribute("data-open")); });
    });
    root.querySelector("[data-export]").addEventListener("click", downloadExport);
    const syncBtn = root.querySelector("[data-sync]");
    if (syncBtn && SYNC_URL) syncBtn.addEventListener("click", syncToProject);
  }

  // ----- Render: Beprobungsstelle ---------------------------------------
  function renderLocation() {
    const loc = locationById(state.currentLocationId);
    if (!loc) { state.view = "list"; return renderList(); }
    const samples = samplesForLocation(loc.id);
    const photos = photosForLocation(loc.id);
    const warnings = validateLocation(loc);

    const sampleBlocks = samples.map(function (s) {
      return (
        '<div class="os-subcard" data-sample="' + s.id + '">' +
        '<div class="os-subcard-head"><strong>' + esc(s.sampleNumber) + "</strong>" +
        '<button class="os-icon-btn" data-del-sample="' + s.id + '" title="Probe loeschen">&#10007;</button></div>' +
        '<label>Proben-Nr.<input data-f="sampleNumber" value="' + esc(s.sampleNumber) + '" inputmode="text"></label>' +
        '<div class="os-grid2">' +
        '<label>Bohrtiefe [mm]<input data-f="drillingDepthMm" value="' + esc(s.drillingDepthMm) + '" inputmode="numeric" placeholder="z. B. 20"></label>' +
        '<label>Hoehe [cm]<input data-f="heightCm" value="' + esc(s.heightCm) + '" inputmode="text" placeholder="z. B. 30 oder -"></label>' +
        "</div>" +
        '<label>Hinweis / Sonderfall<select data-f="noteType">' + selectOptions(NOTE_TYPES, s.noteType) + "</select></label>" +
        '<label>Kommentar<input data-f="comment" value="' + esc(s.comment) + '"></label>' +
        '<div class="os-mini">Status: ' + esc(s.status) + "</div>" +
        "</div>"
      );
    }).join("");

    const photoBlocks = photos.map(function (p) {
      const sampleOpts = '<option value="">(keiner Probe)</option>' + samples.map(function (s) {
        return '<option value="' + esc(s.id) + '"' + (p.sampleId === s.id ? " selected" : "") + ">" + esc(s.sampleNumber) + "</option>";
      }).join("");
      return (
        '<div class="os-photo" data-photo="' + p.id + '">' +
        '<img src="' + previewUrl(p) + '" alt="Foto">' +
        '<label class="os-photo-type"><select data-pf="type">' + selectOptions(PHOTO_TYPES, p.type) + "</select></label>" +
        '<label class="os-photo-sample"><select data-pf="sampleId">' + sampleOpts + "</select></label>" +
        '<input class="os-photo-comment" data-pf="comment" value="' + esc(p.comment) + '" placeholder="Bildkommentar">' +
        '<div class="os-photo-actions">' +
        '<label class="os-textlink">Ersetzen<input type="file" accept="image/*" data-replace="' + p.id + '" hidden></label>' +
        '<button class="os-textlink danger" data-del-photo="' + p.id + '">Loeschen</button>' +
        "</div></div>"
      );
    }).join("");

    root.innerHTML =
      '<div class="os-app">' +
      '<header class="os-appbar">' +
      '<button class="os-back" data-to-list>&#8592;</button>' +
      "<div><strong>" + esc(loc.number) + "</strong><small>" + esc(PROJECT_NAME || PROJECT_ID) + "</small></div>" +
      statusChip(statusForLocation(loc)) +
      "</header>" +

      '<section class="os-section"><h2>Beprobungsstelle</h2>' +
      '<label>BS-Nummer<input data-l="number" value="' + esc(loc.number) + '"></label>' +
      '<label>Position<input data-l="position" value="' + esc(loc.position) + '" placeholder="z. B. Saeule P118"></label>' +
      '<label class="os-check"><input type="checkbox" data-l="positionUncertain"' + (loc.positionUncertain ? " checked" : "") + "> Position unklar (spaeter pruefen)</label>" +
      '<label>Bauteiltyp<select data-l="componentType">' + selectOptions(COMPONENT_TYPES, loc.componentType) + "</select></label>" +
      '<label>Kommentar<input data-l="comment" value="' + esc(loc.comment) + '"></label>' +
      "</section>" +

      '<section class="os-section"><div class="os-section-head"><h2>Proben</h2>' +
      '<button class="os-btn os-btn-small" data-add-sample>+ Probe</button></div>' +
      (sampleBlocks || '<p class="os-muted">Noch keine Probe. Standard sind zwei Tiefenstufen.</p>') +
      "</section>" +

      '<section class="os-section"><div class="os-section-head"><h2>Fotos</h2></div>' +
      '<div class="os-photo-buttons">' +
      '<label class="os-btn os-btn-primary">Foto aufnehmen<input type="file" accept="image/*" capture="environment" data-capture hidden></label>' +
      '<label class="os-btn">Foto hinzufuegen<input type="file" accept="image/*" multiple data-gallery hidden></label>' +
      "</div>" +
      '<div class="os-photo-grid">' + (photoBlocks || '<p class="os-muted">Noch keine Fotos. Mindestens ein Positionsbild vorsehen.</p>') + "</div>" +
      "</section>" +

      '<section class="os-section"><h2>Karbonatisierung (optional)</h2>' +
      '<p class="os-muted small">Gilt fuer die ganze Beprobungsstelle. Keine KI-Bewertung in diesem Schritt.</p>' +
      '<div class="os-grid2">' +
      '<label>Tiefe [mm]<input data-l="carbonationDepth" value="' + esc(loc.carbonationDepth) + '" inputmode="numeric"></label>' +
      '<label>Sonderwert<select data-l="carbonationSpecialValue">' + selectOptions(CARBONATION_VALUES, loc.carbonationSpecialValue) + "</select></label>" +
      "</div>" +
      '<label>Kommentar<input data-l="carbonationComment" value="' + esc(loc.carbonationComment) + '"></label>' +
      "</section>" +

      (warnings.length
        ? '<section class="os-section os-warnings"><h2>Hinweise (' + warnings.length + ")</h2><ul>" +
          warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul></section>"
        : '<section class="os-section os-ok">Keine offenen Hinweise.</section>') +

      '<div class="os-actions-bar">' +
      '<button class="os-btn" data-save>Speichern</button>' +
      '<button class="os-btn ' + (loc.reviewed ? "os-btn-muted" : "os-btn-primary") + '" data-review>' +
      (loc.reviewed ? "Pruefung aufheben" : "Als geprueft markieren") + "</button>" +
      '<button class="os-btn" data-next>Naechste Beprobungsstelle</button>' +
      "</div>" +
      "</div>";

    attachLocationEvents(loc);
  }

  function attachLocationEvents(loc) {
    root.querySelector("[data-to-list]").addEventListener("click", goToList);

    // Beprobungsstellen-Felder
    root.querySelectorAll("[data-l]").forEach(function (input) {
      const field = input.getAttribute("data-l");
      const evt = (input.tagName === "SELECT" || input.type === "checkbox") ? "change" : "change";
      input.addEventListener(evt, function () {
        loc[field] = input.type === "checkbox" ? input.checked : input.value;
        persistLocation(loc);
        if (input.type === "checkbox" || input.tagName === "SELECT") render();
      });
    });

    // Proben hinzufuegen
    root.querySelector("[data-add-sample]").addEventListener("click", async function () {
      const s = newSample(loc.id);
      await persistSample(s);
      state.samples.push(s);
      render();
    });

    // Probenfelder
    root.querySelectorAll("[data-sample]").forEach(function (card) {
      const sampleId = card.getAttribute("data-sample");
      const sample = state.samples.find(function (x) { return x.id === sampleId; });
      if (!sample) return;
      card.querySelectorAll("[data-f]").forEach(function (input) {
        input.addEventListener("change", function () {
          sample[input.getAttribute("data-f")] = input.value;
          if (sample.status === "automatisch erstellt") sample.status = "manuell bearbeitet";
          if (loc.reviewed) { loc.reviewed = false; persistLocation(loc); }
          persistSample(sample);
          if (input.tagName === "SELECT") render();
        });
      });
      const del = card.querySelector("[data-del-sample]");
      del.addEventListener("click", async function () {
        if (!confirm("Probe " + (sample.sampleNumber || "") + " loeschen?")) return;
        await idbDelete("samples", sample.id);
        state.samples = state.samples.filter(function (x) { return x.id !== sample.id; });
        render();
      });
    });

    // Foto-Aufnahme / Galerie
    const capture = root.querySelector("[data-capture]");
    capture.addEventListener("change", async function () {
      await addPhotos(loc.id, capture.files, "Positionsbild");
      render();
    });
    const gallery = root.querySelector("[data-gallery]");
    gallery.addEventListener("change", async function () {
      await addPhotos(loc.id, gallery.files, "Sonstiges");
      render();
    });

    // Fotofelder + Loeschen + Ersetzen
    root.querySelectorAll("[data-photo]").forEach(function (card) {
      const photoId = card.getAttribute("data-photo");
      const photo = state.photos.find(function (x) { return x.id === photoId; });
      if (!photo) return;
      card.querySelectorAll("[data-pf]").forEach(function (input) {
        input.addEventListener("change", function () {
          const f = input.getAttribute("data-pf");
          photo[f] = f === "sampleId" ? (input.value || null) : input.value;
          persistPhoto(photo);
          if (input.tagName === "SELECT") render();
        });
      });
      const delPhoto = card.querySelector("[data-del-photo]");
      delPhoto.addEventListener("click", async function () {
        if (!confirm("Foto loeschen?")) return;
        await idbDelete("photos", photo.id);
        state.photos = state.photos.filter(function (x) { return x.id !== photo.id; });
        render();
      });
      const replace = card.querySelector("[data-replace]");
      replace.addEventListener("change", async function () {
        const file = replace.files && replace.files[0];
        if (file && file.type.indexOf("image/") === 0) {
          photo.blob = file;
          photo.mime = file.type;
          await persistPhoto(photo);
          render();
        }
      });
    });

    // Aktionen
    root.querySelector("[data-save]").addEventListener("click", function () {
      toast("Lokal gespeichert.");
      goToList();
    });
    root.querySelector("[data-review]").addEventListener("click", async function () {
      loc.reviewed = !loc.reviewed;
      if (loc.reviewed) {
        samplesForLocation(loc.id).forEach(function (s) { s.status = "geprueft"; persistSample(s); });
      }
      await persistLocation(loc);
      render();
    });
    root.querySelector("[data-next]").addEventListener("click", onNewLocation);
  }

  // ----- Aktionen --------------------------------------------------------
  async function onNewLocation() {
    const loc = newLocation();
    await persistLocation(loc);
    state.locations.push(loc);
    state.locations.sort(function (a, b) { return (a.number || "").localeCompare(b.number || ""); });
    // Direkt zwei Standardproben anlegen (zwei Tiefenstufen).
    for (let i = 0; i < 2; i++) {
      const s = newSample(loc.id);
      await persistSample(s);
      state.samples.push(s);
    }
    openLocation(loc.id);
  }
  function openLocation(id) {
    state.currentLocationId = id;
    state.view = "location";
    render();
    window.scrollTo(0, 0);
  }
  function goToList() {
    state.view = "list";
    state.currentLocationId = null;
    render();
    window.scrollTo(0, 0);
  }

  // ----- Render-Dispatcher ----------------------------------------------
  function render() {
    clearObjectUrls();
    if (!PROJECT_ID) return renderNoProject();
    if (state.view === "location") return renderLocation();
    return renderList();
  }

  // ----- Start -----------------------------------------------------------
  async function init() {
    if (!PROJECT_ID) { renderNoProject(); return; }
    try {
      await loadProjectData();
    } catch (e) {
      root.innerHTML = '<div class="os-app"><div class="os-empty"><h2>Speicher nicht verfuegbar</h2>' +
        "<p>IndexedDB konnte nicht geoeffnet werden. Bitte privaten Modus deaktivieren.</p></div></div>";
      return;
    }
    render();
  }

  init();
})();
