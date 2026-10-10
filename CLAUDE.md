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
- `data/run-boundaries.json`: shared run boundary polygons, `{version, generated, boundaries:{"Garbage#Friday#208":[[lat,lng],...]}, extras:{key:[ring,...]}, aliases:{shortKey:key}}`. Fetched at start by `lbApplySharedBoundaries()` and **written over every device's `customRunBorders`**, but only once per `generated`/`version` value, so **change `generated` when regenerating** or devices keep the old set. Two builders exist and produce very different results: `lbRebuildAllBoundaries()` (house-pin "nearest house" tessellation, `lbTessellate`: jagged, ignores roads and lots) and the property-line builder in `lb-parcels-script` (Property boundaries menu > Build every run: Vicmap lot lines, runs meet down the middle of the road). The file should come from the property-line builder, then `tools/route-maps/extend_boundaries.py` stretches every stream's runs (Recycling, FOGO, Garbage) to include the streets the truck drives (read off the route-map PDFs) and, where growing two runs of the same stream and day made them overlap, splits the disputed ground down the middle by nearest own house - a real N-way partition per (stream, day), not fixed pair by pair (fixing one pair naively can reopen another). Last of all `tools/boundaries/` neatens the whole set into one tidy map (straight edges; wherever two runs of any stream meet they use the very same line; no house changes run - see its README), and that is what the file holds now. To regenerate: in the app, match every house, then Build every run for each stream, write `customRunBorders` + `lbParcels._t.getExtras()` in this file's shape, then run `compare.py` (Recycling/FOGO) and/or `identify_garbage.py` (Garbage - see below) and `extend_boundaries.py --write` (see `tools/route-maps/README.md`), then `tools/boundaries/build_atoms.py` and `straighten.py` and copy the result in with a new `generated`.
- `data/parcels.json`: every Vicmap lot in the service area plus which lot each house sits on, `{version, generated, scale, parcels:{id:[deltas, area, lot, plan, spi?, holes?]}, sites:{siteKey:[parcelId, m, d]|0}}`. Shipped so the property boundaries layer works offline and on a fresh phone instead of fetching tiles from the Vicmap ArcGIS service (which is still the fallback for anything the file lacks). Merged into IndexedDB by `loadSharedParcels()` once per `generated`, filling gaps only - a phone that matched a new estate keeps its own. ~2.5MB gzipped: coordinates are deltas scaled by 1e5 (~1m). Built by `tools/parcels/` (see its README). Also the geometry `extend_boundaries.py` splits shared roads with.
- `data/street-modes.json`: streets the trucks drive in / reverse in, `{version, generated, segments:[{type:'drive-reverse-out'|'reverse-in-drive-out', street, src, points:[[lat,lng],...]}]}`. Read off the route-map PDFs (Recycling, FOGO and the identified Garbage pages) by `tools/route-maps/`, so positions are approximate (5-20 m); pages that show only part of a run (zoomed detail pages) fit badly and are skipped. Fetched by the main script into `sharedStreetModes` and drawn dashed by `drawRoadModes()` for every kerbside stream (not Street Litter); the "Reverse in / drive in streets" row in the Layers panel toggles it (`showStreetModes`, localStorage `lukezBunzShowStreetModes`). Separate from the hand-drawn per-device `roadModes` and per-house `houseStreetModes`. Not done yet: the maps' "collection point" notes and the school highlights.
- `tools/route-maps/`: Python scripts that read the route-map PDFs (see its README). Recycling and FOGO/Organics PDFs have a readable title (day/run/week) that `compare.py` reads directly. **Garbage's PDFs have a broken font export - every letter, including digits, decodes to an unrelated codepoint - so which run a page shows can't be read from the text**; `identify_garbage.py` instead fits each page's route against every Garbage run for that day (the day comes from the filename) and only keeps a confident, unambiguous match, so only some Garbage pages end up used - that's expected, not a bug. **Summer recycle runs share regular recycle run numbers but have no week letter**; never match them to Week A/B pages or keys.
- `tools/boundaries/`: Python (shapely) that turns the run boundaries into one neat shared map, using the master CSV's house points so no house changes run (see its README).
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

