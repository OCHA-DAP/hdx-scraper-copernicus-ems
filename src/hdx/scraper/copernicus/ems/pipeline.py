#!/usr/bin/python
"""Copernicus EMS Rapid Mapping scraper"""

import logging
from functools import lru_cache
from os.path import basename, join
from pathlib import Path

from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset
from hdx.data.hdxobject import HDXError
from hdx.data.resource import Resource
from hdx.data.showcase import Showcase
from hdx.location.country import Country
from hdx.utilities.dateparse import parse_date
from slugify import slugify

from hdx.scraper.copernicus.ems.product_extractor import (
    describe_product_types,
    describe_resource,
    extract_product_files,
    parse_product_type,
    resource_title,
    round_sort_key,
)

logger = logging.getLogger(__name__)

_RESOURCE_EXTENSION_ORDER = {".gpkg": 0, ".xlsx": 1, ".pdf": 3}


def _resource_sort_key(path: str):
    """Sorts resources by AOI number, then chronological delivery round
    (initial delivery before monitoring round 1 before round 2, etc), then by
    file-extension category within a round (GeoPackage/spreadsheet first,
    PDF map last) - so the list reads as the event's timeline rather than an
    arbitrary alphabetical-by-extension order. Resources whose filename
    doesn't match the expected Copernicus EMS naming pattern sort last."""
    aoi, _, round_token = parse_product_type(path)
    if aoi:
        aoi_number = int(aoi[len("AOI") :])
        round_rank = round_sort_key(round_token)
    else:
        aoi_number = round_rank = float("inf")
    extension_rank = _RESOURCE_EXTENSION_ORDER.get(Path(path).suffix.lower(), 2)
    return (aoi_number, round_rank, extension_rank, path)


@lru_cache
def _get_iso3_country_code_fuzzy(name: str):
    return Country.get_iso3_country_code_fuzzy(name)


def _latest_delivery_time(detail: dict):
    """Returns the latest deliveryTime among a detail's actually-delivered
    (statusCode "F") products, or None if there are none (eg. all products
    are still pending ("W") or were cancelled ("N"))."""
    delivery_times = [
        product["version"]["deliveryTime"]
        for aoi in detail.get("aois") or []
        for product in aoi.get("products") or []
        if product.get("version", {}).get("statusCode") == "F"
        and product.get("version", {}).get("deliveryTime")
    ]
    if not delivery_times:
        return None
    return max(parse_date(dt) for dt in delivery_times)


