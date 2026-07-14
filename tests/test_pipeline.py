import json
from os.path import join

from hdx.scraper.copernicus.ems.pipeline import Pipeline


def _load_activation(input_dir, code, zip_path):
    with open(join(input_dir, f"activation-{code.lower()}.json")) as f:
        detail = json.load(f)["results"][0]
    return {"detail": detail, "zip_path": zip_path}


class TestPipeline:
    def test_generate_datasets(self, configuration, input_dir, config_dir):
        zip_path = join(input_dir, "emsr884_products.zip")
        activations = {
            "EMSR884": _load_activation(input_dir, "EMSR884", zip_path),
            "EMSR838": _load_activation(input_dir, "EMSR838", zip_path),
        }
        pipeline = Pipeline(configuration, activations)
        results = pipeline.generate_datasets()

        assert len(results) == 2
        datasets_by_name = {
            dataset["name"]: (dataset, showcase) for dataset, showcase in results
        }

        dataset, showcase = datasets_by_name["copernicus-ems-emsr884"]
        dataset.update_from_yaml(path=join(config_dir, "hdx_dataset_static.yaml"))
        assert dataset["title"] == "Earthquake in Venezuela (EMSR884)"
        assert "EMSR884" in dataset["notes"]
        assert "GDACS ID: EQ1548377" in dataset["notes"]
        assert dataset.get_tags() == ["earthquake-tsunami", "geodata"]
        assert dataset.get_location_iso3s() == ["VEN"]
        assert dataset.get_resources()[0]["name"] == "EMSR884_products.zip"
        assert (
            showcase["url"]
            == "https://storymaps.arcgis.com/stories/717d0c07ec434b54ab6b2e0bbd7bc9f6"
        )

        dataset, showcase = datasets_by_name["copernicus-ems-emsr838"]
        assert dataset["title"] == "Flood in Pakistan (EMSR838)"
        assert dataset.get_tags() == ["flooding", "geodata"]
        assert dataset.get_location_iso3s() == ["PAK"]

    def test_skips_sensitive_activation(self, configuration, input_dir):
        detail = _load_activation(
            input_dir, "EMSR884", join(input_dir, "emsr884_products.zip")
        )
        detail["detail"]["sensitive"] = True
        pipeline = Pipeline(configuration, {"EMSR884": detail})
        assert pipeline.generate_datasets() == []

    def test_skips_activation_with_no_zip(self, configuration, input_dir):
        detail = _load_activation(input_dir, "EMSR884", None)
        pipeline = Pipeline(configuration, {"EMSR884": detail})
        assert pipeline.generate_datasets() == []
