# Route-map tools

Read the driver route maps (PDF, one page per run, made in Publisher) and use them to
(1) check/extend the run boundaries and (2) build `data/street-modes.json`. Covers all three kerbside
streams: Recycling, FOGO (labelled "Organics" on the maps) and Garbage.

On the maps: **green** = streets driven, **purple** = reverse in / drive out, **orange** = drive in / reverse out.
The maps are not georeferenced, so each page is placed on the ground by fitting its route lines to that run's houses,
good to roughly 5-20 m. Pages that show only part of a run (zoomed detail pages) fit badly and are skipped (fit > 20 m).

**Recycling and FOGO** PDFs have a readable title ("Tuesday Run 219 Recycle WA" / "... Organics WA"), so
`compare.py` reads day/run/week straight off the page text.

**Garbage** PDFs (the ones from `1.0 GARBAGE - Apr26.zip`, exported to PDF one file per day) have a broken
font export: every character decodes to an unrelated Unicode codepoint, so "Monday Run 201 Garbage" extracts
as `DŽŶĚĂǇZƵŶϮϬϭ'ĂƌďĂŐĞ`. It looks like gibberish but the substitution is *consistent* and the same in all
five day files, so `garbage_font.py` simply undoes it and `identify_garbage.py` reads the run number straight
off the page - 93 of 96 pages. Geometry is then only used to place the page on the ground. Pages with no
title block (zoomed detail pages) still fall back to the old approach of identifying the run by fitting the
route against every run that services that day and keeping only a clear, precise winner. Pages that can't be
*placed* well (fit > 15 m) are still skipped even when their run is known.

Needs: `poppler` (`brew install poppler`) and Python with `numpy scipy shapely`.

```
python3 -m venv venv && venv/bin/pip install numpy scipy shapely
mkdir -p work && curl -sL "<SCRIPT_URL>?download=csv" -o work/master.csv     # the master property list
# put the PDFs in the repo root (or set ROUTEMAP_PDF_DIR), then:
venv/bin/python compare.py                    # Recycling + FOGO -> work/compare-results-{REC,ORG}.json, work/routes-m-{REC,ORG}.json
venv/bin/python identify_garbage.py           # Garbage (geometry-identified) -> work/compare-results-GAR*.json, work/routes-m-GAR*.json
venv/bin/python modes_export.py --write       # merge all three -> data/street-modes.json
venv/bin/python extend_boundaries.py --write  # stretch every stream's boundaries to the streets driven, split shared road down the middle -> data/run-boundaries.json (new `generated`)
venv/bin/python cover.py                      # Recycling only: how many of each run's houses sit inside its boundary
```

Notes:
- The PDFs are found automatically in the repo root (or `ROUTEMAP_PDF_DIR`) by filename (`RECYCLE`, `ORGANICS`, or
  `garbage` + a day name). To go faster, run one copy per PDF/day with `ROUTEMAP_SUFFIX=-1.1 python compare.py "1.1 "`
  (or `ROUTEMAP_SUFFIX=-Monday python identify_garbage.py Monday`) - `modes_export.py`/`extend_boundaries.py` merge
  every `work/*-{REC,ORG,GAR}*.json` file, whatever they're suffixed.
- `ROUTEMAP_STREAMS=ORG python compare.py` processes only that stream (skip re-running Recycling if it's already done).
- Regular Recycling/FOGO runs are keyed day + week + run; Garbage has no week; summer recycle runs reuse regular
  recycle run numbers with no week of their own - never match any of these to the wrong key shape.
- Re-running `modes_export.py --write` replaces the whole `street-modes.json`, so run it with every stream's data you
  have, not just the newest.
- `extend_boundaries.py` reads `ROUTEMAP_BASE_BOUNDARIES` (default: the live `data/run-boundaries.json`) as the
  boundaries to extend from - point it at an older snapshot to redo an extension from scratch rather than stacking
  on an already-extended file.
- The overlap split uses each run's own **lot outlines** (from `data/parcels.json`, see `tools/parcels/`)
  as the Voronoi sites, sampled every 2 m - not its house pins. Houses on opposite sides of a street are
  staggered, so a bisector between two rows of *points* is a sawtooth; between two rows of *frontages* it is
  the road's centreline, which is what the maps mean and what the driver expects. Points two runs both claim
  (a shared property line) are dropped, and duplicates are snapped out first - a duplicate point makes
  shapely's Voronoi fail outright, which silently left whole groups unsplit.
- `RESOLVE_ALL_OVERLAPS=0` restricts the split to overlaps the street-extension itself created. The default
  also sweeps up overlaps that were already in the base shapes, but only between runs of the same stream,
  day **and** week - A and B weeks are different fortnights and may legitimately sit on top of each other.
- `lib.py` holds the shared geometry helpers (PDF parsing, the coarse+precise fit, the boundary/house loaders) that
  `compare.py`, `identify_garbage.py`, `modes_export.py` and `extend_boundaries.py` all import.

**Tried and dropped (2026-09-26): placing the part-run Garbage pages automatically.** 56 of the 60 skipped Garbage
pages have their run number read fine but fail the fit (40-60 m), because they show only part of the run, and `fit()`
scores a placement by how close *all* the run's houses are to the drawn route. A scorer for part-pages (route -> real
OSM roads from `work/roads.json` + footprint houses -> route, zoom limited to 1/8-1.3x of the run's overview) was tested
by cutting pieces out of pages that *do* place well and re-placing them: only 1 of 12 came back within 25 m (median
error ~1.4 km). Suburban streets look too alike for a piece of route to be placed on shape alone. Getting these pages in
needs either the maps' source files (if they carry coordinates) or placing each page by hand once.
