**Note (retroactive, added when this was archived here):** unlike every other
entry in this folder, Stage 1-4 for this build were never saved as a local
Claude Code plan-mode file — they were posted directly as comments on
[HDXPIPE-142](https://humanitarian.atlassian.net/browse/HDXPIPE-142)
instead, and recovered from there via the Atlassian Rovo MCP connector.
Implementation (Stage 5/6) is
[PR #1](https://github.com/OCHA-DAP/hdx-scraper-copernicus-ems/pull/1)
(still open as of this writing). The naming-convention work
(`2026-08-17-...`), the viewer-embed/download-links investigation
(`2026-08-18-...`), and the direct-links rewrite (`2026-08-19-...`)
elsewhere in this folder are all follow-ups to the same ticket, driven by
the real partner feedback quoted in the ticket's comment thread — see that
thread for the verbatim exchange with Copernicus (Simone Dalmasso, via
Melanie Rabier as DPT liaison) behind those three plans.

---

# HDXPIPE-142 — HDX pipeline: Copernicus emergency (EMS)

## Original ticket request (description, reported by Monica Turner)

This is a high priority.

Copernicus On Demand Mapping Services - public products.

We want to get onto HDX the Emergency Management Service - On Demand Mapping
from Copernicus which is activated during disasters.
https://mapping.emergency.copernicus.eu/

The products and information we can get onto HDX include:

- Activation status & description
- AOIs (for earthquakes for examples, shakemaps
- Maps
- Some limited statistics but they are usually shared in static infographics.

Example:

- Pakistan https://mapping.emergency.copernicus.eu/activations/EMSR838/ (see download all products)
- Venezuela https://mapping.emergency.copernicus.eu/activations/EMSR884/reporting/ (and its JSON https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR884)
- There is an XML feed for updates if useful to get all updates and info on activations https://mapping.emergency.copernicus.eu/latest/feed/

We have already reached out to the partner to ask to pull in (manually) the
Venezuela data. We will ask further information as soon as we hear back but
your support in exploring and scoping this potential pipeline is
appreciated.

FYI, I do not know yet how to get the EMSR activation number when created.

Below you will find all the info we have:

- **Organisation name (and acronym if any)**: Copernicus
- **Website(s)**: https://mapping.emergency.copernicus.eu/
- **HDX org page to host the data:** https://data.humdata.org/organization/copernicus
- **Are we building a pipeline or supporting the organisation building their own pipeline?** Building

**If we are building a pipeline:**

- **Provide information about the data**:
  - **What is the data about?** Emergency Mapping Services / On Demand activation from Copernicus.
  - **Frequency of update of the data**: As needed / when activated based on disaster.
  - **When does the data update?** Ad-hoc, when products are ready to be released.
  - **Is the data national, subnational, or both?** subnational
  - **Which countries are covered?** any / all
- **API / End points already available:**
  - Each activation seems to have a JSON feed like this one: https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR884
- **Who is the DPT focal point?**
  - Melanie - I will fill the metadata form if needed since the partner has very little time.
- **Main contact for technical questions and organisation set up questions**:
- "KALOGIROU Vasileios" Vasileios.KALOGIROU@euspa.europa.eu for now but we will review if we get a more direct EMS contact.

**DoD to begin building:**

- Partner has agreed that we are going to build the pipeline OR DPT will put the data under the HDX org
- Partner has completed the Metadata form
- Scoping document has been completed by DSys
- Effort has been estimated
- There is capacity to build the pipeline in the current quarter

**Definition of Done:**

- Pipeline code is on github
- Data Systems team added as admin on repository
- Readme is complete with instructions for anyone on DSys to be able to run
- Secrets (if any) are in Bitwarden
- P-coded resources (if any) are flagged
- Code is reviewed and on main branch
- Tests are written and deployed
- Pipeline is (initially) deployed on Github Actions
- Pipeline is deployed on Jenkins
- Pipeline is running on prod
- Partner has reviewed and approved the datasets
- Beryl from DPT has reviewed and approved the datasets
- Pipelines added to [pipeline directory](https://ocha-dap.github.io/dataviz-pipeline-directory/)

## Stage 1-3: Pipeline Scoping (Michael Rans, 2026-07-14)

Scoping summary for a new `hdx-scraper-copernicus-ems` pipeline, produced
against this ticket's description/comments plus live probing of the two
data sources named below. This is the requested scoping deliverable (per
Melanie's note that this is "ready for scoping").

### Summary

Build a pipeline publishing one HDX dataset per Copernicus EMS Rapid Mapping
activation (`EMSR###` code) to the existing `copernicus` HDX org, with the
activation's products archive as a resource and its StoryMap as a showcase.

### Data sources (confirmed live)

- **RSS feed** — `https://mapping.emergency.copernicus.eu/latest/feed/`: standard RSS 2.0, ~10 items / ~2-week rolling window. This is the **only discovery mechanism found** — no bulk "list all activations" endpoint could be confirmed.
- **JSON detail API** — `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR###`: requires a known code (confirmed by testing — omitting `code` errors "Activation code parameter is mandatory"). Returns activation metadata, AOIs, products, and a `productsPath` link to a single ZIP of all products for that activation.

This directly answers Godfrey's comment ("unclear how codes are
generated... need engineering support") — the RSS feed is the discovery
path; the JSON endpoint is enrichment only.

### Key scoping decisions (confirmed with the assignee)

- **Discovery**: RSS feed only, extracting `EMSR\d+` codes from title/description (regex — the feed has no structured code field). Two of ten sampled feed items were non-activation news posts with no code; these are skipped, not treated as errors.
- **Backfill**: forward-only from pipeline launch — no historical EMSR backfill.
- **Dataset granularity**: one HDX dataset per activation (not one rolling global dataset).
- **Resources**: ship the activation's `productsPath` ZIP as-is (not individual extracted layers).
- **Sensitive activations**: activations flagged `sensitive: true` in the API are excluded by default.

### Risks / open items

- **Feed retention is count-capped (~10 items), not time-capped** — during a high-activity period (the feed currently shows 8 concurrent European wildfires), an activation could scroll out of the feed before a scheduled run sees it. No fallback discovery path exists. Mitigated by polling frequently (recommend a short interval, not daily).
- **Product archive size**: real `productsPath` ZIPs sampled at ~880MB-1GB each (confirmed via `Content-Length`). Worth a decision on whether shipping ~1GB HDX resources per activation is acceptable, or whether a different products-shipping strategy is needed.
- **Tag vocabulary**: `category`/`subCategory` → HDX tag mapping is provisional (only `Earthquake`/`Flood`/`Wildfire` covered so far, based on samples seen) and needs confirmation against the approved HDX vocabulary.
- **Dataset identity fields not fabricated**: `dataset_maintainer`, `license_id`, `caveats`, and tag vocabulary are placeholder values pending Melanie's metadata form — not treated as final.

### DoD-to-begin-building gate check

Per this ticket's own checklist: partner agreement and a completed metadata
form aren't confirmed as done in the ticket/comments yet. This scoping
document satisfies the "scoping document completed by DSys" item, but the
others should be confirmed before implementation is treated as prod-ready.

### Templates used

Closest local structural analogs inspected: `hdx-scraper-sentinelasia`
(JSON cascade + incremental state), `hdx-scraper-unosat` (RSS feed
parsing), `hdx-scraper-copernicus-fire`/`-floods` (same HDX org, naming
convention).

---

*A full implementation (code + tests, against real captured API/feed
samples) has since been built locally as* `hdx-scraper-copernicus-ems`,
*pending the confirmations above before it's pushed/deployed.*

## Stage 4: Implementation Plan (Michael Rans, 2026-07-14)

Recorded for continuity between scoping and the PR. Approved and
implemented since this was written.

### Scaffold decision

Greenfield build. Scaffolded via `copier copy` against `hdx-scraper-copier`,
then manually nested the package under `hdx.scraper.copernicus.ems` to
match the `-fire`/`-floods` convention (copier has no variable for
namespaced packages — confirmed by inspecting its `copier.yaml`).

Copier variables used: `scraper_name=ems`, `dataset_source=Copernicus`,
`dataset_organization=47677055-92e2-4f68-bf1b-5d570f27e791` (confirmed
reused from `-fire`/`-floods`), `need_geo=false`. `dataset_maintainer`,
`license_id`, `caveats` were passed as **provisional placeholders**
(flagged, not fabricated finals) pending the DPT metadata form.

### Files planned

- **New**: `config/project_configuration.yaml` (feed URL, detail API URL, tag mapping), `feed_reader.py` (RSS parsing + code extraction, modeled on `hdx-scraper-unosat`), `api_retriever.py` (per-code JSON detail + products ZIP download, modeled on `-fire`/`-floods`), rewritten `pipeline.py` (per-activation dataset generation, modeled on `hdx-scraper-sentinelasia` + `hdx-scraper-glide`), test fixtures captured from the real feed/API.
- **Modified**: `pyproject.toml`, `run.py`, GH workflows, `README.md` (nesting path fixups), `__main__.py` (rewritten orchestration wiring `HDXState` incremental tracking), `tests/conftest.py`/`test_pipeline.py`.

### Code reuse plan

`HDXState` incremental tracking from `sentinelasia`; feed build-date
comparison from `unosat`; per-item `HDXError` isolation from `glide`;
unmapped-category/unknown-type logging from `sentinelasia`'s
`_ignored_types` pattern; org id/package convention from `-fire`/`-floods`.

### Validation plan

`pytest` against real captured fixtures (`Retrieve(save=False,
use_saved=True)`, no live network in CI); `pre-commit`/`ruff` before PR;
manual `save=True` run against live endpoints to capture fixtures.

### Review notes flagged in advance

- Provisional metadata values must be corrected before prod deploy, not silently finalized.
- Nesting fixups (repo/package rename) are mechanical but easy to miss an occurrence of.
- Feed-based discovery is best-effort by design (no list endpoint available) — an accepted limitation, not a bug.
- Schema grounded in a small number of live samples, not a published spec — reviewer should sanity-check fixture variety.

---

*Implementation is complete; see the pull request for the file-change
report and full review package (Stage 5/6).*

## Partner review (2026-07-20 through 2026-08-19)

After PR #1, the pipeline went through staged review with the partner
(Simone Dalmasso, Copernicus/EUSPA) via Melanie Rabier (DPT). Condensed
from the real Jira thread:

- **2026-07-20 to 2026-08-12**: staging links shared with Melanie for
  metadata review. Feedback incorporated: event/delivery date range
  (start = event date, end = last product delivery date, not just the
  disaster date), added `natural disaster`/`hazards and risk` tags,
  clarified product-type descriptions (DEL/GRA/FEP per Copernicus's own
  portfolio page), and reworded resource descriptions to the pattern
  `[Format] with [what] for [AOI] of [event], from the [delivery round]
  delivery` — this became the
  `2026-08-17-align-naming-with-pipeline-builder-standards.md` plan.
- **2026-08-16**: Simone (the actual partner, not DPT) gave detailed
  feedback: the dataset page's map view was confusing (only one layer
  shown at a time, unclear labels/colors vs. their own styled viewer), no
  area-of-analysis boundary shown, product temporal meaning (FEP → DEL →
  GRA) not conveyed, and the long single-layer download list should
  instead point to their own tracked download links, grouped by AOI.
  Recommended relying on their own viewer for display/download rather than
  reproducing it.
- **2026-08-17**: implemented description improvements; attempted a
  viewer iframe embed, which Copernicus's servers blocked
  (`frame-ancestors 'none'`, `X-Frame-Options: SAMEORIGIN` — European
  Commission policy, confirmed by Simone as fixed on their end, not
  changeable). This became the viewer-embed half of
  `2026-08-18-respond-to-copernicus-feedback-viewer-and-links.md`
  (`docs/decisions/0002-showcase-link-not-iframe-embed.md`).
- **2026-08-19**: Simone provided the real per-format download URL
  template
  (`https://rapidmapping.emergency.copernicus.eu/backend/EMSR{xxx}/AOI{yy}/{FEP/DEL/GRA/REF}/EMSR{xxx}_AOI{yy}_{FEP/DEL/GRA/REF}_{version}.zip?type={vectors/pdf/xlsx/geopackage}`),
  which was verified and implemented as
  `2026-08-19-replace-uploaded-resources-with-direct-links.md`
  (`docs/decisions/0001-direct-copernicus-download-links.md`). Simone
  confirmed the result worked well; Melanie approved moving toward
  release to the partner.
