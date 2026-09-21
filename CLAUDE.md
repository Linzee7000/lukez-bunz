# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Lukez Bunz" is a mobile-first, offline-capable web app for waste-collection truck drivers at Solo Resource Recovery. Data covers kerbside Garbage / Recycling / FOGO bins (~57k property records) and public "Street Litter" bins. Screens: live GPS map, drive HUD of streets and next bins, search, welcome/run picker, and a driver shift screen (pre-start check, brake wear, accident flow, defect reports).

The whole app is one hand-edited file, `index.html` (~31k lines, 1.7 MB), with plain browser JS: no modules, bundler, package.json, tests or linter. Remote: `Linzee7000/lukez-bunz`. It is served as static files from `main` via GitHub Pages at https://linzee7000.github.io/lukez-bunz/, so a push to `main` goes live immediately. Currently only the owner and a few testers use it. Commits are plain sentence-case descriptions of a behaviour change, usually touching only `index.html` (plus `data/` when regenerating).

## Running / testing

Serve the folder over HTTP. Opening via `file://` breaks the synchronous XHR data loads.

```bash
python3 -m http.server 8000   # http://localhost:8000/
```

Verification is manual in a browser, using a mobile viewport. GPS, sync, KMZ import and Mapbox need real location and network access. Leaflet 1.9.4, Turf 6.5.0 and JSZip 3.10.1 load from CDNs (`unpkg.com`, `cdnjs`), so the first load needs network access.

Because the file is huge, use `grep -n` and read line ranges rather than opening it whole. Line numbers below are approximate.

## Repository layout

- `index.html`: the entire app (CSS, HTML and all scripts).
- `*.png`: icons, referenced by relative `src="x.png"`. A missing one fails silently as a broken image.
- `data/street-litter-sites.json`, `street-litter-run-data.json`, `street-litter-precinct-maps.json`: static Street Litter reference data, loaded with **synchronous XHR at parse time** into `STREET_LITTER_SITES`, `STREET_LITTER_RUN_DATA` and `STREET_LITTER_PRECINCT_MAPS`. Code guards with `typeof X === 'undefined'`, so keep those guards. These are **not** synced from the Google Sheet. To refresh, re-export and regenerate the JSON (see the comments above each data `<script>`).
- `data/run-boundaries.json`: shared run boundary polygons, `{version, generated, boundaries:{"Garbage#Friday#208":[[lat,lng],...]}, extras:{key:[ring,...]}, aliases:{shortKey:key}}`. Fetched at start by `lbApplySharedBoundaries()` and **written over every device's `customRunBorders`**, but only once per `generated`/`version` value, so **change `generated` when regenerating** or devices keep the old set. Two builders exist and produce very different results: `lbRebuildAllBoundaries()` (house-pin "nearest house" tessellation, `lbTessellate`: jagged, ignores roads and lots) and the property-line builder in `lb-parcels-script` (Property boundaries menu > Build every run: Vicmap lot lines, runs meet down the middle of the road). The file should come from the property-line builder, then `tools/route-maps/extend_boundaries.py` stretches recycling runs to include the streets the truck drives (read off the route-map PDFs; garbage and FOGO runs have no route maps yet, so they are not extended). To regenerate: in the app, match every house, then Build every run for each stream (Garbage, Recycling, FOGO), then write `customRunBorders` + `lbParcels._t.getExtras()` in this file's shape, then run `compare.py` and `extend_boundaries.py --write` (see `tools/route-maps/README.md`).
- `data/street-modes.json`: streets the trucks drive in / reverse in, `{version, generated, segments:[{type:'drive-reverse-out'|'reverse-in-drive-out', street, src, points:[[lat,lng],...]}]}`. Read off the recycle run route maps (PDF) by `tools/route-maps/`, so positions are approximate (5-20 m) and cover all ten recycling day/week route maps (Mon-Fri, Week A and B); pages that show only part of a run (zoomed detail pages) fit badly and are skipped, and the garbage/FOGO maps exist only as Publisher (.pub) files, not yet exported to PDF. Fetched by the main script into `sharedStreetModes` and drawn dashed by `drawRoadModes()` for every kerbside stream (not Street Litter); the "Reverse in / drive in streets" row in the Layers panel toggles it (`showStreetModes`, localStorage `lukezBunzShowStreetModes`). Separate from the hand-drawn per-device `roadModes` and per-house `houseStreetModes`. Not done yet: the maps' "collection point" notes and the school highlights.
- `tools/route-maps/`: Python scripts that read the route-map PDFs (see its README). **Summer recycle runs share regular recycle run numbers but have no week letter**; never match them to Week A/B pages or keys.
- `apps-script/`: the Google Apps Script backend behind `SCRIPT_URL`, managed with `clasp` (see "Backend script" below).
- Root `*.csv` / `*.csv.gz` (`master_combined_with_metadata*`, `SL_site_list_39400.csv`, `SL_asset_list_39401.csv`): source exports and backups. The app does not fetch them. The master CSV is only used through the manual "select master CSV file" fallback when sync fails.

