# 0002: Replace the interactive-viewer iframe embed with a clickable Showcase link

## Status

Accepted — 2026-08-18

## Context

Copernicus EMS gave feedback that the interactive-viewer embed
(`Dataset.set_custom_viz`, pointing at
`mapping.emergency.copernicus.eu/activations/<code>/`) never renders on the
HDX dataset page — the European Commission's Content-Security-Policy
(`frame-ancestors 'none'`) blocks any framing of the viewer, and that policy
is fixed on their end, not something Copernicus or this pipeline can
change. They suggested a plain clickable "open in full screen"-style link
instead, which this pipeline already does elsewhere for the activation's
StoryMap.

## Decision

Remove the `dataset.set_custom_viz(...)` call. Add a second `Showcase`
linking directly to the viewer URL, using the same icon/tagging pattern as
the existing StoryMap showcase. `_generate_dataset` now returns a list of
showcases (0, 1, or 2) instead of a single optional one.

## Consequences

The dataset page no longer carries a broken, never-rendering embed. Every
activation unconditionally gets the viewer showcase (every activation has a
code); the StoryMap showcase remains conditional on `detail["reportLink"]`
being present.
