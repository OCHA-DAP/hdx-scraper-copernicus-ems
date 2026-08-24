from hdx.utilities.dateparse import default_date, parse_date

from hdx.scraper.copernicus.ems.feed_reader import FeedReader


class TestFeedReader:
    def test_get_new_codes_from_scratch(self, configuration, retriever):
        feed_reader = FeedReader(configuration, retriever)
        last_build_date, codes = feed_reader.get_new_codes(default_date)

        assert last_build_date == parse_date("2026-07-13")
        # Two of the ten feed items are not activations and have no EMSR code
        assert codes == [
            "EMSR894",
            "EMSR893",
            "EMSR892",
            "EMSR889",
            "EMSR890",
            "EMSR888",
            "EMSR887",
            "EMSR886",
        ]

    def test_get_new_codes_already_up_to_date(self, configuration, retriever):
        feed_reader = FeedReader(configuration, retriever)
        last_build_date, codes = feed_reader.get_new_codes(parse_date("2026-07-13"))

        assert codes == []
