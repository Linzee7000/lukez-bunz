/* Run forecast, driver details (leading hands only).

   GET ?history=1&pin=<the phone's stored leading hand PIN hash>
     -> the contents of the Drive file "lukez-bunz-run-history.json" (made by tools/reports/run_history.py as
        run-history-drivers.json): who did each run each day - first name, truck, bins, hours flipping, kg.
     -> {status:"error", err:"pin"}     wrong / no PIN
        {status:"error", err:"nopin"}   no LEAD_PIN set on the script yet
        {status:"error", err:"nofile"}  the file isn't in Drive
        {status:"error", err:"locked"}  too many wrong PINs lately (try again in 10 minutes)

   The repo and the app are public, so driver names and their bins per hour are kept here instead of in data/ (Fox, 27 Oct).
   The PIN: set LEAD_PIN to the leading hands' PIN, either in Config.js (CONFIG.LEAD_PIN) or as a Script property
   (Project Settings > Script properties > LEAD_PIN). A phone sends sha256("lukezbunz:" + PIN), the same hash the app keeps
   for leading hand mode, so every leading hand who wants the details must use that PIN on their phone. */
var HISTORY_FILE_NAME_ = "lukez-bunz-run-history.json";

function leadPinHash_() {
  var pin = (typeof CONFIG !== "undefined" && CONFIG.LEAD_PIN) || PropertiesService.getScriptProperties().getProperty("LEAD_PIN");
  if (!pin) return "";
  var d = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, "lukezbunz:" + String(pin).trim(), Utilities.Charset.UTF_8);
  return d.map(function(b) { var v = (b < 0 ? b + 256 : b).toString(16); return v.length < 2 ? "0" + v : v; }).join("");
}

function historyGet_(e) {
  var p = (e && e.parameter) || {};
  var cache = CacheService.getScriptCache(), bad = +(cache.get("histBad") || 0);
  if (bad >= 20) return json_({ status: "error", err: "locked" });
  var want = leadPinHash_();
  if (!want) return json_({ status: "error", err: "nopin" });
  if (String(p.pin || "").toLowerCase() !== want) {
    cache.put("histBad", String(bad + 1), 600);
    return json_({ status: "error", err: "pin" });
  }
  var it = DriveApp.getFilesByName(HISTORY_FILE_NAME_), newest = null;
  while (it.hasNext()) { var f = it.next(); if (!f.isTrashed() && (!newest || f.getLastUpdated() > newest.getLastUpdated())) newest = f; }
  if (!newest) return json_({ status: "error", err: "nofile" });
  return ContentService.createTextOutput(newest.getBlob().getDataAsString("UTF-8")).setMimeType(ContentService.MimeType.JSON);
}
