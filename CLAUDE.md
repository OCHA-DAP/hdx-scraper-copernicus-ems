# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this pipeline does

Reads the Copernicus Emergency Management Service (EMS) Rapid Mapping RSS feed
(`https://mapping.emergency.copernicus.eu/latest/feed/`) to discover EMSR activation
codes, fetches per-activation detail from the EMS JSON API, and publishes one HDX dataset
per activation with one `Link` resource per available product/format combination
(vector data, GeoPackage, PDF map, summary table), plus showcases linking to its StoryMap
and to Copernicus's own interactive viewer.

Resources link straight to Copernicus's own servers rather than being downloaded and
re-hosted on HDX — Copernicus asked for this directly, so they can track download
statistics on their side. See `api_retriever.py`'s module docstring for how those links
are resolved and validated.

There is no confirmed endpoint to list all activations, so the RSS feed (a small rolling
window of recent items) is the sole discovery mechanism — this is a known limitation, not
a bug.

**No persisted state between runs:** every run rechecks every activation currently in the
feed's window, not just ones new since the last run, and republishes all of them
unconditionally. This was a deliberate choice, not an oversight — see
`docs/decisions/0005-full-window-rescan-no-persisted-state.md` for why an incremental
"new since last checkpoint" approach (what an earlier version of this pipeline did, via
`HDXState`) silently and permanently drops activations.

**Deployment caveat:** `dataset_maintainer`, `license_id`, `caveats`, and `notes` in
`src/hdx/scraper/copernicus/ems/config/hdx_dataset_static.yaml` are provisional
placeholders pending confirmation from DPT's Copernicus EMS metadata form — do not treat
this pipeline as ready for prod until those are corrected. Similarly, `tag_mapping` in
`project_configuration.yaml` only covers categories observed in real feed/API samples so
far and is not yet confirmed against the approved HDX tag vocabulary.

## Commands

Environment setup (Python 3.13, managed with `uv`):

```shell
uv sync
```

Run the pipeline (requires `~/.hdx_configuration.yaml` with an HDX key, and
`~/.useragents.yaml` with a `hdx-scraper-copernicus-ems` entry — see README.md):

```shell
uv run python -m hdx.scraper.copernicus.ems
```

Run all tests (with coverage, configured in `pyproject.toml`):

```shell
uv run pytest
```

Run a single test file / test:

```shell
uv run pytest tests/test_product_links.py
uv run pytest tests/test_product_links.py::TestSelectProducts::test_fep_kept_when_no_more_accurate_product_available
```

Lint and format:

```shell
uv run ruff check
uv run ruff format
```

Pre-commit (runs ruff on every commit once installed):

```shell
pre-commit install
pre-commit run --all-files
```

Build:

```shell
uv build
```

Adding a dependency: add it to `project.dependencies` in `pyproject.toml` (or
`[dependency-groups]` for test-only deps), then run `uv lock --upgrade` to refresh
`uv.lock` (pre-commit also does this automatically on commit).

## Architecture

The pipeline is a straight-line pipe from feed → API → HDX, orchestrated by
`__main__.py:main()`:

1. **`feed_reader.FeedReader`** — downloads the RSS feed and extracts `EMSR\d+` codes via
   regex against `f"{title} {description} {link}"` for every entry (the feed has no
   dedicated code field), returning every code currently in the feed's window.
2. **`api_retriever.APIRetriever`** — for each code, calls the detail JSON API, then for
   every product entry in `detail["aois"][].products[]` that has a `downloadPath`, probes
   `f"{downloadPath}?type={format}"` for `format` in `vectors`/`gpkg`/`pdf`/`xlsx` and
   attaches only the ones that resolve as `product["links"]`. This can't be shortcut from
   other API fields — not every product has every format (e.g. a monitoring-round update
   may ship only a map), and that isn't reliably predictable in advance; it has to be
   probed live via a minimal ranged request (`_url_exists`). Activations with no results or
   where nothing resolved any links at all are dropped here and never reach the pipeline.
