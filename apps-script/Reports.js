// =====================================================================
// DRIVER REPORTS (the app's "outbox"), fleet places, config, dash-warning ack
//
// The app posts a report in steps and CHECKS each one (it can't trust the
// normal no-cors sync, which never sees a reply):
//   POST {type:'msg',   rid, kind, urgent, to:[roles], subject, text, ts, data}
//        -> stored on the "Reports" tab and emailed straight away
//   GET  ?status=<rid>   -> {status:'success', found, emailed, photos, finalEmailed, state, ackAt, ackBy}
//   POST {type:'photo', rid, name, mime, b64}  -> saved to a Drive folder for that report
//   POST {type:'final', rid, again, text}      -> one more email, photos attached
//   POST {type:'place', key, place}            -> fleet-added place ("Places" tab)
//   GET  ?places=1       -> {status:'success', places:{key: place}}   (deleted ones stay, flagged)
//   GET  ?config=1       -> {status:'success', company, opsPhone}
//   GET  ?ack=<rid>      -> the "I've got it" link in a dash-warning email
//
// Who is emailed comes from CONFIG.EMAIL in Config.js (not in git).
// A dash warning nobody acknowledges within CONFIG.ESCALATE_MINUTES goes to
// the mechanic; that is checked when the driver's phone asks for ?status=.
// =====================================================================

var REPORT_HEADERS_ = [
  "rid", "kind", "receivedAt", "urgent", "to", "subject", "text", "data",
  "emailed", "photos", "folderId", "finalEmailed", "finalPhotos",
  "state", "ackAt", "ackBy", "escalatedAt", "error"
];
var SHEET_CELL_MAX_ = 45000; // Google Sheets refuses a cell over 50,000 characters

function openSheet_() {
  return SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(CONFIG.SHEET_ID);
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function withLock_(fn) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try { return fn(); } finally { lock.releaseLock(); }
}

function clip_(v) {
  v = String(v == null ? "" : v);
  return v.length > SHEET_CELL_MAX_ ? v.substring(0, SHEET_CELL_MAX_) + " ...[cut]" : v;
}

// ---- POST router (called from doPost when the payload has a "type") ----
function handleTyped_(ss, d) {
  try {
    return withLock_(function() {
      switch (String(d.type)) {
        case "msg":   return handleMsg_(ss, d);
        case "photo": return handlePhoto_(ss, d);
        case "final": return handleFinal_(ss, d);
        case "place": return handlePlace_(ss, d);
        default:      return json_({ status: "error", message: "unknown type: " + d.type });
      }
    });
  } catch (err) {
    Logger.log("typed post failed: " + err.toString());
    return json_({ status: "error", message: err.toString() });
  }
}

// ---- GET router (called from doGet; returns null when it isn't one of ours) ----
function routeGet_(ss, e) {
  var p = (e && e.parameter) || {};
  try {
    if (p.status) return withLock_(function() { return handleStatus_(ss, String(p.status)); });
    if (p.places) return json_({ status: "success", places: readPlaces_(ss) });
    if (p.config) return json_({ status: "success", company: CONFIG.COMPANY || "", opsPhone: CONFIG.OPS_PHONE || "" });
    if (p.ack)    return withLock_(function() { return handleAck_(ss, String(p.ack)); });
  } catch (err) {
    Logger.log("typed get failed: " + err.toString());
    return json_({ status: "error", message: err.toString() });
  }
  return null;
}

// ---- Reports sheet helpers ----
function reportsSheet_(ss) {
  var sh = ss.getSheetByName("Reports") || ss.insertSheet("Reports");
  // Same idea as the Edits tab: always write the canonical header row; new columns only ever go on the end.
  sh.getRange(1, 1, 1, REPORT_HEADERS_.length).setValues([REPORT_HEADERS_]);
  return sh;
}

