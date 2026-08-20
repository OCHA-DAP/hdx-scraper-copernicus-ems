**Note (retroactive, added when this plan was archived here):** the
showcase-vs-iframe decision from this plan is recorded as
`docs/decisions/0002-showcase-link-not-iframe-embed.md`. The download-links
investigation below was superseded by Copernicus's reply — see the
2026-08-19 follow-up plan
(`docs/plans/2026-08-19-replace-uploaded-resources-with-direct-links.md`)
and `docs/decisions/0001-direct-copernicus-download-links.md`.

---

# Respond to Copernicus EMS feedback: viewer embed + download links

## Context

Copernicus EMS (the data provider) gave feedback on the HDX dataset pages this
pipeline produces:

1. The interactive-viewer embed (`Dataset.set_custom_viz`, pointing at
   `mapping.emergency.copernicus.eu/activations/<code>/`) never renders — the European
   Commission's CSP (`frame-ancestors 'none'`) blocks framing, and that policy is fixed on
   their end. They suggested a plain "Open in full screen"-style clickable button instead
   of an iframe — which is exactly what this pipeline's existing StoryMap `Showcase`
   already does, just not yet for the viewer link itself.
2. They'd like the resource-download list to use *their own* download links (so they can
   track download statistics), shown grouped by AOI so the list stays short — mirroring
   what their own viewer's download panel shows, instead of every individual layer file
   currently exploded into its own HDX resource.

This plan covers: (a) fixing the embed now, since it's a clear, low-risk win, and (b)
investigating whether the API already exposes what's needed for (2) — it turns out it
doesn't (see below), so the reply to Copernicus reports that concretely and asks how to
get real links, rather than guessing.

## Investigation finding (updated after testing the real buttons): `downloadPath` is unreliable — don't build against it

The user manually clicked all four buttons on the real viewer card for EMSR884/AOI00
("Grading", v2) and shared the four downloaded files:

