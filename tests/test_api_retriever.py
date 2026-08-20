from hdx.scraper.copernicus.ems.api_retriever import APIRetriever


def _links_for(activations, code, aoi_number, product_type, monitoring_number=0):
    for aoi in activations[code]["detail"]["aois"]:
        for product in aoi["products"]:
            if (
                product["aoiNumber"] == aoi_number
                and product["type"] == product_type
                and product["monitoringNumber"] == monitoring_number
            ):
                return product["links"]
    raise AssertionError(f"No matching product found for {code} AOI{aoi_number}")


class TestAPIRetriever:
    def test_process_resolves_all_formats_when_all_exist(
        self, configuration, retriever, monkeypatch
    ):
        monkeypatch.setattr(APIRetriever, "_url_exists", lambda self, url: True)
        api_retriever = APIRetriever(configuration, retriever)
        activations = api_retriever.process(["EMSR884", "EMSR838"])

        assert set(activations.keys()) == {"EMSR884", "EMSR838"}
        assert activations["EMSR884"]["detail"]["name"] == "Earthquake in Venezuela"
        assert activations["EMSR838"]["detail"]["name"].startswith("Flood")

        links = _links_for(activations, "EMSR884", 0, "GRA")
        assert links == {
            "vectors": (
                "https://rapidmapping.emergency.copernicus.eu/backend/EMSR884/"
                "AOI00/GRA_PRODUCT/EMSR884_AOI00_GRA_PRODUCT_v2.zip?type=vectors"
            ),
            "gpkg": (
                "https://rapidmapping.emergency.copernicus.eu/backend/EMSR884/"
                "AOI00/GRA_PRODUCT/EMSR884_AOI00_GRA_PRODUCT_v2.zip?type=gpkg"
            ),
            "pdf": (
                "https://rapidmapping.emergency.copernicus.eu/backend/EMSR884/"
                "AOI00/GRA_PRODUCT/EMSR884_AOI00_GRA_PRODUCT_v2.zip?type=pdf"
            ),
            "xlsx": (
                "https://rapidmapping.emergency.copernicus.eu/backend/EMSR884/"
                "AOI00/GRA_PRODUCT/EMSR884_AOI00_GRA_PRODUCT_v2.zip?type=xlsx"
            ),
        }

    def test_product_with_no_download_path_gets_no_links(
        self, configuration, retriever, monkeypatch
    ):
        monkeypatch.setattr(APIRetriever, "_url_exists", lambda self, url: True)
        api_retriever = APIRetriever(configuration, retriever)
        activations = api_retriever.process(["EMSR884"])

        # AOI01's initial-delivery GRA product has no downloadPath in the
        # fixture (not feasible) - it must not be probed at all, just skipped.
        assert _links_for(activations, "EMSR884", 1, "GRA") == {}

    def test_only_formats_that_resolve_are_kept(
        self, configuration, retriever, monkeypatch
    ):
        monkeypatch.setattr(
            APIRetriever,
            "_url_exists",
            lambda self, url: url.endswith("?type=pdf"),
        )
        api_retriever = APIRetriever(configuration, retriever)
        activations = api_retriever.process(["EMSR884"])

        links = _links_for(activations, "EMSR884", 0, "GRA")
        assert set(links) == {"pdf"}

    def test_activation_dropped_when_nothing_resolves(
        self, configuration, retriever, monkeypatch
    ):
        monkeypatch.setattr(APIRetriever, "_url_exists", lambda self, url: False)
        api_retriever = APIRetriever(configuration, retriever)
        activations = api_retriever.process(["EMSR884"])

        assert activations == {}
