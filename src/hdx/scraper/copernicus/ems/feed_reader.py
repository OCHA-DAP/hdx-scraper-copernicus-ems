#!/usr/bin/python
"""Reads the Copernicus EMS Rapid Mapping RSS feed to discover activations.

There is no confirmed endpoint to list all activations (the JSON detail API
requires a known code), so this feed is the sole discovery mechanism. It only
covers a small rolling window of recent items and includes non-activation news
items, which are skipped.

Every code currently in that window is returned on every run, not just ones
new since a previous checkpoint: the feed's own `pubDate` reflects only when
an activation was first requested, not when Copernicus later delivers its
products (which can be days or weeks afterwards), so a "new since last time"
filter here would permanently miss activations that had nothing downloadable
yet the last time they were seen. See docs/decisions/0005.
"""

import logging
import re

import feedparser
from hdx.api.configuration import Configuration
from hdx.utilities.retriever import Retrieve

logger = logging.getLogger(__name__)

_CODE_PATTERN = re.compile(r"EMSR\d+", re.IGNORECASE)


class FeedReader:
    def __init__(self, configuration: Configuration, retriever: Retrieve):
        self._retriever = retriever
        self._feed_url = configuration["feed_url"]

    def get_codes(self) -> list:
        feed_path = self._retriever.download_file(self._feed_url, filename="feed.xml")
        feed = feedparser.parse(str(feed_path))

        codes = []
        seen = set()
        for entry in feed.entries:
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

        return codes
