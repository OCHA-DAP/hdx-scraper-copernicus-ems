# 0004: RSS-only discovery, forward-only backfill, one dataset per activation, sensitive activations excluded by default

## Status

Accepted — 2026-07-14

## Context

Scoping this pipeline (HDXPIPE-142) against the two confirmed live Copernicus EMS data
sources required settling four questions with no single "obviously correct" answer:

- **Discovery**: the RSS feed (`https://mapping.emergency.copernicus.eu/latest/feed/`) was
  the only discovery mechanism found — no bulk "list all activations" endpoint exists. The
  feed has no structured `EMSR###` code field, only free-text title/description.
- **Backfill**: the source has an unknown-length history of past activations, but no bulk
  listing to enumerate them from.
- **Dataset granularity**: Copernicus EMS activations are discrete, geographically distinct
  events (earthquakes, floods, wildfires), not a continuous time series.
- **Sensitive activations**: the JSON detail API exposes a `sensitive: true` flag on some
  activations.

## Decision

- **Discovery**: poll the RSS feed only, extracting `EMSR\d+` codes from
  `title`/`description` via regex (the feed has no structured code field). Feed items with
  no extractable code (observed: 2 of 10 sampled items were non-activation news posts) are
  skipped, not treated as errors.
- **Backfill**: forward-only from pipeline launch — no historical EMSR backfill, since the
  feed itself can't enumerate past activations and the JSON detail API requires already
  knowing a code.
- **Dataset granularity**: one HDX dataset per activation (`EMSR###`), not one rolling
  global dataset — activations are discrete events with their own AOIs, products, and
  timeline.
- **Sensitive activations**: activations flagged `sensitive: true` by the API are excluded
  from publication by default.

## Consequences

Because the feed is count-capped (~10 items) rather than time-capped, an activation can in
principle scroll out of the feed before a scheduled run observes it, with no fallback
discovery path — mitigated by polling frequently rather than daily, not eliminated. The
forward-only choice means any pre-launch activation will never appear on HDX unless
manually backfilled later. One-dataset-per-activation was validated in practice through the
partner review that followed (see `0001`-`0003`) without needing to be revisited.