class Pipeline:
    def __init__(self, configuration: Configuration, activations: dict, temp_dir: str):
        self._activations = activations
        self._temp_dir = temp_dir
        self._tag_mapping = configuration.get("tag_mapping", {})
        self._common_tags = configuration.get("common_tags", [])
        self._unmapped_categories = set()

    def generate_datasets(self) -> list:
        datasets = []
        for code, activation in self._activations.items():
            result = self._generate_dataset(code, activation)
            if result:
                datasets.append(result)
        if self._unmapped_categories:
            logger.warning(
                f"Unmapped categories (no tags applied): {sorted(self._unmapped_categories)}"
            )
        return datasets

    def _generate_dataset(self, code: str, activation: dict):
        detail = activation["detail"]
        zip_path = activation["zip_path"]

        if detail.get("sensitive"):
            logger.info(f"{code}: sensitive, skipping")
            return None

        countries = detail.get("countries") or []
        if not countries:
            logger.warning(f"{code}: no countries listed, skipping")
            return None

        if not zip_path:
            logger.warning(f"{code}: no products archive downloaded, skipping")
            return None

        matched_countries = []
        for country in countries:
            iso3, _ = _get_iso3_country_code_fuzzy(country["name"])
            if not iso3:
                logger.warning(f"{code}: couldn't match country {country['name']!r}")
                continue
            matched_countries.append((country["name"], iso3))
        if not matched_countries:
            logger.warning(f"{code}: no valid country locations, skipping")
            return None
        matched_iso3s = [iso3 for _, iso3 in matched_countries]

        if len(matched_countries) == 1:
            location_prefix = matched_countries[0][0]
            name_prefix = matched_iso3s[0].lower()
            resource_prefix = f"{name_prefix}_copernicus_ems"
        else:
            location_prefix = "Multi-country"
            name_prefix = "multi-country"
            resource_prefix = "copernicus_ems"

        activation_name = detail.get("name", code)
        # Copernicus activation names are typically "<event type> in <country>", which
        # would duplicate location_prefix in the title, so strip a matching trailing
        # " in <country>" before prepending it.
        description = activation_name
        for raw_name, _ in matched_countries:
            suffix = f" in {raw_name}"
            if description.lower().endswith(suffix.lower()):
                description = description[: -len(suffix)]
                break
        title = f"{location_prefix} - {description} ({code})"
        category = detail.get("category")
        name = slugify(f"{name_prefix}-{category or code}-{code}")
        dataset = Dataset({"name": name, "title": title})

        gdacs_id = detail.get("gdacsId")
        gdacs_note = (
            f" GDACS ID: {gdacs_id}." if gdacs_id and gdacs_id.lower() != "none" else ""
        )
        activation_date = detail.get("activationTime") or detail.get("eventTime")
        citation_year = parse_date(activation_date).year if activation_date else None
        citation_note = (
            f"\n\n**Citation:** Copernicus Emergency Management Service "
            f"(© {citation_year} European Union), {code}"
            if citation_year
            else ""
        )
        dataset["notes"] = (
            f"This dataset contains Copernicus EMS Rapid Mapping products for "
            f"activation {code}. {detail.get('reason', '')}{gdacs_note}{citation_note}"
        )

        category_tags = list(self._tag_mapping.get(category, []))
        if category and not category_tags:
            self._unmapped_categories.add(category)
        tags = list(dict.fromkeys(self._common_tags + category_tags))
        if tags:
            dataset.add_tags(tags)

        dataset.set_subnational(True)
        added_country = False
        for iso3 in matched_iso3s:
            try:
                dataset.add_country_location(iso3)
                added_country = True
            except HDXError:
                logger.error(f"{code}: couldn't add country {iso3}, skipping location")
        if not added_country:
            logger.warning(f"{code}: no valid country locations, skipping")
            return None

        event_time = detail.get("eventTime")
        if event_time:
            start_date = parse_date(event_time)
            end_date = _latest_delivery_time(detail) or start_date
            dataset.set_time_period(start_date, end_date)

        extracted_paths = extract_product_files(zip_path, join(self._temp_dir, code))
        if not extracted_paths:
            logger.warning(
                f"{code}: no files extracted from products archive, skipping"
            )
            return None

        dataset["notes"] += describe_product_types(extracted_paths)

        for path in sorted(extracted_paths, key=_resource_sort_key):
            raw_name = basename(path)
            resource = Resource(
                {
                    # The raw Copernicus EMS filename (raw_name) is cryptic to
                    # a non-expert user, so a descriptive name following HDX's
                    # resource-naming convention is used instead - the actual
                    # uploaded/downloaded file still keeps its original
                    # filename on disk regardless of this "name" field.
                    "name": resource_title(path, resource_prefix),
                    "description": describe_resource(path, code, activation_name),
                }
            )
            ext = Path(path).suffix.lower()
            try:
                if ext == ".json":
                    # Plain ".json" only maps to a generic "JSON" HDX format, but
                    # these are GeoJSON feature collections.
                    resource.set_file_to_upload(path)
                    resource.set_format("geojson")
                elif ext == ".zip":
                    # The only zips this pipeline creates are per-layer shapefile
                    # component bundles; ".zip" itself has no format mapping.
                    resource.set_file_to_upload(path)
                    resource.set_format("shp")
                else:
                    resource.set_file_to_upload(path, guess_format_from_suffix=True)
            except HDXError:
                logger.warning(f"{code}: couldn't map format for {raw_name}, skipping")
                continue
            dataset.add_update_resource(resource)

        # TODO: HDX's default single-resource preview would show one
        # arbitrary, unstyled layer out of this multi-layer package, which
        # misrepresents the data - disabled for now rather than defaulting
        # to that.
        dataset.preview_off()

        showcases = []
        report_link = detail.get("reportLink")
        if report_link:
            report_showcase = Showcase(
                {
                    "name": f"{name}-showcase",
                    "title": f"{activation_name} Situational Report",
                    "notes": "Click to explore the Copernicus EMS StoryMap for this activation",
                    "url": report_link,
                    "image_url": "https://mapping.emergency.copernicus.eu/static/assets/ccl/images/ccl-icon-emergency.svg",
                }
            )
            if tags:
                report_showcase.add_tags(tags)
            showcases.append(report_showcase)

        # Copernicus's own viewer has proper legends/colours/timelines that
        # this pipeline doesn't attempt to reproduce - link to it via a
        # showcase button rather than Dataset.set_custom_viz: HDX embeds
        # set_custom_viz's URL in an iframe, and the viewer's
        # Content-Security-Policy (frame-ancestors 'none', set by EU
        # Commission policy - not something Copernicus can change) refuses to
        # be framed by any other origin, so that iframe never renders.
        viewer_showcase = Showcase(
            {
                "name": f"{name}-viewer-showcase",
                "title": f"{activation_name} Interactive Viewer",
                "notes": "Click to open the Copernicus EMS interactive map viewer for this activation in full screen",
                "url": f"https://mapping.emergency.copernicus.eu/activations/{code}/",
                "image_url": "https://cems-mapping-website.s3.amazonaws.com/media/images/cems-orange-logo.2e16d0ba.fill-768x432.png",
            }
        )
        if tags:
            viewer_showcase.add_tags(tags)
        showcases.append(viewer_showcase)

        return dataset, showcases
