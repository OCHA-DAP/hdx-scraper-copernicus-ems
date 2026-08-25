# 0005: Recheck every activation in the feed window every run, no persisted state

## Status

Accepted — 2026-08-26

## Context

An `HDXState`-based incremental checkpoint was added (commit `035f69f`) on top of the
RSS-only discovery decided in `0004`: `feed_reader.get_new_codes` compared each feed
entry's `pubDate` against a `previous_build_date` read from a `pipeline-state-copernicus-ems`
HDX dataset, and only newly-published entries were passed on to `api_retriever`.

This broke in production the first time it ran against a real gap: EMSR926 ("Flood in
Latvia and Lithuania") never appeared on HDX. Two compounding problems were found:

- **Off-by-one at the checkpoint boundary.** The comparison used `published <=
  previous_build_date`. Since Copernicus `pubDate`s are date-only (`00:00:00 UTC`) and the
  stored checkpoint is the feed's own `lastBuildDate` (also date-only), an activation whose
  `pubDate` exactly equalled the previous checkpoint was treated as already-seen and
  skipped — permanently, since the checkpoint only ever advances.
- **`pubDate` reflects only when an activation was requested, never updated.** Checked
  against every currently-open activation in the feed: `activationTime` (≈ `pubDate`) vs.
  the latest product `deliveryTime` showed gaps from 1 to 10 days (e.g. EMSR920:
  `activationTime` 2026-08-14, latest delivery 2026-08-24). Monitoring-round deliveries
  routinely land days or weeks after the original request, and none of that ever moves
  `pubDate`. So even fixing the boundary bug, a "new since last checkpoint" filter based on
  `pubDate` would still permanently miss any activation that had nothing downloadable (or
  failed the `?type=` probe - see the Known limitation in `CLAUDE.md`) the one time it was
  seen while "new".

A per-activation cursor keyed on the API's own `version.deliveryTime` (which does change on
every delivery) was considered as a fix, tracked in a persisted `{code: last_processed_time}`
map. It was rejected for being disproportionate: it reintroduces exactly the class of bug
above (an activation whose only real delivery is older than a since-advanced global
watermark, e.g. because its probe failed transiently that one time, would again be
permanently unreachable unless the cursor were tracked per-code specifically) for a benefit
that doesn't matter at this scale.

## Decision

Drop checkpointing entirely. `feed_reader.get_codes()` returns every `EMSR\d+` code
currently in the feed (skipping non-activation items), with no filtering by date.
`api_retriever`/`pipeline` then reprocess every one of those codes on every run,
unconditionally - `Dataset.create_in_hdx` already creates-or-updates idempotently, so
rebuilding an unchanged activation's dataset is a harmless no-op resource list.

`pipeline-state-copernicus-ems` and the `HDXState` usage in `__main__.py` are removed; the
HDX dataset itself is deleted as it no longer has any purpose.

## Consequences

- Correctness no longer depends on any timestamp comparison being exactly right, and
  self-heals: an activation that was undownloadable, or whose `?type=` probe failed
  transiently, is retried automatically for as long as Copernicus keeps it in the feed's
  rolling window (see the Known limitation note in `CLAUDE.md`), with no special-casing.
- The feed's small window size (~10 items) is now load-bearing for correctness, not just
  for discovery: an activation must still be surfaced by the feed at the point its products
  are actually ready, matching the risk already accepted in `0004`'s consequences (an
  activation can in principle scroll out of the window before ever being observed with
  something downloadable) - mitigated by running frequently, not eliminated.
- Every activation still in the feed window gets a `create_in_hdx`/showcase call on every
  run regardless of whether anything actually changed, which is more HDX API calls and
  revision-history churn than a (correct) change-detection version would produce. Accepted
  as a reasonable trade at ~10 items/run; worth revisiting if the window size or run
  frequency grows substantially.
