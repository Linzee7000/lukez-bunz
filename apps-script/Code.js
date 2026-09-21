// 1. SAVE EDITS, BOUNDARIES & REMINDERS (POST)
function doPost(e) {
  var ss = openSheet_();

  var rawData = null;

  try {
    if (e && e.parameter && e.parameter.payload) {
      rawData = JSON.parse(e.parameter.payload);
    } else if (e && e.postData && e.postData.contents) {
      var content = e.postData.contents;
      if (content.indexOf("payload=") === 0) {
        content = decodeURIComponent(content.substring(8).replace(/\+/g, " "));
      }
      rawData = JSON.parse(content);
    }
  } catch(err) {
    logSyncAttempt_(ss, null, "parse error: " + err.toString(), 0);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  if (!rawData) {
    logSyncAttempt_(ss, null, "no data received", 0);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "No data received" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  // Driver reports, photos and fleet places carry a "type" and are handled in Reports.js.
  // The normal sync payload (edits / boundaries / reminders) has no type.
  if (rawData.type) return handleTyped_(ss, rawData);

  var errors = [];
  var duplicatesSkipped = 0;

  // A. Save Property, Bin, Flag & Rating Edits
  try {
    if (rawData.edits && rawData.edits.length > 0) {
      var editSheet = ss.getSheetByName("Edits") || ss.insertSheet("Edits");

      // "editId" is a stable unique ID the app now stamps onto every edit
      // the moment it's recorded (see logEdit() client-side). It's what
      // lets us tell "this edit was already saved" from "this is new" -
      // independent of the app's own lastSyncedEditCount bookkeeping,
      // which only lives on the device and can be lost (reinstall,
      // cleared storage, restoring from an exported CSV). Keeping it as
      // column A makes it the natural key to de-duplicate on below.
      var desiredHeaders = [
        "editId", "timestamp", "editType", "propId", "siteId", "address",
        "stream", "serial", "lat", "lng", "day", "weekLetter",
        "garRun", "recRun", "recSummerRun", "fogRun", "runFlags",
        "ratingStars", "ratingComment"
      ];

      // Force row 1 to hold exactly these headers, in this exact order,
      // starting at column A - every single run, not just when the sheet
      // is brand new. See the long comment that used to live here: an
      // earlier "self-healing" version compared header text and could
      // silently duplicate the whole header row instead of fixing it.
      // Unconditionally writing the canonical header row makes that
      // failure mode impossible. Safe every time because new fields only
      // ever get added to the END of this list.
      editSheet.getRange(1, 1, 1, desiredHeaders.length).setValues([desiredHeaders]);
      var headers = desiredHeaders;

      // Build the set of editIds already saved in this sheet so a resend
      // (retry after a dropped connection, a reinstalled app replaying
      // its whole local log, a restored CSV) can never create a second
      // row for the same edit. Column A is "editId" per the header list
      // above.
      var existingIds = {};
      var lastRow = editSheet.getLastRow();
      if (lastRow > 1) {
        var idValues = editSheet.getRange(2, 1, lastRow - 1, 1).getValues();
        for (var r = 0; r < idValues.length; r++) {
          var idVal = idValues[r][0];
          if (idVal) existingIds[String(idVal)] = true;
        }
      }

      var newRows = [];
      rawData.edits.forEach(function(edit) {
        var id = edit.editId ? String(edit.editId) : "";
        // Edits without an editId at all (e.g. a very old client that
        // predates this field) can't be deduplicated - always save those,
        // same as before. Edits WITH an id that's already on the sheet
        // are skipped as duplicates.
        if (id && existingIds[id]) {
          duplicatesSkipped++;
          return;
        }
        if (id) existingIds[id] = true; // guard against dupes within the same payload too
        newRows.push(headers.map(function(key) {
          return edit[key] !== undefined ? edit[key] : "";
        }));
      });

      if (newRows.length > 0) {
        editSheet.getRange(editSheet.getLastRow() + 1, 1, newRows.length, headers.length).setValues(newRows);
      }
    }
  } catch(errA) {
    Logger.log("Edits section failed: " + errA.toString());
    errors.push("edits: " + errA.toString());
  }

  // B. Save Custom Boundary Polygons
  try {
    if (rawData.boundaries && Object.keys(rawData.boundaries).length > 0) {
      var bSheet = ss.getSheetByName("Boundaries") || ss.insertSheet("Boundaries");
      bSheet.clear();
      bSheet.appendRow(["Boundary_JSON"]);
      bSheet.appendRow([JSON.stringify(rawData.boundaries)]);
    }
  } catch(errB) {
    Logger.log("Boundaries section failed: " + errB.toString());
    errors.push("boundaries: " + errB.toString());
  }

  // C. Save Site Reminders
  try {
    if (rawData.reminders && Object.keys(rawData.reminders).length > 0) {
      var rSheet = ss.getSheetByName("Reminders") || ss.insertSheet("Reminders");
      rSheet.clear();
      rSheet.appendRow(["Reminders_JSON"]);
      rSheet.appendRow([JSON.stringify(rawData.reminders)]);
    }
  } catch(errC) {
    Logger.log("Reminders section failed: " + errC.toString());
    errors.push("reminders: " + errC.toString());
  }

  // D. Save Street Litter edits (small per-site patches keyed by site id).
  // Merged into what is already stored, so one device never wipes another's.
  try {
    if (rawData.streetLitterEdits && Object.keys(rawData.streetLitterEdits).length > 0) {
      var slSheet = ss.getSheetByName("StreetLitterEdits") || ss.insertSheet("StreetLitterEdits");
      var slMerged = readJsonRows_(slSheet);
      Object.keys(rawData.streetLitterEdits).forEach(function(k) { slMerged[k] = rawData.streetLitterEdits[k]; });
      writeJsonRows_(slSheet, "StreetLitterEdits_JSON (split over rows)", slMerged);
    }
  } catch(errD) {
    Logger.log("Street Litter section failed: " + errD.toString());
    errors.push("streetLitter: " + errD.toString());
  }

  logSyncAttempt_(ss, rawData, errors.join(" | "), duplicatesSkipped);

  return ContentService.createTextOutput(JSON.stringify({
    status: errors.length ? "partial_error" : "success",
    duplicatesSkipped: duplicatesSkipped,
    errors: errors
  })).setMimeType(ContentService.MimeType.JSON);
}

// Writes one diagnostic row per sync attempt to a "SyncLog" tab so you can
// see - directly in the spreadsheet, no need to dig through Executions -
// exactly what each sync actually sent, whether it errored, and whether
// any of it was recognized and skipped as a duplicate.
function logSyncAttempt_(ss, rawData, errorText, duplicatesSkipped) {
  try {
    var sheet = ss.getSheetByName("SyncLog") || ss.insertSheet("SyncLog");
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(["timestamp", "editsCount", "duplicatesSkipped", "boundaryKeys", "reminderKeys", "errors"]);
    } else {
      // If this sheet was created by the older version of this script, it
      // won't have the duplicatesSkipped column yet - add it in without
      // disturbing existing rows or reordering anything.
      var headerRow = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
      if (headerRow.indexOf("duplicatesSkipped") === -1) {
        sheet.insertColumnAfter(2);
        sheet.getRange(1, 3).setValue("duplicatesSkipped");
      }
    }
    var editsCount = (rawData && rawData.edits) ? rawData.edits.length : 0;
    var boundaryKeys = (rawData && rawData.boundaries) ? Object.keys(rawData.boundaries).length : 0;
    var reminderKeys = (rawData && rawData.reminders) ? Object.keys(rawData.reminders).length : 0;
    sheet.appendRow([new Date(), editsCount, duplicatesSkipped || 0, boundaryKeys, reminderKeys, errorText || ""]);
    // Keep the log from growing forever - trim to the most recent 500 rows.
    var lastRow = sheet.getLastRow();
    if (lastRow > 501) {
      sheet.deleteRows(2, lastRow - 501);
    }
  } catch (logErr) {
    Logger.log("SyncLog write failed: " + logErr.toString());
  }
}

// 2. STREAM MASTER DATASET OR READ SYNC DATA (GET)
function doGet(e) {
  if (e && e.parameter && e.parameter.download === "csv") {
    try {
      var file = DriveApp.getFileById(CONFIG.MASTER_FILE_ID);
      return ContentService.createTextOutput(file.getBlob().getDataAsString("UTF-8"))
        .setMimeType(ContentService.MimeType.TEXT);
    } catch(err) {
      return ContentService.createTextOutput("ERROR: " + err.toString())
        .setMimeType(ContentService.MimeType.TEXT);
    }
  }

  var ss = openSheet_();

  // ?status= / ?places= / ?config= / ?ack= are answered by Reports.js
  var routed = routeGet_(ss, e);
  if (routed) return routed;

  var editSheet = ss.getSheetByName("Edits");
  var bSheet = ss.getSheetByName("Boundaries");
  var rSheet = ss.getSheetByName("Reminders");

  var edits = [];
  if (editSheet && editSheet.getLastRow() > 1) {
    var data = editSheet.getDataRange().getValues();
    var headers = data[0];
    for (var i = 1; i < data.length; i++) {
      var obj = {};
      headers.forEach(function(h, idx) { obj[h] = data[i][idx]; });
      edits.push(obj);
    }
  }

  var boundaries = {};
  if (bSheet && bSheet.getLastRow() > 1) {
    try {
      boundaries = JSON.parse(bSheet.getRange(2, 1).getValue());
    } catch(err) {}
  }

  var reminders = {};
  if (rSheet && rSheet.getLastRow() > 1) {
    try {
      reminders = JSON.parse(rSheet.getRange(2, 1).getValue());
    } catch(err) {}
  }

  var streetLitterEdits = readJsonRows_(ss.getSheetByName("StreetLitterEdits"));

  return ContentService.createTextOutput(JSON.stringify({ edits: edits, boundaries: boundaries, reminders: reminders, streetLitterEdits: streetLitterEdits }))
    .setMimeType(ContentService.MimeType.JSON);
}

// ---------------------------------------------------------------------
// IMPORTANT - if boundaries/reminders still don't show up after pasting
// this in, it is very likely NOT a code problem but a deployment one:
// saving a script in the Apps Script editor does NOT update your live
// /exec URL. You must go to Deploy > Manage deployments > (pencil/edit
// icon on your existing deployment) > Version: "New version" > Deploy.
// Only that step pushes this code to the URL the app is actually using.
//
// WHAT CHANGED IN THIS VERSION
// - Every edit row now starts with an "editId" column. The app stamps a
//   unique ID onto each edit the moment it's made, so the same edit
//   always carries the same ID no matter how many times it's sent.
// - Before appending new rows to "Edits", this script now reads the
//   editIds already in the sheet and skips any incoming edit whose ID is
//   already there - so a resend (dropped connection retry, a reinstalled
//   app replaying its history, a restored CSV) can never create a second
//   row for the same change.
// - The "SyncLog" tab gets a new "duplicatesSkipped" column so you can
//   see, per sync, how many incoming edits were recognized as ones
//   already saved and skipped.
// - If your existing Edits sheet has old rows saved before this change,
//   they simply won't have an editId (blank in that column) - that's
//   fine, they're left exactly as they are and are never touched or
//   removed by this script.
// ---------------------------------------------------------------------

