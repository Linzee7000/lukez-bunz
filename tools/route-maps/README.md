# Route-map tools

Read the driver route maps (PDF, one page per run, made in Publisher) and use them to
(1) check the run boundaries and (2) build `data/street-modes.json`.

On the maps: **green** = streets driven, **purple** = reverse in / drive out, **orange** = drive in / reverse out.
The maps are not georeferenced, so each page is placed on the ground by fitting its route lines to that run's houses
(`compare.py`), good to roughly 5-20 m. Pages that show only part of a run (zoomed detail pages) fit badly and are skipped (fit > 20 m).

Needs: `poppler` (`brew install poppler`) and Python with `numpy scipy shapely`.

```
python3 -m venv venv && venv/bin/pip install numpy scipy shapely
mkdir -p work && curl -sL "<SCRIPT_URL>?download=csv" -o work/master.csv     # the master property list
# put the PDFs in the repo root (or set ROUTEMAP_PDF_DIR), then:
venv/bin/python compare.py            # -> work/compare-results.json, work/routes-m.json (and a per-page report)
venv/bin/python modes_export.py       # -> work/street-modes.json  (copy to data/street-modes.json)
venv/bin/python cover.py              # how many of each run's houses sit inside its boundary (needs work/master.csv)
```

Notes: recycling PDFs only so far (all ten day/week sets). The PDFs are found automatically in the repo root (or `ROUTEMAP_PDF_DIR`); to go faster run one copy per PDF with `ROUTEMAP_SUFFIX=-1.1 python compare.py "1.1 "` and so on (modes_export.py merges them). Regular recycling runs are keyed day + week + run; summer
recycle runs reuse the same numbers with no week, so never match them to a Week A/B page. Re-running `modes_export.py` replaces the
whole file, so run it with every PDF you have, not just the new ones.