function findReportRow_(sh, rid) {
  var last = sh.getLastRow();
  if (last < 2) return 0;
  var ids = sh.getRange(2, 1, last - 1, 1).getValues();
  for (var i = ids.length - 1; i >= 0; i--) if (String(ids[i][0]) === rid) return i + 2;
  return 0;
}

function readReport_(sh, row) {
  var vals = sh.getRange(row, 1, 1, REPORT_HEADERS_.length).getValues()[0], o = {};
  REPORT_HEADERS_.forEach(function(h, i) { o[h] = vals[i]; });
  return o;
}

function writeReport_(sh, row, patch) {
  Object.keys(patch).forEach(function(k) {
    var col = REPORT_HEADERS_.indexOf(k);
    if (col >= 0) sh.getRange(row, col + 1).setValue(patch[k]);
  });
}

// ---- who to email ----
function rolesOf_(to) {
  if (Array.isArray(to)) return to;
  if (typeof to === "string" && to) return [to];
  return ["lead"];
}

function recipients_(roles) {
  var seen = {}, out = [], map = CONFIG.EMAIL || {};
  roles.forEach(function(role) {
    var list = map[String(role)];
    if (!list || !list.length) list = map["default"] || [];
    list.forEach(function(a) {
      a = String(a).trim();
      if (a && !seen[a.toLowerCase()]) { seen[a.toLowerCase()] = 1; out.push(a); }
    });
  });
  return out;
}

function sendMail_(to, subject, body, attachments) {
  var o = { to: to.join(","), subject: subject, body: body, name: (CONFIG.COMPANY || "Lukez Bunz") };
  if (attachments && attachments.length) o.attachments = attachments;
  MailApp.sendEmail(o);
}

function ackLink_(rid) {
  return ScriptApp.getService().getUrl() + "?ack=" + encodeURIComponent(rid);
}

// ---- step 1: the message ----
function handleMsg_(ss, d) {
  var rid = String(d.rid || "");
  if (!rid) return json_({ status: "error", message: "no rid" });
  var sh = reportsSheet_(ss), row = findReportRow_(sh, rid);
  var rep = row ? readReport_(sh, row) : null;

  // A retry of something already emailed must never email twice.
  if (rep && Number(rep.emailed) > 0) return json_({ status: "success", duplicate: true });

  var roles = rolesOf_(d.to), to = recipients_(roles);
  var subject = String(d.subject || "Report");
  var body = String(d.text || "");
  if (String(d.kind) === "dash") body += "\n\nI've got it (tap so it doesn't go to the mechanic):\n" + ackLink_(rid);
  body += "\n\n---\nReport " + rid + " received " + new Date().toString();

  if (!row) {
    sh.appendRow([
      rid, clip_(d.kind), Date.now(), d.urgent ? "URGENT" : "", JSON.stringify(roles), clip_(subject),
      clip_(d.text), clip_(JSON.stringify(d.data || {})), 0, 0, "", 0, 0,
      String(d.kind) === "dash" ? "waiting" : "sent", "", "", "", ""
    ]);
    row = sh.getLastRow();
  }

  var emailed = 0, err = "";
  if (!to.length) {
    err = "no recipients configured";
  } else {
    try { sendMail_(to, subject, body); emailed = to.length; }
    catch (mailErr) { err = "mail failed: " + mailErr.toString(); Logger.log(err); }
  }
  writeReport_(sh, row, { emailed: emailed, error: err });
  return json_({ status: "success", emailed: emailed });
}

