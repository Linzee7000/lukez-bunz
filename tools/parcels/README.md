# Parcel tools

Ships the Vicmap lot boundaries for the service area as `data/parcels.json`, so the property
boundaries layer works on a fresh phone and with no signal instead of fetching thousands of tiles
from the Vicmap Parcel ArcGIS service. The app still falls back to that service for anything the
file doesn't cover, so a new estate isn't blocked on regenerating this.

The file holds every lot's outline plus which lot each house sits on - the same match the app makes
itself, so a phone loading this starts with the matching already done. It is also what
`tools/route-maps/build_boundaries.py` uses to build the run boundaries.

Coordinates are stored as deltas scaled by 1e5 (~1 m; worst measured round-trip error 0.71 m) and
everything derivable is dropped, which is what takes it from 26 MB to ~2.5 MB gzipped.

## Regenerating

Lot lines rarely change, so this only needs redoing when they do (subdivisions, new estates).

```
python3 receive.py            # waits on 127.0.0.1:8765 for the export
```

Then open the app (with the parcel cache populated - the phone or browser that has been doing the
matching) and in its console:

```js
await fetch('http://127.0.0.1:8765/save', {
  method: 'POST', headers: {'content-type': 'application/json'},
  body: JSON.stringify(lbParcels._t.getStore())
})
```

`receive.py` writes `work/store-raw.json` and exits. Then:

```
python3 pack.py               # -> work/parcels.json, prints raw and gzipped size
python3 pack.py --write       # ...and replaces ../../data/parcels.json
```

The app applies the shipped file once per its `generated` value (recorded as `store.shared` in
IndexedDB) and only ever fills gaps - a phone that has matched lots the file doesn't have keeps its
own. Nothing else needs changing when the file is regenerated.
