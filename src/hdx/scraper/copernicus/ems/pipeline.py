#!/usr/bin/python
"""Copernicus EMS Rapid Mapping scraper"""

import logging

from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset
from hdx.data.hdxobject import HDXError
from hdx.data.resource import Resource
from hdx.data.showcase import Showcase
from hdx.location.country import Country
from hdx.utilities.dateparse import parse_date
from slugify import slugify

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, configuration: Configuration, activations: dict):
        self._configuration = configuration
        self._activations = activations
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

        name = slugify(f"copernicus-ems-{code}")
        activation_name = detail.get("name", code)
        dataset = Dataset({"name": name, "title": f"{activation_name} ({code})"})

        gdacs_id = detail.get("gdacsId")
        gdacs_note = (
            f" GDACS ID: {gdacs_id}." if gdacs_id and gdacs_id.lower() != "none" else ""
        )
        dataset["notes"] = (
            f"**Copernicus EMS activation code: {code}**  "
            f"{detail.get('reason', '')}{gdacs_note}"
        )

        category = detail.get("category")
        tags = list(self._tag_mapping.get(category, []))
        if category and not tags:
            self._unmapped_categories.add(category)
        if tags:
            dataset.add_tags(tags)

        dataset.set_subnational(True)
        added_country = False
        for country in countries:
            iso3, _ = Country.get_iso3_country_code_fuzzy(country["name"])
            if not iso3:
                logger.warning(f"{code}: couldn't match country {country['name']!r}")
                continue
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

        resource = Resource(
            {
                "name": f"{code}_products.zip",
                "description": (
                    f"All Rapid Mapping products for activation {code} ({activation_name}), "
                    "zipped: primarily GeoTIFF rasters, may also include vector tile/style files"
                ),
            }
        )
        # HDX has no generic "zip" format; every zip synonym maps to a specific content
        # type. GeoTIFF is the closest fit since raster imagery is the dominant content,
        # though the archive can also contain vt/sld/json layer files - see description.
        resource.set_format("zipped geotiff")
        resource.set_file_to_upload(zip_path)
        dataset.add_update_resource(resource)

        showcase = None
        report_link = detail.get("reportLink")
        if report_link:
            showcase = Showcase(
                {
                    "name": f"{name}-showcase",
                    "title": f"{activation_name} StoryMap",
                    "notes": "Click to explore the Copernicus EMS StoryMap for this activation",
                    "url": report_link,
                }
            )
            if tags:
                showcase.add_tags(tags)

        return dataset, showcase
