#!/usr/bin/python
"""Copernicus EMS Rapid Mapping scraper"""

import logging
from functools import lru_cache

from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset
from hdx.data.hdxobject import HDXError
from hdx.data.resource import Resource
from hdx.data.showcase import Showcase
from hdx.location.country import Country
from hdx.utilities.dateparse import parse_date
from slugify import slugify

from hdx.scraper.copernicus.ems.product_links import (
    describe_product_types,
    describe_resource,
    resource_format,
    resource_sort_key,
    resource_title,
    select_products,
)

logger = logging.getLogger(__name__)


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
    def __init__(self, configuration: Configuration, activations: dict):
        self._activations = activations
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

        if detail.get("sensitive"):
            logger.info(f"{code}: sensitive, skipping")
            return None

        countries = detail.get("countries") or []
        if not countries:
            logger.warning(f"{code}: no countries listed, skipping")
            return None

        products = select_products(detail.get("aois") or [])
        if not products:
            logger.warning(f"{code}: no downloadable products, skipping")
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

        dataset["notes"] += describe_product_types(products)

        resource_specs = sorted(
            (
                (product, format_key)
                for product in products
                for format_key in product["links"]
            ),
            key=lambda spec: resource_sort_key(*spec),
        )
        for product, format_key in resource_specs:
            resource = Resource(
                {
                    "name": resource_title(product, format_key, resource_prefix),
                    "description": describe_resource(
                        product, format_key, code, activation_name
                    ),
                    "url": product["links"][format_key],
                }
            )
            resource.set_format(resource_format(format_key))
            dataset.add_update_resource(resource)

        dataset.preview_off()

        showcases = []
        report_link = detail.get("reportLink")
        if report_link:
            report_showcase = Showcase(
                {
                    "name": f"{name}-showcase",
                    "title": f"{activation_name} Situational Report",
                    "notes": "Click to explore the Copernicus EMS situational reporting for this activation",
                    "url": f"https://mapping.emergency.copernicus.eu/activations/{code}/reporting/",
                    "image_url": "https://mapping.emergency.copernicus.eu/static/assets/ccl/images/ccl-icon-emergency.svg",
                }
            )
            if tags:
                report_showcase.add_tags(tags)
            showcases.append(report_showcase)

        # Showcase link, not Dataset.set_custom_viz's iframe embed which doesn't work
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
