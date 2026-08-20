**Note (retroactive, added when this plan was archived here):** this plan's
core decision is recorded as
`docs/decisions/0001-direct-copernicus-download-links.md`.

---

# Replace uploaded product resources with direct Copernicus download links

## Context

Copernicus EMS gave feedback (relayed and investigated in the earlier `swift-percolating-hamming` plan/session) asking that the HDX dataset's download list use *their own* tracked download links instead of this pipeline downloading their products zip and re-uploading individual files, so they can measure download statistics. That earlier session found the API's `downloadPath` field alone wasn't enough (it only ever gives one combined zip, not the four separate per-format files their own viewer UI offers: Vector data / GeoPackage / Map / Summary Table) and asked Copernicus for the real URL scheme.

Copernicus replied with:
```
https://rapidmapping.emergency.copernicus.eu/backend/EMSR{xxx}/AOI{yy}/{FEP/DEL/GRA/REF}/EMSR{xxx}_AOI{yy}_{FEP/DEL/GRA/REF}_{version}.zip?type={vectors/pdf/xlsx/geopackage}
```

I verified this directly against the live backend (using real activation data in `saved_data/`, not guesses):

- **The delivery-round segment (`PRODUCT`/`MONIT01`/...) is still required** — Copernicus's template omitted it, but dropping it from the path/filename 404s. The existing `downloadPath` field per product already contains the correct, fully-formed base URL (e.g. `.../AOI01/DEL_PRODUCT/EMSR907_AOI01_DEL_PRODUCT_v1.zip`) — so we should build from `downloadPath` directly rather than hand-formatting the URL ourselves.
- **`?type=` values**: `vectors`, `pdf`, `xlsx` work as given; `geopackage` does **not** — it silently falls back to returning the full combined zip. The working value is **`gpkg`**. Confirmed by comparing the S3 redirect target for each query value.
- **Appending `?type=<value>` to `downloadPath` redirects to a genuinely different, specific S3 object** (e.g. `.../processed/EMSR907_AOI01_DEL_PRODUCT_v1.gpkg`, `.../processed/..._summaryTable_v1.xlsx`) for recent (Aug-2026) activations — this is real per-format linking, not a client-side split of one file.
- **Not every product/round has every format.** A monitoring-round update sometimes only ships a map (`pdf`), with `vectors`/`gpkg`/`xlsx` returning a clean 404 straight from the backend (not a redirect). This must be probed per (product, format) — it can't be reliably predicted from other API fields (a `layers`/`mapsCount`-based guess was tested and found to disagree with reality in at least one case).
- **One older (Jul-2026) activation (`EMSR838`) behaved inconsistently**: `?type=vectors`/`xlsx` 404'd even though the plain combined-zip download (no `?type=`) contained those exact files. This looks like a backend quirk specific to older activations. Since this pipeline only ever processes newly-discovered activations from the RSS feed going forward, this is a documented, accepted limitation rather than something to engineer around.
- `REF` (the fourth type Copernicus mentioned) never appeared in any real data sampled — handled generically, unverified.

**Decision (confirmed with the user):** this fully replaces the current download-zip → extract → re-upload flow. No resources are uploaded any more; every resource is a `Link` (URL-only) resource pointing straight at Copernicus's backend. This retires almost all of `product_extractor.py` (zip flattening, shapefile-sibling bundling, per-layer explosion, GeoPackage-supersedes-layers logic, dedup/`__dup` handling) since none of it applies once we're no longer downloading or unpacking anything — we now enumerate available products/formats straight from the detail API's `aois[].products[]` array instead of parsing filenames out of a zip.

## Design

### `api_retriever.py` — resolve and validate direct links instead of downloading the zip