## Architecture

The file is a stack of `<script>`/`<style>` blocks sharing one global scope, in load order:

1. Custom dialog helpers (`customAlert/Confirm/Prompt`, Promise-based). Use these, never native `alert/confirm/prompt`.
2. `street-litter-*` data blocks (above).
3. **Main script** (~4833-13113, plus a continuation to ~18209): `SCRIPT_URL`, `buildBinsAtAddress`, IndexedDB helpers, filters, GPS snail trail, KMZ/KML import, geofences, Street Litter layers, run boundaries, property inspector, sync, boot.
4. `unified-clean-script`: the run/stream/day filter modal and map rotation (IIFE-local scope).
5. `welcome-screen-script`, then the `lb-*` add-ons (`lb-drawer`, `lb-map-tools`, `lb-phase2`, `lb-phase3`, `lb-parcels`, `lb-street-stats`, `lb-break-clock`), then `ux2-style`/`ux2-script`.

**`ux2-script` (~26946-31271) is the biggest block.** It is a set of independent IIFEs, each under a banner comment: choose-on-map picker, emoji-to-icon swapper, Customize + "Nerd mode", HUD + issue reporting, run-being-driven vs looked-up, the driver shift/pre-start/brakes, the **outbox**, nearby toilets/tip spots/hydrants, the accident flow, role permissions, Service days map, location-problems report, and map-furniture/layer glue.

**Add-ons extend earlier code by wrapping globals, not editing it**: `const prev = window.fn; window.fn = function(...){ prev(...); /* extra */ }`. `lbNotifyTabChanged`, `renderCurrentAddressTelemetry`, `updateMapHeaderInfo`, `toggleNextBinBox`, `initLeafletMap`, `logEdit` and `openLocationPickerModal` are each wrapped several times. Consequences:
- Only `window.`-assigned or top-level `function` declarations can be wrapped. IIFE-local ones can't.
- Load order matters. A wrapper only sees what was defined before it, and it must tolerate a missing target (`typeof fn === 'function'`).
- Before changing a behaviour, `grep -n "window.fnName"` to find every wrapper. What the user sees is the composition of all of them.
- Cross-block calls go through `window.*` (`uxIsLead`, `lbOutbox`, `lbMedia`, `lbStraySites`, ...). ux2 blocks read main-script globals via a `g('name')` helper that evaluates by name, so a misspelled global fails silently.

**Navigation and state.** `switchMainTab(tab)` toggles `.screen-view.active` among `welcome`, `map`, `hud`, `search`, sets `activeTab` and calls `window.lbNotifyTabChanged(tab)`. The map is a full-bleed overlay with slide-out panels (`body.lb-drawer-open / lb-layers-open / lb-settings-open`). CSS is driven from `<body>` classes (`ux2`, `dark-mode`, `ux-light`, `lb-map-screen`, `stream-*`, `lb-lead`) and `data-ux-screen`. Filtering state lives in globals: `activeFilterStream`, `activeFilterWeek`, `activeFilterDataSource`, `selectedRunsSet`. Re-render through the existing `render*`/`update*` functions rather than patching the DOM.

**Data model.**
- `siteRecords` is the master list, built from a CSV that the Google Apps Script backend serves at `SCRIPT_URL?download=csv`. Each site has `soloSchedule`, `soloStreams` / `councilStreams` (Garbage/Recycling/FOGO bin lists) and run fields `garRun`, `recRun`, `fogRun`, `recSummerRun`. Data source is `solo` or `council`.
- Edits go into `masterEditsLog` and are merged onto records by `mergeEditsIntoRecords`. They are never written back into the CSV.
- Street Litter is a parallel dataset (`StreetGarbage` / `StreetRecycling` streams) with per-device `streetLitterOverrides`. Unlike kerbside runs it can run on weekends.
- Run boundaries are `customRunBorders` keyed `Stream#Day#Run`, with a backup in `customRunBordersBackup` for undo.