// ---- step 2: does the script really have it? ----
function handleStatus_(ss, rid) {
  var sh = reportsSheet_(ss), row = findReportRow_(sh, rid);
  if (!row) return json_({ status: "success", found: false });
  var rep = readReport_(sh, row);

  // Dash warning nobody answered: goes to the mechanic (once).
  if (String(rep.kind) === "dash" && rep.state === "waiting" &&
      Date.now() - Number(rep.receivedAt) >= (CONFIG.ESCALATE_MINUTES || 15) * 60000) {
    var to = recipients_(["mechanic"]);
    try {
      if (to.length) sendMail_(to, "NO REPLY TO DASH WARNING: " + rep.subject,
        "Nobody has answered this dash warning within " + (CONFIG.ESCALATE_MINUTES || 15) + " minutes.\n\n" + rep.text);
    } catch (mailErr) { Logger.log("escalation mail failed: " + mailErr.toString()); }
    writeReport_(sh, row, { state: "escalated", escalatedAt: Date.now() });
    rep.state = "escalated"; rep.escalatedAt = Date.now();
  }

  return json_({
    status: "success", found: true,
    emailed: Number(rep.emailed) || 0,
    photos: Number(rep.photos) || 0,
    finalEmailed: Number(rep.finalEmailed) || 0,
    state: rep.state || "sent",
    ackAt: rep.ackAt ? Number(rep.ackAt) : 0,
    ackBy: rep.ackBy || ""
  });
}

