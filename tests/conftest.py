from os.path import join

import pytest
from hdx.api.configuration import Configuration
from hdx.api.locations import Locations
from hdx.data.vocabulary import Vocabulary
from hdx.location.country import Country
from hdx.utilities.downloader import Download
from hdx.utilities.retriever import Retrieve
from hdx.utilities.useragent import UserAgent


@pytest.fixture(scope="session")
def fixtures_dir():
    return join("tests", "fixtures")


@pytest.fixture(scope="session")
def input_dir(fixtures_dir):
    return join(fixtures_dir, "input")


@pytest.fixture(scope="session")
def config_dir(fixtures_dir):
    return join("src", "hdx", "scraper", "copernicus", "ems", "config")


@pytest.fixture(scope="session")
def configuration(config_dir):
    UserAgent.set_global("test")
    Configuration._create(
        hdx_read_only=True,
        hdx_site="prod",
        project_config_yaml=join(config_dir, "project_configuration.yaml"),
    )
    Locations.set_validlocations(
        [
            {"name": "ven", "title": "Venezuela"},
            {"name": "pak", "title": "Pakistan"},
        ]
    )
    Country.countriesdata(False)
    Vocabulary._approved_vocabulary = {
        "tags": [
            {"name": tag}
            for tag in (
                "earthquake-tsunami",
                "flooding",
                "fire",
                "geodata",
                "natural disasters",
                "hazards and risk",
            )
        ],
        "id": "b891512e-9516-4bf5-962a-7a289772a2a1",
        "name": "approved",
    }
    return Configuration.read()


@pytest.fixture
def retriever(input_dir, tmp_path):
    with Download(user_agent="test") as downloader:
        yield Retrieve(
            downloader=downloader,
            fallback_dir=str(tmp_path),
            saved_dir=input_dir,
            temp_dir=str(tmp_path),
            save=False,
            use_saved=True,
        )
