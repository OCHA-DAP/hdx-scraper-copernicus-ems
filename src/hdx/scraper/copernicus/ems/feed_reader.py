#!/usr/bin/python
"""Reads the Copernicus EMS Rapid Mapping RSS feed to discover new activations.

There is no confirmed endpoint to list all activations (the JSON detail API
requires a known code), so this feed is the sole discovery mechanism. It only
covers a small rolling window of recent items and includes non-activation news
items, which are skipped.
"""

import logging
import re

import feedparser
from hdx.api.configuration import Configuration
from hdx.utilities.dateparse import default_date, parse_date
from hdx.utilities.retriever import Retrieve

logger = logging.getLogger(__name__)

_CODE_PATTERN = re.compile(r"EMSR\d+", re.IGNORECASE)


class FeedReader:
    def __init__(self, configuration: Configuration, retriever: Retrieve):
        self._configuration = configuration
        self._retriever = retriever
        self._feed_url = configuration["feed_url"]

    def get_new_codes(self, previous_build_date) -> tuple:
        feed_path = self._retriever.download_file(self._feed_url, filename="feed.xml")
        feed = feedparser.parse(str(feed_path))

        build_date_str = getattr(feed.feed, "updated", None)
        last_build_date = parse_date(build_date_str) if build_date_str else default_date
        if last_build_date <= previous_build_date:
            return previous_build_date, []

        codes = []
        seen = set()
        for entry in feed.entries:
            published = parse_date(entry.published)
            if published <= previous_build_date:
                continue
            match = _CODE_PATTERN.search(
                f"{entry.title} {entry.description} {entry.link}"
            )
            if not match:
                logger.info(f"Skipping feed item with no EMSR code: {entry.title}")
                continue
            code = match.group(0).upper()
            if code not in seen:
                seen.add(code)
                codes.append(code)

        return last_build_date, codes