// ---- the "I've got it" link ----
function handleAck_(ss, rid) {
  var sh = reportsSheet_(ss), row = findReportRow_(sh, rid), msg;
  if (!row) {
    msg = "Sorry, that report wasn't found.";
  } else {
    var rep = readReport_(sh, row);
    if (rep.state !== "ack") writeReport_(sh, row, { state: "ack", ackAt: Date.now(), ackBy: "Leading hand" });
    msg = "Thanks, got it. The driver will see that you've answered.";
  }
  return HtmlService.createHtmlOutput(
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="font-family:sans-serif;font-size:20px;padding:32px;text-align:center">' + msg + "</body>");
}

// ---- Drive folder for a report's photos ----
function photoRoot_() {
  var name = CONFIG.PHOTO_FOLDER || "Lukez Bunz Reports", it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}

function reportFolder_(sh, row, rep) {
  if (rep.folderId) { try { return DriveApp.getFolderById(String(rep.folderId)); } catch (e) {} }
  var stamp = Utilities.formatDate(new Date(), "Australia/Sydney", "yyyy-MM-dd HH-mm");
  var folder = photoRoot_().createFolder(stamp + " " + rep.kind + " " + rep.rid);
  writeReport_(sh, row, { folderId: folder.getId() });
  return folder;
}

function countFiles_(folder) {
  var n = 0, it = folder.getFiles();
  while (it.hasNext()) { it.next(); n++; }
  return n;
}

function safeName_(s) { return String(s || "").replace(/[^A-Za-z0-9._-]/g, "_").substring(0, 80); }

// ---- step 3: one photo / voice note ----
function handlePhoto_(ss, d) {
  var rid = String(d.rid || ""), sh = reportsSheet_(ss), row = findReportRow_(sh, rid);
  if (!row) return json_({ status: "error", message: "unknown report" });
  var rep = readReport_(sh, row), folder = reportFolder_(sh, row, rep);
  var name = safeName_(d.name) || ("file-" + Date.now());
  if (!folder.getFilesByName(name).hasNext()) {           // a retry must not save it twice
    var blob = Utilities.newBlob(Utilities.base64Decode(String(d.b64 || "")), String(d.mime || "image/jpeg"), name);
    folder.createFile(blob);
  }
  writeReport_(sh, row, { photos: countFiles_(folder) });
  return json_({ status: "success" });
}

// ---- step 4: the follow-up email with everything ----
function handleFinal_(ss, d) {
  var rid = String(d.rid || ""), sh = reportsSheet_(ss), row = findReportRow_(sh, rid);
  if (!row) return json_({ status: "error", message: "unknown report" });
  var rep = readReport_(sh, row), roles;
  try { roles = rolesOf_(JSON.parse(rep.to)); } catch (e) { roles = ["lead"]; }
  var to = recipients_(roles), folder = null, blobs = [], total = 0, n = 0;

  if (rep.folderId) {
    try {
      folder = DriveApp.getFolderById(String(rep.folderId));
      var it = folder.getFiles();
      while (it.hasNext()) { var f = it.next(); n++; total += f.getSize(); blobs.push(f.getBlob()); }
    } catch (e) { folder = null; blobs = []; }
  }
  var attach = total <= 20 * 1024 * 1024;                  // Gmail's limit is 25 MB; leave room
  var body = String(d.text || "") +
    (folder ? "\n\n" + n + " photo/file(s)" + (attach ? " attached and" : " (too big to attach)") + " saved in Drive:\n" + folder.getUrl() : "");
  var emailed = 0;
  if (to.length) {
    try { sendMail_(to, (d.again ? "More photos: " : "Full report: ") + rep.subject, body, attach ? blobs : []); emailed = to.length; }
    catch (mailErr) { Logger.log("final mail failed: " + mailErr.toString()); writeReport_(sh, row, { error: "final mail failed: " + mailErr.toString() }); }
  }
  if (emailed) writeReport_(sh, row, { finalEmailed: emailed, finalPhotos: n });
  return json_({ status: "success", emailed: emailed });
}

// ---- fleet places ----
function placesSheet_(ss) {
  var sh = ss.getSheetByName("Places") || ss.insertSheet("Places");
  sh.getRange(1, 1, 1, 3).setValues([["key", "json", "updatedAt"]]);
  return sh;
}

function handlePlace_(ss, d) {
  var key = String(d.key || ""); if (!key || !d.place) return json_({ status: "error", message: "no place" });
  var sh = placesSheet_(ss), last = sh.getLastRow(), row = 0;
  if (last > 1) {
    var keys = sh.getRange(2, 1, last - 1, 1).getValues();
    for (var i = 0; i < keys.length; i++) if (String(keys[i][0]) === key) { row = i + 2; break; }
  }
  var vals = [key, clip_(JSON.stringify(d.place)), new Date()];
  if (row) sh.getRange(row, 1, 1, 3).setValues([vals]); else sh.appendRow(vals);
  return json_({ status: "success" });
}

function readPlaces_(ss) {
  var sh = ss.getSheetByName("Places"), out = {};
  if (!sh || sh.getLastRow() < 2) return out;
  sh.getRange(2, 1, sh.getLastRow() - 1, 2).getValues().forEach(function(r) {
    try { out[String(r[0])] = JSON.parse(r[1]); } catch (e) {}
  });
  return out;
}

// ---- Street Litter edits (per-site patches, merged by site id) ----
// Stored in rows of <= 40,000 characters, because one cell can't hold more than 50,000.
function readJsonRows_(sh) {
  if (!sh || sh.getLastRow() < 2) return {};
  var rows = sh.getRange(2, 1, sh.getLastRow() - 1, 1).getValues();
  try { return JSON.parse(rows.map(function(r) { return String(r[0]); }).join("")) || {}; } catch (e) { return {}; }
}

function writeJsonRows_(sh, header, obj) {
  var text = JSON.stringify(obj), rows = [];
  for (var i = 0; i < text.length; i += 40000) rows.push([text.substring(i, i + 40000)]);
  sh.clear();
  sh.getRange(1, 1).setValue(header);
  if (rows.length) sh.getRange(2, 1, rows.length, 1).setValues(rows);
}

// ---- run this ONCE from the Apps Script editor (Run > authorizeOnce) ----
// Sending email and saving to Drive need permissions the old script never asked for.
// Until the owner approves them here, the new endpoints fail even after deploying.
function authorizeOnce() {
  Logger.log("Mail quota left today: " + MailApp.getRemainingDailyQuota());
  Logger.log("Photo folder: " + photoRoot_().getUrl());
  Logger.log("Sheet: " + openSheet_().getName());
  Logger.log("Recipients (default): " + recipients_(["lead"]).join(", "));
}
