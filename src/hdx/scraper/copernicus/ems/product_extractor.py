#!/usr/bin/python
"""Extracts individual files from a Copernicus EMS Rapid Mapping products zip.

The top-level zip mixes direct files (eg. a raw GeoTIFF) with nested
per-product zips (eg. EMSR887_AOI01_DEL_PRODUCT_v1.zip), each of which bundles
several vector layers as full shapefile component sets, a GeoPackage, an
XLSX summary table and a PDF map under a Maps/ subfolder. Every file already
present in the archive is turned into an individually uploadable resource
file, except for a handful of per-layer vector groups deliberately left out
(see _SKIPPED_LAYERS below) since they're supporting/provenance content
rather than mapped output, and FEP (First Estimate Product) files for an AOI
that also has a more accurate DEL or GRA product (see _MORE_ACCURATE_TYPES
below); the only files this module ever creates are zips bundling a single
layer's shapefile sidecars together, since a lone .shp isn't openable
without its .shx/.dbf companions.
"""

import logging
import re
import shutil
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_SHAPEFILE_EXT = ".shp"
_GEOJSON_EXT = ".json"

# Layer/table names deliberately excluded from the exploded resource set:
# areaOfInterestA/imageFootprintA/notAnalysedA describe the assessment itself
# (AOI boundary, source imagery coverage, analysis gaps) rather than the
# mapped event, and "source" is a geometry-less imagery-provenance table -
# all supporting/provenance content rather than the core mapped output.
_SKIPPED_LAYERS = ("areaOfInterestA", "imageFootprintA", "notAnalysedA", "source")
_SKIPPED_LAYER_RE = re.compile(rf"_(?:{'|'.join(_SKIPPED_LAYERS)})_v\d+(?:__dup\d+)?$")

# Copernicus EMS product filenames encode the AOI, product type and delivery
# round, eg. "EMSR887_AOI01_DEL_PRODUCT_v1.gpkg" (initial delivery) or
# "EMSR887_AOI01_DEL_MONIT01_v1.gpkg" (first monitoring update). FEP is a
# rapid, less precise product; once a DEL or GRA product (from any round) is
# produced for the same AOI it supersedes the FEP.
_PRODUCT_TYPE_RE = re.compile(r"_(AOI\d+)_(DEL|FEP|GRA)_(PRODUCT|MONIT\d+)")
_MORE_ACCURATE_TYPES = ("DEL", "GRA")

_PRODUCT_TYPE_NOTES = {
    "DEL": (
        "**DEL (Delineation)**: maps the extent of the event itself "
        "(eg. flood, fire, landslide boundary)."
    ),
    "GRA": (
        "**GRA (Grading)**: assesses damage to individual features "
        "(eg. buildings, infrastructure)."
    ),
    "FEP": (
        "**FEP (First Estimate Product)**: a rapid, less precise product "
        "released shortly after activation for immediate situational "
        "awareness; excluded from this dataset once a more accurate DEL or "
        "GRA product for the same AOI is available."
    ),
}

_PRODUCT_TYPE_SHORT_LABELS = {
    "DEL": "delineation (extent) map",
    "GRA": "grading (damage assessment) map",
    "FEP": "first estimate product",
}

_FORMAT_LABELS = {
    ".gpkg": "GeoPackage",
    ".zip": "shapefile",
    ".json": "GeoJSON",
    ".xlsx": "spreadsheet",
    ".pdf": "PDF map",
    ".tif": "GeoTIFF",
}

_LAYER_NAME_RE = re.compile(r"_([A-Za-z][A-Za-z0-9]*)_v\d+(?:__dup\d+)?$")
_HUMANIZE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _is_skipped_layer(stem: str) -> bool:
    return bool(_SKIPPED_LAYER_RE.search(stem))


def _parse_product_type(stem: str):
    match = _PRODUCT_TYPE_RE.search(stem)
    if not match:
        return None, None, None
    return match.group(1), match.group(2), match.group(3)


def _round_label(round_token: str) -> str:
    if round_token == "PRODUCT":
        return "the initial delivery"
    monit_match = re.fullmatch(r"MONIT0*(\d+)", round_token)
    return f"monitoring round {monit_match.group(1)}"


def _format_label(path: str) -> str:
    return _FORMAT_LABELS.get(Path(path).suffix.lower(), Path(path).suffix.lstrip("."))


def _layer_fragment(stem: str, aoi: str, product_type: str, round_token: str) -> str:
    """Returns a human-readable fragment naming the specific vector layer a
    per-layer resource (shapefile zip / standalone geojson) contains, eg.
    " (Observed Event layer)", or "" if the stem is a whole-AOI/round file
    (eg. the single GeoPackage/spreadsheet/PDF covering the whole delivery)."""
    prefix = f"_{aoi}_{product_type}_{round_token}"
    remainder = stem[stem.index(prefix) + len(prefix) :]
    match = _LAYER_NAME_RE.search(remainder)
    if not match:
        return ""
    layer_name = match.group(1).rstrip("A") or match.group(1)
    humanized = _HUMANIZE_RE.sub(" ", layer_name).title()
    return f" ({humanized} layer)"