3. **`pipeline.Pipeline`** — one `_generate_dataset(code, activation)` call per activation,
   producing an `(hdx.data.Dataset, list[hdx.data.Showcase])` pair (or `None` to skip).
   Handles: sensitive-activation/no-country/no-downloadable-product filtering, fuzzy
   country-name → ISO3 matching (`hdx.location.country.Country`, memoized per name since
   the same countries recur across activations), title/name/tag construction from
   `project_configuration.yaml`'s `tag_mapping`/`common_tags`, time period from
   `eventTime`/product delivery times, and building one `Link` `Resource` per
   (product, format) pair returned by `product_links.select_products` — a `Resource` with
   just a `url` and no uploaded file, so HDX never stores a copy and every download is
   served, and counted, by Copernicus. Resources are sorted by AOI number, then
   chronological delivery round, then format category (`product_links.resource_sort_key`)
   so the list reads as the event's timeline rather than an arbitrary order.
   `Dataset.preview_off()` disables HDX's default single-resource preview: with every
   resource an external link rather than a file HDX holds a copy of, there's nothing local
   left for HDX to preview. A `Showcase` links to Copernicus's own interactive viewer
   (`mapping.emergency.copernicus.eu/activations/<code>/`) for properly-styled/labelled
   display — deliberately a plain click-through link rather than `Dataset.set_custom_viz`'s
   iframe embed, since the viewer sends `Content-Security-Policy: frame-ancestors 'none'`
   (EU Commission policy, not something Copernicus can change), which refuses to let any
   other origin frame it. A second `Showcase` links to the activation's StoryMap when
   `detail["reportLink"]` is present.
4. **`product_links`** — selects which product/format combinations are worth publishing and
   builds their resource name/description/sort order, operating directly on the structured
   product dicts the API returns (`aoiNumber`, `type`, `monitoring`, `monitoringNumber`) —
   no filename parsing needed, since nothing is downloaded or unzipped any more.
   `select_products` drops products with no resolved `links` and drops `FEP` (First
   Estimate Product) entries for an AOI that also has a more accurate `DEL`/`GRA` product
   (from any delivery round), since FEP is a rapid, less precise product meant to be
   superseded. Type/format labels fall back to a generic string (e.g. `"GRM product"`) for
   any product-type code not in the known `DEL`/`GRA`/`FEP` set, since Copernicus can and
   does introduce new ones (`GRM` already appears in real data; `REF` is mentioned by
   Copernicus but hasn't been observed).

**Known limitation:** the `?type=` per-format probing in `api_retriever.py` was confirmed
against multiple real, recently-published activations, but was found to be unreliable for
at least one older activation (`?type=vectors`/`xlsx` 404'd even though the plain combined
zip at the same `downloadPath`, with no `?type=`, contained those exact files). Since this
pipeline only ever processes activations still in the RSS feed's small rolling window
(recently requested or recently updated), this is an accepted limitation rather than
something worked around — and since every run rechecks the whole window (see
`docs/decisions/0005-full-window-rescan-no-persisted-state.md`), a transient probe failure
for one activation on one run isn't permanent - it gets retried on the next run for as long
as the activation stays in the window.

Tests mirror this structure 1:1 (`tests/test_<module>.py`) and drive real fixture data
(`tests/fixtures/input/`, sourced from actual Copernicus EMS feed/API responses) through
`Retrieve` in `use_saved=True` mode rather than mocking the HTTP layer —
`tests/conftest.py`'s `retriever` fixture wires this up. The one deliberate exception:
`APIRetriever._url_exists` does a live existence check that `Retrieve`'s fixture layer has
no equivalent for (in `use_saved=True` mode it always returns a path unconditionally, so it
can't represent "this doesn't exist") — `tests/test_api_retriever.py` monkeypatches
`_url_exists` itself (not the HTTP layer) to control which formats "resolve" per test.

## Code Style

- Formatted with `ruff` via pre-commit hooks. After changing any Python code, run:

```bash
pre-commit run --all-files
```

- Python ≥ 3.13

## Collaboration Style

- Be objective, not agreeable. Act as a partner, not a sycophant. Push back when you disagree, flag
  tradeoffs honestly, and don't sugarcoat problems.
- Keep explanations brief and to the point.
- Don't rely on recalled knowledge for facts that could be stale (API behaviour, library versions,
  external systems). Search or read the actual source first. If you lack verified information, say
  so rather than speculate.

## Scope of Changes

When fixing a bug or addressing PR feedback, change only what is necessary to resolve the specific
issue. Do not refactor surrounding code, rename variables, adjust formatting, or make improvements
in the same commit unless they are directly required by the fix. Unrelated changes obscure the
intent of the fix and complicate review and blame.

## Decision Records

Non-trivial design decisions are recorded in `docs/decisions/` (see `docs/decisions/README.md`) —
the distilled decision, not the full planning narrative, belongs here.