- Remove the `productsPath` zip download entirely.
- For each product entry across `detail["aois"][].products[]`, if it has a `downloadPath`, probe `f"{download_path}?type={fmt}"` for `fmt` in `("vectors", "gpkg", "pdf", "xlsx")` and attach a `product["links"] = {fmt: url, ...}` dict containing only the formats that resolved. Products with no `downloadPath` (not feasible) get `links = {}`.
- Existence probe: a small `_url_exists(url)` helper doing a minimal ranged request (`self._retriever.downloader.setup(url, headers={"Range": "bytes=0-1"})`, `close_response()` after), returning `True`/catching `DownloadError` → `False`. This deliberately bypasses `Retrieve`'s save/fixture layer (`download_file`/`download_json`) because that layer has no notion of "does this exist" — in `use_saved=True` mode it always returns a path unconditionally, so it can't represent "this format is missing." This is a small, explicit exception to the project's usual no-mocking convention: tests will monkeypatch `APIRetriever._url_exists` itself (not the HTTP layer) to exercise the skip/fallback logic, since there's no fixture equivalent for a boolean existence check.
- Drop an activation entirely if none of its products resolved any links (mirrors today's "no products archive available" skip).
- `activations[code] = {"detail": detail}` — no more `zip_path`.

### `product_extractor.py` → rename to `product_links.py`

Same rename for `tests/test_product_extractor.py` → `tests/test_product_links.py`. The module's job changes from "explode a zip into files" to "describe and order the (product, format) links resolved by `api_retriever`." Everything about nested-zip flattening, shapefile sibling bundling, per-layer explosion, GeoPackage-supersedes-per-layer, and duplicate-entry disambiguation is deleted — none of it applies when nothing is downloaded or unpacked. What's kept/rebuilt, all operating on the structured product dicts (no more filename regex parsing — `aoiNumber`, `type`, `monitoring`, `monitoringNumber` come straight from the API):

- `_PRODUCT_TYPE_NOTES` / a type-label map for `DEL`/`GRA`/`FEP`, with a generic fallback (`f"{type} product"`) for codes we haven't seen documented (`GRM`, which already appears in real data; `REF`, which hasn't) — more forward-compatible than the old regex, which could only recognise the three hardcoded codes at all.
- Format labels/extensions matching Copernicus's own four button labels: `vectors` → "Vector data (zipped shapefile)" / `.zip`, `gpkg` → "GeoPackage" / `.gpkg`, `pdf` → "PDF map" / `.pdf`, `xlsx` → "Summary table (spreadsheet)" / `.xlsx`.
- `select_products(aois) -> list[dict]`: flattens `aois[].products[]`, drops any with empty `links`, and drops `FEP` products for an AOI number where a `DEL`/`GRA` product also exists for that same AOI (same rule as today's `_MORE_ACCURATE_TYPES` logic, just matched on `aoiNumber`/`type` directly instead of parsed filenames).
- `resource_title(product, format_key, resource_prefix)` / `describe_resource(product, format_key, code, activation_name)`: same purpose as today's functions, rebuilt against the product dict + format key instead of a file path.
- `resource_sort_key(product, format_key)`: `(aoiNumber, monitoringNumber if monitoring else 0, format_rank)` where `format_rank` keeps today's ordering (GeoPackage, then spreadsheet, then vectors, then PDF last).
- `describe_product_types(products)`: same dataset-notes snippet, built from the set of `type` values present across the selected products instead of parsed filenames; keep the "prefer the GeoPackage" note, gated on whether any selected product has a `gpkg` link.

### `pipeline.py`

- Constructor drops `temp_dir` (no longer used).
- `_generate_dataset`: replace the `zip_path`/`extract_product_files` block with `product_links.select_products(detail.get("aois") or [])`; skip the activation (as today) if the selected list is empty.
- Resource loop iterates `(product, format_key)` pairs from the selected products, sorted by `resource_sort_key`. For each, build a `Resource` with `name`/`description` from `product_links`, set `resource["url"] = f"{product['downloadPath']}?type={format_key}"`, and `resource.set_format(...)` (`vectors`→`"shp"`, `gpkg`→`"geopackage"`, `pdf`→`"pdf"`, `xlsx`→`"xlsx"` — matches today's format strings) — no `set_file_to_upload` call at all, which is what makes it a Link resource. The `try/except HDXError` around format-guessing goes away since these four formats are always valid, known HDX formats (no more "couldn't map format" fallback needed).
- `dataset.preview_off()` stays, but the comment changes: it's no longer a "TODO, do better later" — with zero uploaded/hosted resources, HDX has nothing it *could* preview, so this is simply correct now, not a compromise.

### `__main__.py`

- `Pipeline(configuration, activations, tempdir)` → `Pipeline(configuration, activations)`. `tempdir` is still needed for the `Retrieve` construction (detail JSON downloads), just no longer passed to `Pipeline`.

### Tests

- `tests/test_api_retriever.py`: replace the `zip_path is not None` assertions with checks against `detail["aois"][...]["products"][...]["links"]`. Monkeypatch `APIRetriever._url_exists` per test to control which (product, format) combinations "exist," covering: a normal case (some formats resolve), a format that 404s and is excluded, and an activation where nothing resolves and is dropped entirely.
- `tests/test_product_links.py` (renamed): rewrite around `select_products`/`resource_title`/`describe_resource`/`resource_sort_key`/`describe_product_types` operating on product dicts (constructed inline in the test, matching the real API shape) instead of files on disk — no more zip fixtures or `tmp_path` extraction needed for this file.
- `tests/test_pipeline.py`: update fixture activation data / mocked `activations` dicts to the new `{"detail": ...}` shape (no `zip_path`), and update resource assertions to check `resource["url"]` + `get_format()` instead of uploaded-file assertions. The existing `gpkg` format assertion (`get_format() == "geopackage"`) carries over unchanged.

### `CLAUDE.md`

- "What this pipeline does": mention resources link directly to Copernicus's own servers (at their request, so they can track download statistics) rather than being re-hosted on HDX.
- Architecture step 2 (`api_retriever`): describe link-resolution/probing instead of zip download.
- Architecture step 3 (`pipeline.Pipeline`): drop the file-based resource description; describe building one Link resource per available (AOI, product, round, format) combination. Update the `preview_off()` note to state plainly that there's nothing local to preview any more, rather than framing it as a deferred TODO.
- Architecture step 4 (`product_extractor`): replace with a `product_links` description — no more zip/shapefile/dedup content.
- Note the accepted limitation: `?type=` per-format probing was confirmed against multiple real recent activations but is known to be unreliable for at least one older one; since only newly-discovered activations are ever processed, this isn't expected to matter in practice.

## Verification

- `uv run pytest` — full suite, including the renamed/rewritten test files.
- `uv run ruff check` / `uv run ruff format`.
- `grep -rn "extract_product_files\|zip_path\|product_extractor" src tests CLAUDE.md` should come back empty once the rename/removal is complete.
- Manually inspect one generated `Dataset`'s resources (via the existing `test_generate_datasets`-style fixture) to confirm each resource has a `url` pointing at `rapidmapping.emergency.copernicus.eu` with the right `?type=` value and no `file_to_upload` was ever set.