def describe_resource(path: str, code: str, activation_name: str) -> str:
    """Returns a specific, human-readable description for a single extracted
    resource file, or a generic fallback if the filename doesn't match the
    expected Copernicus EMS naming pattern (eg. an unrecognised product type
    code).

    Args:
        path: Path to the extracted resource file
        code: Activation code, eg. "EMSR900"
        activation_name: Activation name, eg. "Wildfire in Central Spain"

    Returns:
        A one-sentence resource description
    """
    stem = Path(path).stem
    aoi, product_type, round_token = _parse_product_type(stem)
    if not product_type:
        return (
            f"Rapid Mapping product file for activation {code} "
            f"({activation_name}): {Path(path).name}"
        )
    aoi_number = str(int(aoi[len("AOI") :]))
    type_label = _PRODUCT_TYPE_SHORT_LABELS[product_type]
    # Only the per-layer shapefile-zip/geojson resources have a layer-name
    # suffix worth calling out; the GeoPackage/spreadsheet/PDF resources each
    # cover the whole AOI/round delivery, not a single layer.
    if Path(path).suffix.lower() in (".zip", ".json"):
        layer_fragment = _layer_fragment(stem, aoi, product_type, round_token)
    else:
        layer_fragment = ""
    return (
        f"{_format_label(path)} containing the {type_label}{layer_fragment} for "
        f"Area of Interest {aoi_number} of the {activation_name} ({code}), from "
        f"{_round_label(round_token)}."
    )


def describe_product_types(paths: list) -> str:
    """Returns a dataset-notes snippet explaining which Copernicus EMS product
    type codes (DEL/GRA/FEP) appear in the given resource paths' filenames.

    Args:
        paths: Resource paths, typically as returned by extract_product_files

    Returns:
        A notes snippet, or "" if none of the recognised codes are present.
    """
    types_present = set()
    for path in paths:
        _, product_type, _ = _parse_product_type(Path(path).stem)
        if product_type:
            types_present.add(product_type)
    if not types_present:
        return ""
    lines = [
        _PRODUCT_TYPE_NOTES[product_type]
        for product_type in ("DEL", "GRA", "FEP")
        if product_type in types_present
    ]
    return (
        "\n\n**Product types present in this dataset's resources:**  \n"
        + "  \n".join(lines)
    )


