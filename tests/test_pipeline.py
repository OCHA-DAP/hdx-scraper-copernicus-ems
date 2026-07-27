import json
from os.path import join

from hdx.scraper.copernicus.ems.pipeline import Pipeline


def _load_activation(input_dir, code, zip_path):
    with open(join(input_dir, f"activation-{code.lower()}.json")) as f:
        detail = json.load(f)["results"][0]
    return {"detail": detail, "zip_path": zip_path}


class TestPipeline:
    def test_generate_datasets(self, configuration, input_dir, config_dir, tmp_path):
        zip_path = join(input_dir, "emsr884_products.zip")
        activations = {
            "EMSR884": _load_activation(input_dir, "EMSR884", zip_path),
            "EMSR838": _load_activation(input_dir, "EMSR838", zip_path),
        }
        pipeline = Pipeline(configuration, activations, str(tmp_path))
        results = pipeline.generate_datasets()

        assert len(results) == 2
        datasets_by_name = {
            dataset["name"]: (dataset, showcase) for dataset, showcase in results
        }

        dataset, showcase = datasets_by_name["ven-earthquake-emsr884"]
        dataset.update_from_yaml(path=join(config_dir, "hdx_dataset_static.yaml"))
        assert dataset["title"] == "Venezuela - Earthquake (EMSR884)"
        assert "EMSR884" in dataset["notes"]
        assert "GDACS ID: EQ1548377" in dataset["notes"]
        assert dataset.get_tags() == ["earthquake-tsunami", "geodata"]
        assert dataset.get_location_iso3s() == ["VEN"]
        resources = dataset.get_resources()
        assert len(resources) == 1
        assert resources[0]["name"] == "EMSR884_AOI00_GRM_PRODUCT_v1.tif"
        assert resources[0].get_format() == "geotiff"
        assert (
            showcase["url"]
            == "https://storymaps.arcgis.com/stories/717d0c07ec434b54ab6b2e0bbd7bc9f6"
        )

        dataset, showcase = datasets_by_name["pak-flood-emsr838"]
        assert dataset["title"] == "Pakistan - Flood (EMSR838)"
        assert dataset.get_tags() == ["flooding", "geodata"]
        assert dataset.get_location_iso3s() == ["PAK"]

    def test_generate_dataset_explodes_nested_products(
        self, configuration, input_dir, tmp_path
    ):
        zip_path = join(input_dir, "emsrtest_products.zip")
        detail = _load_activation(input_dir, "EMSR884", zip_path)
        pipeline = Pipeline(configuration, {"EMSR884": detail}, str(tmp_path))
        ((dataset, _showcase),) = pipeline.generate_datasets()

        assert "DEL (Delineation)" in dataset["notes"]
        assert "FEP (First Estimate Product)" not in dataset["notes"]

        resources = dataset.get_resources()
        resources_by_name = {r["name"]: r for r in resources}
        stem = "EMSRTEST_AOI01_DEL_PRODUCT"
        # observedEventA (core) is kept; areaOfInterestA (supporting) and
        # source (marginal) are deliberately skipped.
        assert set(resources_by_name) == {
            f"{stem}_v1.gpkg",
            f"{stem}_summaryTable_v1.xlsx",
            f"{stem}_1000_map_v1.pdf",
            f"{stem}_observedEventA_v1.zip",
            f"{stem}_observedEventA_v1.json",
        }
        # gpkg first, xlsx second, pdf last, others in between.
        assert [r["name"] for r in resources] == [
            f"{stem}_v1.gpkg",
            f"{stem}_summaryTable_v1.xlsx",
            f"{stem}_observedEventA_v1.json",
            f"{stem}_observedEventA_v1.zip",
            f"{stem}_1000_map_v1.pdf",
        ]
        assert resources_by_name[f"{stem}_v1.gpkg"].get_format() == "geopackage"
        assert resources_by_name[f"{stem}_observedEventA_v1.zip"].get_format() == "shp"
        assert (
            resources_by_name[f"{stem}_observedEventA_v1.json"].get_format()
            == "geojson"
        )

    def test_skips_sensitive_activation(self, configuration, input_dir, tmp_path):
        detail = _load_activation(
            input_dir, "EMSR884", join(input_dir, "emsr884_products.zip")
        )
        detail["detail"]["sensitive"] = True
        pipeline = Pipeline(configuration, {"EMSR884": detail}, str(tmp_path))
        assert pipeline.generate_datasets() == []

    def test_skips_activation_with_no_zip(self, configuration, input_dir, tmp_path):
        detail = _load_activation(input_dir, "EMSR884", None)
        pipeline = Pipeline(configuration, {"EMSR884": detail}, str(tmp_path))
        assert pipeline.generate_datasets() == []
