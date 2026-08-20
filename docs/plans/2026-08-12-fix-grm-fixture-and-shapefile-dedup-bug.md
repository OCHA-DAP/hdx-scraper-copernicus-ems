**Note (retroactive, added when this plan was archived here):** the module
this plan modifies, `product_extractor.py`'s zip-flattening/shapefile-sibling
dedup logic (`_flatten_nested`/`_flatten_to_scratch`), was retired entirely
by the 2026-08-19 rewrite to direct Copernicus download links — see
`docs/decisions/0001-direct-copernicus-download-links.md`. Kept here as
historical record only; this bug and its fix no longer apply to current code.

---

# Fix GRM test fixture and shapefile-sibling dedup bug

## Context

Follow-up to the HDXPIPE-142 review work: while sanity-checking the previous changes against real Copernicus data (`saved_data/activation-emsr900.json`), two issues were flagged for follow-up rather than fixed immediately:

1. The test fixture `tests/fixtures/input/activation-emsr884.json` has a product typed `"GRM"` at AOI00 — not a real, documented Copernicus product-type code (only DEL/GRA/FEP/REF are documented; confirmed against Copernicus's own portfolio page in the prior session, and confirmed here that **no** real saved activation in `saved_data/` ever uses `GRM`). It's almost certainly a mistake in this hand-built fixture.
2. While running the pipeline against real EMSR900 data, a stray orphaned resource appeared (`EMSR900_AOI03_DEL_MONIT01_observedEventP_v1__dup2.xml`, extracted as a bare standalone file instead of being bundled with its shapefile siblings). Investigation (reproduced directly against `saved_data/emsr900_products.zip`) found the root cause: `_resolve_name` in `product_extractor.py` decides "same content vs. genuinely different content" **per individual filename**, with no notion of a shapefile layer's sibling group (`.shp/.shx/.dbf/.prj/.sld/.lyr/.xml` + split-out `.json`). In the observed case this only mislabels one file (no data lost), but the same root cause was reproduced as a **worse case**: if a future re-delivery changes `.shp`+`.shx` (geometry) while `.dbf` (attributes) stays byte-identical, the current code produces a shapefile zip bundle **missing its `.dbf` entirely** — a broken, unopenable shapefile. This is a real correctness bug, not just cosmetic, so it needs fixing.

## Change 1: Fix the GRM fixture

`tests/fixtures/input/activation-emsr884.json`'s AOI00 product (id 2611) will have its `"type"` changed from `"GRM"` to `"GRA"` — chosen because every other AOI in this same activation already uses `GRA`, and AOI00's own layer names (`groundMovementA`, `notAnalysedA`) are consistent with a grading/damage-assessment product, keeping the fixture internally coherent. Update every other `"GRM"` occurrence within that one product object (images `fileName`s, `downloadPath`, `layers[].name`) to `GRA` for consistency, since none of these fields are actually read by the pipeline (confirmed: only `type`, as encoded in the zip's *filename*, drives behavior) — this is purely about not leaving a self-contradictory fixture.

`tests/fixtures/input/emsr884_products.zip` (a 34-byte dummy placeholder, single entry) gets its entry renamed from `EMSR884_AOI00_GRM_PRODUCT_v1.tif` to `EMSR884_AOI00_GRA_PRODUCT_v1.tif` (same dummy bytes) — done with a small Python `zipfile` script during implementation, not a text edit.

Since `GRA` is now a *recognised* product-type code, downstream test expectations that relied on this specific file being *unrecognised* change:
- `tests/test_pipeline.py::test_generate_datasets` — resource name becomes `EMSR884_AOI00_GRA_PRODUCT_v1.tif`; the description is no longer the generic fallback but the specific one: `"GeoTIFF containing the grading (damage assessment) map for Area of Interest 0 of the Earthquake in Venezuela (EMSR884), from the initial delivery."` (AOI00 renders as "Area of Interest 0" — expected given `describe_resource`'s existing `int(aoi[len("AOI"):])` logic; not something this change needs to address).
- `tests/test_product_extractor.py::test_direct_file_passthrough` — expected extracted filename becomes `EMSR884_AOI00_GRA_PRODUCT_v1.tif`.
- `tests/test_product_extractor.py::TestDescribeProductTypes::test_no_recognised_types` and `TestDescribeResource::test_falls_back_for_unrecognised_type_code` currently reuse the `"EMSR884_AOI00_GRM..."` string as their "unrecognised code" example — since that string will no longer represent real fixture data, both are updated to use a clearly-synthetic, decoupled placeholder filename (e.g. `"EMSR999_AOI01_XXX_PRODUCT_v1.tif"`) instead, so the tests keep testing the *fallback path* without implying `GRM`/`EMSR884` still means anything special.

## Change 2: Fix the shapefile-sibling dedup bug

Recommended approach (Option A — targeted fix scoped to `_flatten_nested`, per investigation): make the dedup/disambiguation decision atomic per **stem-group** (all files sharing a base name across extensions) within a single nested zip occurrence, instead of per individual file. This fully covers the diagnosed bug — confirmed the failure is entirely inside `_flatten_nested`'s per-file resolution — without the much larger diff and regression surface of restructuring the whole two-pass extraction pipeline (Option B), which would also only buy protection against a cross-boundary scenario (a top-level flat file colliding in stem with a nested zip's internal file) that the module's own docstring says never happens in real Copernicus archives.

In `src/hdx/scraper/copernicus/ems/product_extractor.py`:

- `_flatten_to_scratch` (currently :207-227): add a second dict `seen_groups = {}` alongside the existing `seen`, and pass `seen_groups` (not `seen`) into `_flatten_nested`. `seen` continues to be used only for top-level per-entry resolution via the existing `_resolve_name` (unchanged, still handles the outer zip's own direct entries).
- `_flatten_nested` (currently :230-240): rewrite to bucket `nested.infolist()` by stem (`Path(Path(info.filename).name).stem`) *before* resolving any names, then resolve+extract one bucket at a time via a new `_resolve_group_names` helper, instead of calling `_resolve_name` per entry.
- New `_resolve_group_names(seen_groups: dict, stem: str, infos: list[zipfile.ZipInfo]) -> list[tuple[ZipInfo, str]] | None`:
  - Fingerprint the whole group: `tuple(sorted((Path(info.filename).name, info.CRC, info.file_size) for info in infos))`.
  - If this fingerprint was already seen for this stem → return `None` (drop every member of the group together; log once: `"Duplicate entry group for {stem!r} ({n} file(s)) in archive, skipping repeat"`).
  - Else if the stem has prior fingerprint(s) but not this one → assign the *same* `__dup{n}` suffix (n = count of prior distinct fingerprints + 1, preserving today's numbering) to every member; log once: `"Entry group for {stem!r} reused for different content; keeping both, this occurrence extracted with suffix {suffix!r} ({filenames})"`.
  - Else (first time this stem appears) → every member keeps its original name.
  - Append the fingerprint to `seen_groups[stem]` and return the list of `(info, resolved_name)` pairs.
- `_flatten_nested` extracts each `(info, resolved_name)` pair via the existing, unchanged `_extract_flat`.
- `_extract_flat` and `_materialize_groups` are unchanged — `_materialize_groups`'s existing stem-based grouping and `_SHAPEFILE_EXT in members` bundling logic is exactly what this fix guarantees will now always see complete sibling sets (or none).

### Tests

Add to `tests/test_product_extractor.py::TestProductExtractor` (building nested-zip bytes in-memory, matching the existing in-test zip-building style):
- A test where an outer zip has two entries with the same name, each a nested zip containing a shapefile-layer family (`.shp/.shx/.dbf/.prj/.xml`); between occurrences all members are byte-identical except `.xml`. Assert the resulting `__dup2` shapefile bundle's `namelist()` contains **all** the `__dup2`-suffixed siblings, not just the changed one — locking in that no sibling is orphaned.
- A "worse case" test where `.shp`/`.shx` differ between occurrences but `.dbf` is identical. Assert the `__dup2` bundle contains all three of `.shp/.shx/.dbf` and that they're a self-consistent (matching) triplet from the *second* occurrence — proving the fix, since today's code produces a bundle missing `.dbf`.
- A "no false positive" test: two occurrences whose group members are all byte-identical → only one copy of each sibling is extracted, nothing gets a `__dup2`.
- Re-run (no changes expected/needed) `test_dedup_identical_entry_kept_once`, `test_name_collision_with_different_content_keeps_both` (top-level path, untouched), `test_nested_zip_grouping_and_bundling`, and `test_fep_dropped_when_more_accurate_monitoring_product_available` / `..._monitoring_product_available` (single-occurrence nested path) as regression guards.

## Verification

- `uv run pytest -q` — full suite green, including the new dedup-group tests and the updated GRM→GRA fixture assertions.
- `uv run ruff format --check . && uv run ruff check .`
- Re-run the manual sanity check against `saved_data/activation-emsr900.json` + `saved_data/emsr900_products.zip` (same ad hoc script used in the prior session) and confirm: (a) `EMSR900_AOI03_DEL_MONIT01_observedEventP_v1` no longer produces a standalone orphaned `.xml` resource — it's either fully collapsed as a duplicate or fully bundled with its `__dup2` siblings into one shapefile zip; (b) the resource list/descriptions are otherwise unchanged from the previous verification run.
