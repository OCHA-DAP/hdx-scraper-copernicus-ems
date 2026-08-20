# 0001: Replace uploaded/re-hosted product resources with direct Copernicus download links

## Status

Accepted — 2026-08-19

## Context

Copernicus EMS asked that HDX's download list use their own tracked download
links (so they can measure download statistics) instead of this pipeline
downloading their products zip and re-uploading individual files. An initial
investigation (2026-08-18) found the API's `downloadPath` field alone
insufficient — stale/wrong in at least one real case (404) and only ever
covering one combined zip, not the four separate per-format files (Vector
data / GeoPackage / Map / Summary Table) their own viewer offers, and the
true per-format product code doesn't appear anywhere in the public API.
Copernicus was asked directly for the real URL scheme and replied with a
template; verified directly against the live backend using real activation
data: the delivery-round segment is still required (Copernicus's own
template omitted it, but `downloadPath` already contains it correctly), the
working `?type=` value for GeoPackage is `gpkg` not `geopackage`, and not
every product/round has every format (must be probed per product/format,
not predicted from other fields).

## Decision

Replace the download-zip → extract → re-upload flow entirely. Every
resource becomes a `Link` (URL-only) resource built from
`f"{downloadPath}?type={format}"`, probed per (product, format) via a
minimal ranged existence check. Enumerate available products/formats
directly from the detail API's `aois[].products[]` array rather than
parsing filenames out of a downloaded zip.

## Consequences

Retires almost all of `product_extractor.py` (renamed `product_links.py`) —
zip flattening, shapefile-sibling bundling, per-layer explosion,
GeoPackage-supersedes-layers logic, and duplicate-entry disambiguation all
become unnecessary once nothing is downloaded or unpacked; a prior bug fix
targeting that same zip-flattening/dedup logic (2026-08-12, see
`docs/plans/2026-08-12-fix-grm-fixture-and-shapefile-dedup-bug.md`) is now
moot. `api_retriever.py`'s existence probe deliberately bypasses
`Retrieve`'s save/fixture replay layer, since that layer has no notion of
"does this exist" — tests instead monkeypatch the probe function itself.
One older activation (`EMSR838`) behaves inconsistently with `?type=`
probing (404s where the combined zip has the file); accepted as a
documented limitation since only newly-discovered activations are ever
processed going forward.