**Edit the map (`lb-boundary-hub-script`, look in `lb-editmap-style` at the very end of the file).** One panel (`#lbHub`, opened by `lbOpenBoundaryHub(tab)`) beside the map, under it on a phone held upright, with four tabs: Boundary, Houses, Truck line, Streets. It replaced the old "Boundaries & streets" hub and the second column of edit buttons: every tool is a tile in the panel and the line over the map (`setMapTopBarContext` with no buttons) only says what to do next. Opening the Boundary tab turns boundary editing on, closing the panel turns it off, and `toggleRoadSnapEditing()` from anywhere else just opens the panel.
- Boundary tab: a run here is ONE boundary, named by its full key (`Stream#Day#Week#Run`, `activeKeys`), never by the run number alone: 219 is a different piece of ground on each day and week, and with no day chosen in the filter every one of them is on the map (about 220 boundaries). The panel shows "Working on" (the picked run, with the day when more than one day is on the map, and its colour row), "Runs where you tapped" (runs of different streams lie on top of each other; a tap lists every run under it) and "Runs on screen" (follows the map, `viewKeys()`). "Several runs" lets more than one be worked on. Points are picked by tapping or by dragging a box (the Box select tile, or Shift + drag), and the picked points' buttons (delete, straighten, snap that stretch, pick between) are in the panel straight away. Undo / redo (`Ctrl+Z` / `Ctrl+Y`) keep snapshots of the saved boundaries.
- **Shared lines:** where two runs meet they have the very same points, so a point within 0.3 m of a point in another saved boundary is the same point. Moving, adding or deleting it does the same in the other run (also when that run is filtered off the map). With "All streams" on (`linkAll`, the default) that is every saved boundary of any stream, day or week, because they use the same lines; off, only the same stream / day / week (`linked()`). Keep it that way: any new boundary tool must go through `deletePoints` / `insertAt` / the drag code, or update the neighbours itself, or gaps open between runs.
- **The magnet** (`magnetTargets` / `magnetAt`, the Magnet tile): a dragged point jumps onto another run's point, or anywhere along its line, once it is 14 px away (10 px for a line; more for a finger), and lands on it exactly; dropped on a line where the other run has no point, that run gets one (`twinOnEdge`). This is how two runs are made to meet; without it the point had to land within 30 cm by eye.
- **Run colours:** an outline is the run's own colour (`window.lbColourOfKey`, used by `renderMapData`): the one picked in the panel's colour row (saved in `runColorMap` under the lower-cased full key, per phone, not shared), else a shade of the stream's colour that depends only on the run number. It used to be picked by the run's position in the list, so runs changed colour with the filter. An older colour saved under just the run number still counts unless it is one of `PRESET_COLORS`.
- **Never call `renderMapData()` for a small change.** A whole day's runs is about 16,000 house and bin markers and a redraw takes seconds. The panel updates outlines with `setLatLngs` (`commit`, `syncLayers`), redraws single house markers (`redrawHouses`, using the markers captured by the `drawHouseTriangle` wrapper) and holds back the redraw the main script's own snap functions ask for (`wholeRun`).
- Houses tab: the map's own "select houses" state (`selectedCollectionHouseIds`, `collectionSelectionActive`) with its buttons in the panel; a box picks the houses the map has drawn. Truck line tab: drawing the line a truck follows (below), the KML / KMZ tools, and the picked run's line is shown without narrowing the filter (`renderKmzEvidence` wrapper). Streets tab: the street-name forms, unchanged.
- Test hooks are on `window.lbBoundaryHub._t` (`rings()`, `twins()`, `drag()`, `pick()`, `undo()`...).
- **Drawn truck lines** (same script, sections "TRUCK LINES, the sums" = the plain-number object `TL`, and "DRAWN TRUCK LINES"). A leading hand presses Draw line and taps along the way the truck goes. Between taps the line follows the roads: OpenStreetMap ways from Overpass, fetched in 0.02 degree squares and kept in IndexedDB `lbRoadTiles`, built into a graph (`TL.mkGraph`), shortest way by `TL.route` (one-way streets and roundabouts respected, with a fall-back that ignores them). So drawing with Follow roads on needs internet the first time an area is used; with it off a tap gives a straight stretch (`s: 1`).
  - Stored as the way driven down the MIDDLE of the road: `TLD[runKey] = { ts, by, legs: [{ g, r, s, p }] }` in IndexedDB `lbTruckLines`; `runKey` is the boundary key (`Stream#Day#Week#Run`), `g` is the press that made the stretch (undo, rub out and a T-turn's three stretches go by `g`), `r: 1` is reversing.
  - **The kerb side is worked out when it is drawn** (`TL.kerb`): trucks keep left, so the line sits 3 m to the left of the way of travel (widened when zoomed out so the two sides stay apart), and up a street and back down it shows as two lines. A reversing stretch sits on the right of the way it moves (the truck stays in the lane it faces along) and is drawn with white dashes on top, because in a T-turn it lies right under the forward stretches. Do not store the shifted line.
  - **T-turn** (`TL.tTurn`): from the pen, forward to the first corner with a road both sides, 14 m into the left road, reverse 14 m past the corner into the right road, forward and left back into the street. Driveway / car park ways only count as arms when no proper corner is found.
  - Drawn in its own pane (`lb-truckline-pane`, `pointer-events: none`) by `tlRender()`, which the `renderKmzEvidence` wrapper calls; it follows the same "Truck lines" switch and run filter as imported KML lines (a phone that never touched the switch gets it turned on when a drawn line first arrives). Taps while drawing are read off the map container's own `click` in the capture phase and stopped there, so a house or bin under the tap does not open.
  - **Shared between phones** as outbox places, kind `truckLine`, id `tl_<key>_<part>`, in parts under 24,000 characters (a sheet cell holds 50,000), points packed by `TL.enc`. Sent 20 s after the last change or when the panel is put away; `pullPlaces` hands them to `window.lbTruckLines.fleet()`; the newest `ts` wins and a line only replaces the local one once every part with that `ts` has arrived. An empty `legs` is a cleared line. Needs no Apps Script change.
  - Test hooks: `window.lbTruckLines._t` (`tapAt([lat, lng])`, `turn()`, `data()`, `state()`, `parts()`, `fleetNow()`, `setFetch(fn)` to hand roads in without the network).

**Roles.** Driver vs leading hand, set by `lbRole`. Leading-hand mode is unlocked by a SHA-256-hashed PIN stored on the phone and toggles `body.lb-lead`. It is a UI guard only, not real security. Drivers have limited edit rights (runs, boundaries), enforced in the "What a driver may change" block.

**Map.** Leaflet with Esri World Imagery, or Mapbox when a `pk.` token is stored. Overpass, Nominatim and Vicmap Parcel (ArcGIS) are used for street names, reverse geocoding and parcels. Routes come from depot KMZ exports parsed in-browser (`extractKmzKml`, `kmzDataByRun`). A live GPS "snail trail" is capped at 400 km and persisted across reloads. The map has one DOM marker per house/bin, so zoomed-out views need the thinning logic in the "zoomed right out" block.

## Conventions

- Long comments explain *why* (past bugs, GPS edge cases, data-loss incidents). Keep them, and add one when fixing something subtle.
- Icons are `<img class="icon-img" src="name.png">`. Stream colours are Garbage red, Recycling yellow, FOGO green.
- New UI goes in the `ux2` layer as another IIFE that wraps existing globals. Don't restructure the earlier blocks.
