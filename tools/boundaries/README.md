# tools/boundaries: neat run boundaries

Takes `data/run-boundaries.json` (property-line builder + `tools/route-maps/extend_boundaries.py`) and turns it into
one tidy map: straight edges, and wherever two runs meet (same stream or not) they use the very same line.

Needs Python 3 with `shapely` (2.1+), `numpy` and, for the pictures, `Pillow`. Run from this folder:

```bash
python3 build_atoms.py            # ~6 min: writes cl.pkl (and layer_*.pkl) next to the scripts
python3 straighten.py final.json 4 3500 3 60   # ~1.5 min: passes, biggest triangle m2, house clearance m, spike angle
```

Then copy `final.json`'s `boundaries` and `extras` into `data/run-boundaries.json`, keep `aliases`, and **change
`generated`** (devices only take a shared set once per `generated` value).

## What it does

1. **Each stream cleaned as one partition** (`neat.clean_group`): thin road stubs with fewer than three of the run's
   houses are dropped, overlaps go to the run with more of its own houses there, loose crumbs go, and the gaps between
   runs are filled by both sides growing at the same pace so they meet in the middle.
2. **Atoms.** The three streams are laid over each other. Every piece of ground is then one "atom": the same garbage
   run, recycling run and FOGO run all over it. Atoms nobody lives in are only the slivers between two streams' lines,
   so each is folded into the neighbour it shares most edge with. That is what makes different streams share one line.
3. **Straightening** (`neat.simplify_lines`, run several times): a corner is removed only if the triangle it sweeps
   holds no house (with a few metres' clearance) and no other line's corner. So lines go straight wherever nothing
   lives, and **no house ever changes run**. Sharp spikes with no house in them are cut off whatever their size.
4. A run is the union of its atoms.

Houses come from the master CSV in the repo root (`Lat`, `Lng`, day, week cycle and the three run columns). Runs with
fewer than 30 houses in that CSV cannot be checked against anything, so they are left exactly as drawn.

`render.py` draws a before/after picture of any bounding box; `straighten.py` prints, per stream, how many houses sit
inside their own run before and after.