- Vector data → `EMSR884_AOI00_GRM_PRODUCT_v2.zip` (139 MB, 35 entries: every shapefile
  layer's sidecar set plus a `.tif`, no gpkg/xlsx/pdf)
- GeoPackage → `EMSR884_AOI00_GRM_PRODUCT_v2.gpkg` (8.4 MB)
- Map → `EMSR884_AOI00_GRM_PRODUCT_500000_map_v2.pdf`
- Summary Table → `EMSR884_AOI00_GRM_PRODUCT_summaryTable_v2.xlsx`

Two things stand out:

1. **The four buttons are four distinct files**, not one zip split client-side — Vector
   data omits the GeoPackage/summary table/map entirely, confirming the card really does
   offer 4 separate downloads as the screenshot showed.
2. **All four use the product code `GRM`, but the detail API's `type` field for this exact
   product says `"GRA"`**, and its `downloadPath` field is
   `.../AOI00/GRA_PRODUCT/EMSR884_AOI00_GRA_PRODUCT_v2.zip`. I checked whether that
   `downloadPath` URL actually resolves (`curl` through the backend's redirect to its
   signed S3 URL — the backend returns HTTP 302 with a presigned S3 link, then S3 itself
   returns 200/206 if the object exists or 404 if it doesn't): **`downloadPath` 404s — the
   file it points to doesn't exist.** The real file lives at
   `.../AOI00/GRM_PRODUCT/EMSR884_AOI00_GRM_PRODUCT_v2.zip` (confirmed 206, and it's the
   same "Vector data" zip the user downloaded), under the true internal product code
   (`GRM` — apparently a Ground Motion/deformation product, distinct from plain grading),
   which the public API never exposes; it only ever reports the coarser `type: "GRA"`.
   I could not find a working path for the GeoPackage/Map/Summary Table files by guessing
   filename variations of the same pattern (all 404's) — confirming a URL can't be reliably
   *derived*, only used once given directly.

**Conclusion: `downloadPath` cannot be trusted as a source of download links** — it's
stale/wrong on at least this real example, and even when right it only ever covers one
combined bundle, not the four separate files the UI actually offers. We also cannot
reconstruct the four per-format URLs ourselves, since the true product code (`GRM` here)
that appears in the real file paths isn't present anywhere in the public API response.

This means the "use your own tracked download links" ask is **not implementable purely
from data already in the public API** — it genuinely needs Copernicus to either fix/expose
correct per-format URLs in the API (e.g. a `vectorDataPath`/`gpkgPath`/`mapPath`/
`summaryTablePath` alongside `downloadPath`, all pointing at real objects), or tell us the
URL rule they actually use. I stopped short of further guessing at their backend's URL
structure by brute force once this became clear, since blind probing of a third party's
production infrastructure isn't a good way to reverse-engineer this - it's better to just
ask them directly (see reply below), or capture the four real network requests once
(e.g. via browser devtools "Copy as cURL" on each button) if a quick concrete example would
help move their answer along.

Also worth noting: the screenshot's card metadata (title "Grading", "Image acquisition
time", "Product Delivery", "Version 2") maps cleanly onto fields we already have per
product entry (`images[].acquisitionTime`, `version.deliveryTime`, `version.number`) —
so the grouping unit itself (one card per AOI + product + round) is not in question, only
the download URLs are.

**Action taken on this**: no code changes for the download-link restructuring in this
round — it can't be built from the public API as it stands. The reply below lays out what
was found (including the stale `downloadPath`, as a bug report) and asks Copernicus how to
get real per-format links.

## Code change: replace the broken viewer embed with a Showcase button

In `src/hdx/scraper/copernicus/ems/pipeline.py`'s `_generate_dataset`:

- Remove the `dataset.set_custom_viz(...)` call (lines ~232-236) — it can never render, so
  keeping it around is misleading rather than harmless.
- Add a second `Showcase`, alongside the existing StoryMap `report_link` one, linking to
  `https://mapping.emergency.copernicus.eu/activations/{code}/` — giving the same
  clickable "open in full screen" UX the org showed for the StoryMap, this time for the
  interactive viewer. Reuse the same icon (`ccl-icon-emergency.svg`) and tagging pattern
  already used for the `report_link` showcase.
- `_generate_dataset` currently returns a single `(dataset, showcase)` pair. Change this to
  `(dataset, showcases)` where `showcases` is a list (0, 1, or 2 items depending on whether
  `report_link` was present — the viewer showcase itself is unconditional, since every
  activation has a code).

Follow-through changes required by that signature change:
- `src/hdx/scraper/copernicus/ems/__main__.py` (`main()`, ~line 72): change
  `for dataset, showcase in pipeline.generate_datasets():` to unpack `showcases` and loop
  `for showcase in showcases: showcase.create_in_hdx(); showcase.add_dataset(dataset)`.
- `tests/test_pipeline.py`: update every place that unpacks `(dataset, showcase)` /
  `(dataset, _showcase)` to the new list shape, and:
  - Remove the `dataset.get_custom_viz() == "https://mapping.emergency.copernicus.eu/..."`
    assertions (lines ~72-75, ~151-154) — the call no longer exists.
  - Add an assertion that one of the returned showcases has
    `url == "https://mapping.emergency.copernicus.eu/activations/EMSR884/"`.
  - Keep the existing StoryMap-showcase URL assertion, just locating it in the new list.
- `CLAUDE.md`'s Architecture section currently documents `set_custom_viz` and its known
  CSP-framing failure as a `TODO`/known-limitation — update that paragraph to describe the
  showcase-button approach instead, and drop the "doesn't currently render" caveat since it
  will no longer apply.

No changes needed to `api_retriever.py` or `product_extractor.py` for this part.

## Reply to send to Copernicus

Draft (for the user to review/edit before sending — not sent by this plan):

> Thanks for the feedback — both points make sense.
>
> On the viewer embed: understood that the frame-ancestors policy is fixed on the
> Commission's side and isn't something we can negotiate around. We'll drop the broken
> iframe embed and instead add a clickable button/link to the dataset page that opens your
> interactive viewer for that activation in full screen — the same "click to explore"
> pattern we already use for the StoryMap link you saw on the page.
>
> On the download links: we looked into building this from your public activation API, and
> want to flag two things we found along the way.
>
> The grouping unit works out cleanly — one card per AOI + product + round, which lines up
> with each entry in the API's `aois[].products[]` array (the acquisition time, delivery
> time and version on your card all match fields already in that entry).
>
> The actual download URLs don't, though. We downloaded all four buttons from a real card
> (EMSR884, AOI00, "Grading" v2) to compare against the API: Vector data, GeoPackage, Map
> and Summary Table are four separate files, all named with product code `GRM`. But that
> product's `type` field in the API says `"GRA"`, and its `downloadPath` field
> (`.../AOI00/GRA_PRODUCT/EMSR884_AOI00_GRA_PRODUCT_v2.zip`) 404s — it doesn't point at a
> real file. The actual file lives at `.../AOI00/GRM_PRODUCT/EMSR884_AOI00_GRM_PRODUCT_v2.zip`
> instead, under a product code (`GRM`) that isn't exposed anywhere in the API response we
> get. So `downloadPath` looks like a bug on your side for at least this case, and even
> where it's correct it only ever gives one combined zip, not the four separate files your
> UI actually offers.
>
> We don't want to guess further at your URL structure by brute-forcing filename patterns
> against your production backend. Could you either (a) expose the correct, real per-format
> URLs in the API — e.g. `vectorDataPath`/`gpkgPath`/`mapPath`/`summaryTablePath` alongside
> (or fixing) `downloadPath` — or (b) point us at documentation for the URL scheme your own
> viewer uses? A "Copy as cURL" of the four button requests from your browser's network tab
> for one activation would also be enough for us to confirm the pattern.

## Verification

- `uv run pytest tests/test_pipeline.py` after the showcase-signature change, plus the full
  suite (`uv run pytest`) since `__main__.py`'s loop shape changes too.
- `uv run ruff check` / `uv run ruff format`.
- Manually inspect one generated `Dataset`/`Showcase` pair (e.g. via the existing
  `test_generate_datasets` fixture data) to confirm two showcases come back for an
  activation with a `reportLink`, and one for an activation without.
