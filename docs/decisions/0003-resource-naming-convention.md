# 0003: Resource names follow the pipeline-builder skill's lowercase/underscore filename convention, with a country-count-dependent prefix

## Status

Accepted — 2026-08-17

## Context

An earlier session added human-readable resource titles (e.g. `"AOI 1 -
Delineation (extent) map - GeoPackage (initial delivery).gpkg"`) in place of
Copernicus's cryptic raw filenames, but that format used mixed case, spaces,
hyphens, and parenthetical prose — not matching the `hdx:pipeline-builder`
skill's documented "Resource Name and Filename" standard (lowercase,
underscore-separated, country/org-prefixed).

## Decision

Rebuild `resource_title()` as a proper lowercase, underscore-separated
filename-style name:
`{resource_prefix}_{aoi}_{type_slug}[_{layer_slug}]_{round_slug}[_dup{n}].{ext}`.
`resource_prefix` is `{iso3}_copernicus_ems` for single-country activations,
or bare `copernicus_ems` for multi-country activations — the standard's
iso3/org-prefix pattern doesn't cleanly support multiple countries in one
filename, so the activation code (already present in the resource
description) is left out of the name rather than force-fitting multiple
ISO3s in. Dataset `notes` was also reworded to start with "This dataset
contains..." per the skill's separate Dataset Description convention.

## Consequences

Resource names are now consistent with every other HDX pipeline built
against this skill's standard, at the cost of losing the more
human-readable prose titles for anyone browsing resource names directly
(the descriptive text remains available via `describe_resource()`). This
naming shape (`resource_prefix` parameter, `_slug` helper functions)
carried forward unchanged into the 2026-08-19 rewrite to direct Copernicus
links (see 0001).
