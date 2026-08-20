**Note (retroactive, added when this plan was archived here):** this plan's
naming decisions are recorded as
`docs/decisions/0003-resource-naming-convention.md`.

---

# Align resource/dataset naming with the pipeline-builder skill's standards

## Context

A previous session added `resource_title()` in `product_extractor.py` to give HDX
resources a human-readable display `name` instead of the raw cryptic Copernicus
filename (e.g. `EMSR913_AOI01_DEL_PRODUCT_v1.gpkg`). That implementation produced
prose-style titles with spaces, hyphens, and parentheses (e.g. `"AOI 1 - Delineation
(extent) map - GeoPackage (initial delivery).gpkg"`).

The user asked to replace spaces with underscores, and to check naming against the
`hdx:pipeline-builder` skill's documented conventions
(`references/hdx-data-and-naming-standards.md`). That doc's "Resource Name and
Filename" section is explicit:

> Use the filename as both the resource name and the filename. Lowercase with
> underscores. Country-specific files start with the ISO3 code; org-specific files
> start with the org acronym... Avoid the word "data" in resource names.

The prose-style title doesn't fit this at all (mixed case, spaces, hyphens,
parenthetical prose). The fix is a full redesign of `resource_title()` to a proper
lowercase, underscore-separated filename-style name, not just a character swap.

Confirmed with the user:
- Prefix scheme: single-country activations use `{iso3}_copernicus_ems_...`;
  multi-country activations use `copernicus_ems_...` (no iso3, since the
  standard's iso3/org pattern doesn't cleanly support multiple countries per file).
  The activation code (e.g. `EMSR913`) does **not** need to appear in the resource
  name - it already appears in `describe_resource()`'s description text.
- While auditing, dataset `notes` was found to not follow the skill's Dataset
  Description convention ("start with 'This dataset contains...'") - the user
  wants this fixed too, even though it's a separate field from *names*.
- Dataset title/name (URL slug) were checked against the standard and are already
  compliant: title is `"{Country} - {Description} ({CODE})"` (location + hyphen,
  title case; the trailing activation code is justified the same way the
  standard's disaster-alert date-suffix exception justifies including an event
  identifier for uniqueness), and name is `{iso3-lower}-{category}-{code}` slug
  form (lowercase-hyphen, ISO3 not full country name) - no changes needed there.

## Implementation

### 1. `src/hdx/scraper/copernicus/ems/product_extractor.py`

Replace the current prose-style `resource_title(path)` with a filename-style
version, `resource_title(path, resource_prefix)`:

- New small mapping `_PRODUCT_TYPE_SLUG = {"DEL": "delineation", "GRA": "grading",
  "FEP": "first_estimate"}` (a filename-safe counterpart to the existing
  `_PRODUCT_TYPE_SHORT_LABELS`, which stays as-is for `describe_resource`).
- New `_round_slug(round_token)` (`"PRODUCT"` → `"initial"`, `"MONIT01"` →
  `"monitoring1"`) - a filename-safe counterpart to the existing `_round_label`,
  which stays as-is.
- New `_layer_slug(layer_name)`: strips the trailing `"A"` the same way
  `_layer_fragment` already does, then converts camelCase to snake_case via
  `_HUMANIZE_RE.sub("_", ...).lower()` (reusing the existing `_HUMANIZE_RE`
  pattern, just substituting `"_"` instead of `" "` and lowercasing instead of
  `.title()`-casing). `_layer_fragment`/`describe_resource` are untouched.
- `resource_title` builds: `{resource_prefix}_{aoi.lower()}_{type_slug}` +
  optionally `_{layer_slug}` (only for `.zip`/`.json`, same gating as today, using
  the existing `_layer_name()` helper) + `_{round_slug}` + optionally `_dup{n}`
  (reusing the existing `_DUP_SUFFIX_RE`) + the real lowercased extension.
  Falls back to the raw filename (`Path(path).name`) when the filename doesn't
  match the expected Copernicus EMS pattern, same as before.
- Example outputs: `ven_copernicus_ems_aoi01_delineation_initial.gpkg`,
  `ven_copernicus_ems_aoi01_delineation_area_of_interest_initial.json`,
  `copernicus_ems_aoi01_grading_monitoring1_dup2.zip` (multi-country, duplicate
  delivery).
- Docstring updated to describe the new format and the prefix parameter.

### 2. `src/hdx/scraper/copernicus/ems/pipeline.py`

- Right after `matched_iso3s` is computed, add:
  ```python
  resource_prefix = (
      f"{matched_iso3s[0].lower()}_copernicus_ems"
      if len(matched_iso3s) == 1
      else "copernicus_ems"
  )
  ```
- Pass it through: `resource_title(path, resource_prefix)` in the resource-building
  loop.
- Reword the `dataset["notes"]` opening to start with "This dataset contains...":
  ```python
  dataset["notes"] = (
      f"This dataset contains Copernicus EMS Rapid Mapping products for "
      f"activation {code}. {detail.get('reason', '')}{gdacs_note}{citation_note}"
  )
  ```
  (drops the old bold "**Copernicus EMS activation code: ...**" label in favour of
  plain language per the guideline; `gdacs_note`/`citation_note` construction is
  unchanged).

### 3. Tests

- `tests/test_product_extractor.py`: rewrite `TestResourceTitle` for the new
  `resource_title(path, resource_prefix)` signature and snake_case output -
  initial delivery, monitoring round, layer-fragment (zip/json), duplicate-delivery
  disambiguation, fallback-for-unrecognised-code, and the multi-resource
  uniqueness check, plus a case each for the single-country (`{iso3}_copernicus_ems`)
  and multi-country (`copernicus_ems`) prefixes.
- `tests/test_pipeline.py`: update every hardcoded resource-name expectation
  (`test_generate_datasets`, `test_generate_dataset_explodes_nested_products`,
  `test_multi_aoi_resources_grouped_by_aoi_and_round`) to the new snake_case
  names, and add an assertion that `dataset["notes"]` starts with `"This dataset
  contains"`.

## Verification

- `uv run pytest` - full suite green.
- `uv run ruff check && uv run ruff format --check`.
- Re-run the real-archive spot check (`extract_product_files` +
  `resource_title`) against `saved_data/emsr913_products.zip` (single-country) to
  eyeball the new names read correctly as `esp_copernicus_ems_aoi01_...`.
