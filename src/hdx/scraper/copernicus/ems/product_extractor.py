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

# Copernicus EMS product filenames encode the AOI and product type, eg.
# "EMSR887_AOI01_DEL_PRODUCT_v1.gpkg". FEP is a rapid, less precise product;
# once a DEL or GRA product is produced for the same AOI it supersedes the FEP.
_PRODUCT_TYPE_RE = re.compile(r"_(AOI\d+)_(DEL|FEP|GRA)_PRODUCT")
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


def _is_skipped_layer(stem: str) -> bool:
    return bool(_SKIPPED_LAYER_RE.search(stem))


def _parse_product_type(stem: str):
    match = _PRODUCT_TYPE_RE.search(stem)
    if not match:
        return None, None
    return match.group(1), match.group(2)


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
        _, product_type = _parse_product_type(Path(path).stem)
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
                raw_paths.extend(_flatten_nested(nested, scratch_dir, seen))
            flat_path.unlink()
    return raw_paths


def _flatten_nested(nested: zipfile.ZipFile, scratch_dir: Path, seen: dict) -> list:
    raw_paths = []
    for info in nested.infolist():
        if info.is_dir():
            continue
        name = Path(info.filename).name
        resolved_name = _resolve_name(seen, name, info.CRC, info.file_size)
        if resolved_name is None:
            continue
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


def _resolve_name(seen: dict, name: str, crc: int, size: int):
    """Returns the filename this entry should be extracted under, or None if
    it's a byte-identical duplicate of an already-processed entry (some real
    archives contain such artifacts, safe to collapse to one).

    Some archives also reuse the same filename for genuinely different
    content (observed in real Copernicus EMS archives). Those must not be
    dropped: they're disambiguated with a "__dup<n>" suffix so every distinct
    file still ends up as its own resource.
    """
    key = (crc, size)
    prior_keys = seen.setdefault(name, [])
    if key in prior_keys:
        logger.info(f"Duplicate entry {name!r} in archive, skipping repeat")
        return None
    if prior_keys:
        stem_path = Path(name)
        resolved_name = f"{stem_path.stem}__dup{len(prior_keys) + 1}{stem_path.suffix}"
        logger.warning(
            f"Entry {name!r} reused for different content; keeping both, this "
            f"occurrence extracted as {resolved_name!r}"
        )
    else:
        resolved_name = name
    prior_keys.append(key)
    return resolved_name


def _materialize_groups(raw_paths: list, output_dir_path: Path) -> list:
    groups = {}
    for path in raw_paths:
        groups.setdefault(path.stem, {})[path.suffix.lower()] = path

    aoi_accurate_types = {}
    for stem in groups:
        aoi, product_type = _parse_product_type(stem)
        if aoi and product_type in _MORE_ACCURATE_TYPES:
            aoi_accurate_types.setdefault(aoi, set()).add(product_type)

    extracted = []
    for stem, members in groups.items():
        if _is_skipped_layer(stem):
            continue
        aoi, product_type = _parse_product_type(stem)
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
