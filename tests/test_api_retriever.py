from hdx.utilities.downloader import Download
from hdx.utilities.retriever import Retrieve

from hdx.scraper.copernicus.ems.api_retriever import APIRetriever


class TestAPIRetriever:
    def test_process(self, configuration, input_dir, tmp_path):
        with Download(user_agent="test") as downloader:
            retriever = Retrieve(
                downloader=downloader,
                fallback_dir=str(tmp_path),
                saved_dir=input_dir,
                temp_dir=str(tmp_path),
                save=False,
                use_saved=True,
            )
            api_retriever = APIRetriever(configuration, retriever)
            activations = api_retriever.process(["EMSR884", "EMSR838"])

        assert set(activations.keys()) == {"EMSR884", "EMSR838"}

        emsr884 = activations["EMSR884"]
        assert emsr884["detail"]["name"] == "Earthquake in Venezuela"
        assert emsr884["detail"]["countries"] == [{"name": "Venezuela"}]
        assert emsr884["zip_path"] is not None

        emsr838 = activations["EMSR838"]
        assert emsr838["detail"]["name"].startswith("Flood")
        assert emsr838["detail"]["countries"] == [{"name": "Pakistan"}]
        assert emsr838["zip_path"] is not None
