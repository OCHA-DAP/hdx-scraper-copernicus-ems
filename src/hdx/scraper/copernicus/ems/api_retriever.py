#!/usr/bin/python
"""Fetches per-activation detail and product archives from the Copernicus EMS
Rapid Mapping JSON API, for activation codes discovered via the RSS feed."""

import logging

from hdx.api.configuration import Configuration
from hdx.utilities.retriever import Retrieve

logger = logging.getLogger(__name__)


class APIRetriever:
    def __init__(self, configuration: Configuration, retriever: Retrieve):
        self._configuration = configuration
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

            products_path = detail.get("productsPath")
            zip_path = None
            if products_path:
                zip_path = self._retriever.download_file(
                    products_path, filename=f"{code.lower()}_products.zip"
                )
            else:
                logger.warning(f"{code}: no products archive available")

            activations[code] = {"detail": detail, "zip_path": zip_path}
        return activations
