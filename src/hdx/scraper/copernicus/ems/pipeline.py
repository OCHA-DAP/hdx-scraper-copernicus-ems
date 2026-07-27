#!/usr/bin/python
"""Copernicus EMS Rapid Mapping scraper"""

import logging
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
    extract_product_files,
)

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, configuration: Configuration, activations: dict, temp_dir: str):
        self._configuration = configuration
        self._activations = activations
        self._temp_dir = temp_dir
        self._tag_mapping = configuration.get("tag_mapping", {})
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
            iso3, _ = Country.get_iso3_country_code_fuzzy(country["name"])
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
        else:
            location_prefix = "Multi-country"
            name_prefix = "multi-country"

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
            f"**Copernicus EMS activation code: {code}**  "
            f"{detail.get('reason', '')}{gdacs_note}{citation_note}"
        )

        tags = list(self._tag_mapping.get(category, []))
        if category and not tags:
            self._unmapped_categories.add(category)
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
            dataset.set_time_period(parse_date(event_time))

        extracted_paths = extract_product_files(zip_path, join(self._temp_dir, code))
        if not extracted_paths:
            logger.warning(
                f"{code}: no files extracted from products archive, skipping"
            )
            return None

        dataset["notes"] += describe_product_types(extracted_paths)

        resource_order = {".gpkg": 0, ".xlsx": 1, ".pdf": 3}
        for path in sorted(
            extracted_paths,
            key=lambda p: (resource_order.get(Path(p).suffix.lower(), 2), p),
        ):
            resource_name = basename(path)
            resource = Resource(
                {
                    "name": resource_name,
                    "description": (
                        f"Rapid Mapping product file for activation {code} "
                        f"({activation_name}): {resource_name}"
                    ),
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
                logger.warning(
                    f"{code}: couldn't map format for {resource_name}, skipping"
                )
                continue
            dataset.add_update_resource(resource)

        showcase = None
        report_link = detail.get("reportLink")
        if report_link:
            showcase = Showcase(
                {
                    "name": f"{name}-showcase",
                    "title": f"{activation_name} Situational Report",
                    "notes": "Click to explore the Copernicus EMS StoryMap for this activation",
                    "url": report_link,
                    "image_url": "https://mapping.emergency.copernicus.eu/static/assets/ccl/images/ccl-icon-emergency.svg",
                }
            )
            if tags:
                showcase.add_tags(tags)

        return dataset, showcase