def extract_product_files(zip_path: str, output_dir: str) -> list:
    """Extract every file from a Copernicus EMS products zip into output_dir
    as individually-uploadable resource files, bundling only the shapefile
    sidecar family together (one zip per vector layer).

    Args:
        zip_path: Path to the top-level products zip downloaded for an activation
        output_dir: Directory to write the extracted/created files into

    Returns:
        List of paths written to output_dir
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    scratch_dir = output_dir_path / ".raw"
    scratch_dir.mkdir(exist_ok=True)

    try:
        raw_paths = _flatten_to_scratch(zip_path, scratch_dir)
        return _materialize_groups(raw_paths, output_dir_path)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def _flatten_to_scratch(zip_path: str, scratch_dir: Path) -> list:
    seen = {}
    seen_groups = {}
    raw_paths = []
    with zipfile.ZipFile(zip_path) as outer:
        for info in outer.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            resolved_name = _resolve_name(seen, name, info.CRC, info.file_size)
            if resolved_name is None:
                continue
            flat_path = _extract_flat(outer, info, resolved_name, scratch_dir)
            try:
                nested = zipfile.ZipFile(flat_path)
            except zipfile.BadZipFile:
                raw_paths.append(flat_path)
                continue
            with nested:
                raw_paths.extend(_flatten_nested(nested, scratch_dir, seen_groups))
            flat_path.unlink()
    return raw_paths


def _flatten_nested(
    nested: zipfile.ZipFile, scratch_dir: Path, seen_groups: dict
) -> list:
    groups = {}
    for info in nested.infolist():
        if info.is_dir():
            continue
        stem = Path(Path(info.filename).name).stem
        groups.setdefault(stem, []).append(info)

    raw_paths = []
    for stem, infos in groups.items():
        resolved = _resolve_group_names(seen_groups, stem, infos)
        if resolved is None:
            continue
        for info, resolved_name in resolved:
            raw_paths.append(_extract_flat(nested, info, resolved_name, scratch_dir))
    return raw_paths


def _extract_flat(
    source_zip: zipfile.ZipFile, info: zipfile.ZipInfo, name: str, scratch_dir: Path
) -> Path:
    """Extract info to scratch_dir/name, flattening any subfolder in its
    original path (eg. Maps/x.pdf) and using name (which may have been
    disambiguated by _resolve_name) as the destination filename directly -
    writing straight to that path (rather than using ZipFile.extract(),
    which writes based on info.filename and would let a same-named entry
    clobber a previous one's bytes before it could be moved aside)."""
    dest = scratch_dir / name
    with source_zip.open(info) as source_fh, open(dest, "wb") as dest_fh:
        shutil.copyfileobj(source_fh, dest_fh)
    return dest


def _dedup_occurrence(seen: dict, key, fingerprint):
    """Returns the occurrence index (0 for the first time this key is seen,
    1+ for a genuinely different repeat that needs disambiguating), or None
    if fingerprint is a byte-identical repeat of an already-processed
    occurrence of key (some real archives contain such artifacts, safe to
    collapse to one)."""
    prior_fingerprints = seen.setdefault(key, [])
    if fingerprint in prior_fingerprints:
        return None
    index = len(prior_fingerprints)
    prior_fingerprints.append(fingerprint)
    return index


def _resolve_name(seen: dict, name: str, crc: int, size: int):
    """Returns the filename this entry should be extracted under, or None if
    it's a byte-identical duplicate of an already-processed entry.

    Some archives also reuse the same filename for genuinely different
    content (observed in real Copernicus EMS archives). Those must not be
    dropped: they're disambiguated with a "__dup<n>" suffix so every distinct
    file still ends up as its own resource.
    """
    index = _dedup_occurrence(seen, name, (crc, size))
    if index is None:
        logger.info(f"Duplicate entry {name!r} in archive, skipping repeat")
        return None
    if index == 0:
        return name
    stem_path = Path(name)
    resolved_name = f"{stem_path.stem}__dup{index + 1}{stem_path.suffix}"
    logger.warning(
        f"Entry {name!r} reused for different content; keeping both, this "
        f"occurrence extracted as {resolved_name!r}"
    )
    return resolved_name


def _resolve_group_names(seen_groups: dict, stem: str, infos: list):
    """Returns a list of (info, resolved_name) pairs for every member of a
    shapefile-layer sibling group (eg. the .shp/.shx/.dbf/.prj/.xml files
    sharing one stem), or None if the whole group is a byte-identical repeat
    of an already-processed occurrence of that stem.

    Unlike _resolve_name, this decides duplicate-vs-distinct for the group as
    one atomic unit (fingerprinting every member together), so siblings can
    never be split across a "kept as-is" and a "__dup<n>" occurrence - which
    would otherwise leave one of them without its shapefile companions (see
    module docstring).
    """
    fingerprint = tuple(
        sorted((Path(info.filename).name, info.CRC, info.file_size) for info in infos)
    )
    index = _dedup_occurrence(seen_groups, stem, fingerprint)
    if index is None:
        logger.info(
            f"Duplicate entry group for {stem!r} ({len(infos)} file(s)) in "
            "archive, skipping repeat"
        )
        return None
    if index == 0:
        suffix = ""
    else:
        suffix = f"__dup{index + 1}"
        names = sorted(Path(info.filename).name for info in infos)
        logger.warning(
            f"Entry group for {stem!r} reused for different content; keeping "
            f"both, this occurrence extracted with suffix {suffix!r} ({names})"
        )

    resolved = []
    for info in infos:
        name_path = Path(Path(info.filename).name)
        resolved_name = f"{name_path.stem}{suffix}{name_path.suffix}"
        resolved.append((info, resolved_name))
    return resolved


def _materialize_groups(raw_paths: list, output_dir_path: Path) -> list:
    groups = {}
    for path in raw_paths:
        groups.setdefault(path.stem, {})[path.suffix.lower()] = path

    parsed_types = {stem: _parse_product_type(stem) for stem in groups}

    aoi_accurate_types = {}
    for aoi, product_type, _ in parsed_types.values():
        if aoi and product_type in _MORE_ACCURATE_TYPES:
            aoi_accurate_types.setdefault(aoi, set()).add(product_type)

    extracted = []
    for stem, members in groups.items():
        if _is_skipped_layer(stem):
            continue
        aoi, product_type, _ = parsed_types[stem]
        if product_type == "FEP" and aoi_accurate_types.get(aoi):
            logger.info(
                f"Skipping FEP product {stem!r}: more accurate "
                f"{'/'.join(sorted(aoi_accurate_types[aoi]))} data available for {aoi}"
            )
            continue
        if _SHAPEFILE_EXT in members:
            geojson_path = members.pop(_GEOJSON_EXT, None)
            extracted.append(_bundle_shapefile(members, output_dir_path))
            if geojson_path is not None:
                extracted.append(_move_into(geojson_path, output_dir_path))
        else:
            for member_path in members.values():
                extracted.append(_move_into(member_path, output_dir_path))
    return extracted


def _bundle_shapefile(members: dict, output_dir_path: Path) -> str:
    stem = next(iter(members.values())).stem
    bundle_path = output_dir_path / f"{stem}.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for member_path in members.values():
            bundle.write(member_path, arcname=member_path.name)
    return str(bundle_path)


def _move_into(path: Path, output_dir_path: Path) -> str:
    dest = output_dir_path / path.name
    path.rename(dest)
    return str(dest)
