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
font export: every letter - including digits - decodes to an unrelated Unicode codepoint, so the run number
can't be read from the page text at all. `identify_garbage.py` works around this by geometry instead: it
gets the day from the PDF's filename (plain text, unaffected), then fits each page's route against *every*
Garbage run that services that day and keeps the match only if one run wins clearly and precisely (a cheap
normalised-correlation pass ranks all candidates, then a precise fit is run on just the top few, and the
winner must beat the runner-up by a wide margin). Most pages come back "ambiguous" and are skipped - that's
expected, not a bug; only genuinely confident matches feed into the boundary/street-mode data, since a wrong
guess here would inject a wrong route into a run's data.

Needs: `poppler` (`brew install poppler`) and Python with `numpy scipy shapely`.

```
python3 -m venv venv && venv/bin/pip install numpy scipy shapely
mkdir -p work && curl -sL "<SCRIPT_URL>?download=csv" -o work/master.csv     # the master property list
# put the PDFs in the repo root (or set ROUTEMAP_PDF_DIR), then:
venv/bin/python compare.py                    # Recycling + FOGO -> work/compare-results-{REC,ORG}.json, work/routes-m-{REC,ORG}.json
venv/bin/python identify_garbage.py           # Garbage (geometry-identified) -> work/compare-results-GAR*.json, work/routes-m-GAR*.json
venv/bin/python modes_export.py --write       # merge all three -> data/street-modes.json
venv/bin/python extend_boundaries.py --write  # stretch every stream's boundaries to the streets driven, split any resulting overlap down the middle -> data/run-boundaries.json (new `generated`)
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
- `lib.py` holds the shared geometry helpers (PDF parsing, the coarse+precise fit, the boundary/house loaders) that
  `compare.py`, `identify_garbage.py`, `modes_export.py` and `extend_boundaries.py` all import.
