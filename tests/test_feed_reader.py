from hdx.scraper.copernicus.ems.feed_reader import FeedReader


class TestFeedReader:
    def test_get_codes_returns_every_activation_in_the_feed(
        self, configuration, retriever
    ):
        feed_reader = FeedReader(configuration, retriever)
        codes = feed_reader.get_codes()

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