**Persistence.**
- IndexedDB `LukezBunzMasterDB_v1200`, one object store `store`, via `saveToDB(key, val)` / `loadFromDB(key)`. Keys: `masterRecords`, `masterEditsLog`, `customRunBorders`, `kmzDataByRun`, `geofences`, `gpsTrail*`, `runProgressState`, `streetLitterOverrides`, `uiAccentBase`.
- `localStorage`: UI prefs under `lukezBunz*`; `lbTheme`, `lbRole`, `lbLeadPin`, `lbDriver`, `siteReminders`, `lbMapboxToken`, shift/brake history (`lbShiftHistory`, `lbBrakes`) and the outbox queue.
- Boot (`DOMContentLoaded` in the main script) restores from IndexedDB. When you change a stored shape, handle old saves. See the trail-restore code, which backfills missing fields.

**Sync (`startUpdateProcess`).**
1. POST pending edits, hand-made boundaries, reminders and Street Litter edits to `SCRIPT_URL` with `mode:'no-cors'`. The response is opaque, so success can't be confirmed.
2. GET `SCRIPT_URL` to pull Street Litter overrides.
3. GET `?download=csv` and re-index via `processMasterCsvText`.

Only edits past `lastSyncedEditCount` are sent, to avoid duplicate sheet rows. Boundaries that came from a rebuild or the shared file are excluded (`lbBoundariesToPush`) because they are too big for the script. `processMasterCsvText` deliberately **refuses** a CSV with a bad header, fewer than 500 rows, or under half the existing row count. Do not weaken it: an Apps Script error page once wiped the real dataset.

**Outbox (`window.lbOutbox`).** Driver reports (accident, dash warning, brakes, defects, damaged bins, fleet-added places) are queued in localStorage and POSTed to `SCRIPT_URL`, then **confirmed** by polling `?status=<rid>` / `?places=1`. Failed sends retry with exponential backoff. Confirmation depends on the deployed Apps Script supporting those endpoints (`err = 'old-script'` means it doesn't). Anything that changes what a report contains must match `apps-script/Reports.js`.

## Backend script (`apps-script/`)

The Apps Script project behind `SCRIPT_URL` (standalone, `executeAs` the owner, `ANYONE_ANONYMOUS`). `Code.js` is the original sync (`doPost`/`doGet`: edits, boundaries, reminders, Street Litter edits, master CSV download). `Reports.js` handles the outbox protocol: `type: msg | photo | final | place` POSTs and `?status= / ?places= / ?config= / ?ack=` GETs, with reports on a "Reports" tab, photos in a Drive folder, and email via `MailApp`. `index.html` in there is a leftover old web-app page that nothing serves.

- **Private config:** `Config.js` (Sheet ID, master CSV Drive ID, recipient emails per role) is git-ignored because the repo is public, but `clasp push` still uploads it. `Config.example.js.txt` shows its shape. `.clasp.json` (script ID) is git-ignored too. A fresh checkout needs both recreated.
- **Deploying:** `clasp push` only updates the script's working copy. The live `/exec` URL keeps serving the last deployed version until `clasp deploy -i <deploymentId>` (same id, so `SCRIPT_URL` doesn't change). To roll back, redeploy the previous version number. Deploy and list with `clasp list-deployments`.
- **First run after new permissions:** new scopes (Mail, Drive) need the owner to run `authorizeOnce` in the Apps Script editor once, or the new endpoints fail even after deploying.
- **Testing:** there is no local runner. Changes have been checked against mocked Google services only, so verify on Google before relying on a change.
- A second, older prototype script exists on the owner's account (not used by the app). Don't push to it.

**Roles.** Driver vs leading hand, set by `lbRole`. Leading-hand mode is unlocked by a SHA-256-hashed PIN stored on the phone and toggles `body.lb-lead`. It is a UI guard only, not real security. Drivers have limited edit rights (runs, boundaries), enforced in the "What a driver may change" block.

**Map.** Leaflet with Esri World Imagery, or Mapbox when a `pk.` token is stored. Overpass, Nominatim and Vicmap Parcel (ArcGIS) are used for street names, reverse geocoding and parcels. Routes come from depot KMZ exports parsed in-browser (`extractKmzKml`, `kmzDataByRun`). A live GPS "snail trail" is capped at 400 km and persisted across reloads. The map has one DOM marker per house/bin, so zoomed-out views need the thinning logic in the "zoomed right out" block.

## Conventions

- Long comments explain *why* (past bugs, GPS edge cases, data-loss incidents). Keep them, and add one when fixing something subtle.
- Icons are `<img class="icon-img" src="name.png">`. Stream colours are Garbage red, Recycling yellow, FOGO green.
- New UI goes in the `ux2` layer as another IIFE that wraps existing globals. Don't restructure the earlier blocks.
