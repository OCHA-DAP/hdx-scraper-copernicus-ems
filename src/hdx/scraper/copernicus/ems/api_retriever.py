#!/usr/bin/python
"""Fetches per-activation detail from the Copernicus EMS Rapid Mapping JSON
API, for activation codes discovered via the RSS feed, and resolves which
direct per-format download links (see product_links.py) actually exist on
Copernicus's own backend for each product.

Resources are linked straight to Copernicus's servers rather than downloaded
and re-hosted on HDX, at Copernicus's own request (so they can track download
statistics) - see CLAUDE.md. Appending `?type=<format>` to a product's
`downloadPath` redirects to a specific per-format file, but not every product
has every format (eg. a monitoring-round update may ship only a map), and
this can't be predicted from other API fields - it has to be probed."""

import logging

from hdx.api.configuration import Configuration
from hdx.utilities.base_downloader import DownloadError
from hdx.utilities.retriever import Retrieve

logger = logging.getLogger(__name__)

# Confirmed against the live backend: "geopackage" (as literally given by
# Copernicus) silently falls back to the combined bundle rather than the
# standalone GeoPackage - the working query value is "gpkg".
_FORMAT_QUERY_VALUES = ("vectors", "gpkg", "pdf", "xlsx")


class APIRetriever:
    def __init__(self, configuration: Configuration, retriever: Retrieve):
        self._retriever = retriever
        self._detail_base_url = configuration["detail_base_url"]

    def process(self, codes: list) -> dict:
        activations = {}
        for code in codes:
            url = f"{self._detail_base_url}?code={code}"
            response = self._retriever.download_json(
                url, filename=f"activation-{code.lower()}.json"
            )
            results = response.get("results", [])
            if not results:
                logger.warning(f"No activation detail found for {code}, skipping")
                continue
            detail = results[0]

            has_links = False
            for aoi in detail.get("aois") or []:
                for product in aoi.get("products") or []:
                    product["links"] = self._resolve_links(product)
                    has_links = has_links or bool(product["links"])

            if not has_links:
                logger.warning(f"{code}: no downloadable product links available")
                continue

            activations[code] = {"detail": detail}
        return activations

    def _resolve_links(self, product: dict) -> dict:
        download_path = product.get("downloadPath")
        if not download_path:
            return {}
        links = {}
        for format_value in _FORMAT_QUERY_VALUES:
            url = f"{download_path}?type={format_value}"
            if self._url_exists(url):
                links[format_value] = url
        return links

    def _url_exists(self, url: str) -> bool:
        downloader = self._retriever.downloader
        try:
            downloader.setup(url, headers={"Range": "bytes=0-1"})
            return True
        except DownloadError:
            return False
        finally:
            downloader.close_response()
