import io
import json
import zipfile
from os.path import join

from hdx.utilities.dateparse import parse_date

from hdx.scraper.copernicus.ems.pipeline import Pipeline, _latest_delivery_time


def _load_activation(input_dir, code, zip_path):
    with open(join(input_dir, f"activation-{code.lower()}.json")) as f:
        detail = json.load(f)["results"][0]
    return {"detail": detail, "zip_path": zip_path}


def _nested_zip_bytes(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buffer.getvalue()


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
            dataset["name"]: (dataset, showcases) for dataset, showcases in results
        }

        dataset, showcases = datasets_by_name["ven-earthquake-emsr884"]
        dataset.update_from_yaml(path=join(config_dir, "hdx_dataset_static.yaml"))
        assert dataset["title"] == "Venezuela - Earthquake (EMSR884)"
        assert dataset["notes"].startswith("This dataset contains")
        assert "EMSR884" in dataset["notes"]
        assert "GDACS ID: EQ1548377" in dataset["notes"]
        assert set(dataset.get_tags()) == {
            "natural disasters",
            "hazards and risk",
            "earthquake-tsunami",
            "geodata",
        }
        assert dataset.get_location_iso3s() == ["VEN"]
        time_period = dataset.get_time_period()
        assert time_period["startdate"].date() == parse_date("2026-06-24").date()
        assert time_period["enddate"].date() == parse_date("2026-07-06").date()
        resources = dataset.get_resources()
        assert len(resources) == 1
        assert resources[0]["name"] == "ven_copernicus_ems_aoi00_grading_initial.tif"
        assert resources[0].get_format() == "geotiff"
        assert resources[0]["description"] == (
            "GeoTIFF containing the grading (damage assessment) map for Area "
            "of Interest 0 of the Earthquake in Venezuela (EMSR884), from the "
            "initial delivery."
        )
        showcase_urls = {s["url"] for s in showcases}
        assert (
            "https://storymaps.arcgis.com/stories/717d0c07ec434b54ab6b2e0bbd7bc9f6"
            in showcase_urls
        )
        assert (
            "https://mapping.emergency.copernicus.eu/activations/EMSR884/"
            in showcase_urls
        )
        # emsr884_products.zip has no AOI boundary layer to preview, so the
        # default (arbitrary, potentially misleading) HDX preview is disabled.
        assert dataset.data["dataset_preview"] == "no_preview"

        dataset, showcases = datasets_by_name["pak-flood-emsr838"]
        assert dataset["title"] == "Pakistan - Flood (EMSR838)"
        assert set(dataset.get_tags()) == {
            "natural disasters",
            "hazards and risk",
            "flooding",
            "geodata",
        }
        assert dataset.get_location_iso3s() == ["PAK"]
        time_period = dataset.get_time_period()
        assert time_period["startdate"].date() == parse_date("2025-08-29").date()
        assert time_period["enddate"].date() == parse_date("2025-09-11").date()

    def test_generate_dataset_explodes_nested_products(
        self, configuration, input_dir, tmp_path
    ):
        zip_path = join(input_dir, "emsrtest_products.zip")
        detail = _load_activation(input_dir, "EMSR884", zip_path)
        pipeline = Pipeline(configuration, {"EMSR884": detail}, str(tmp_path))
        ((dataset, _showcases),) = pipeline.generate_datasets()

        assert "DEL (Delineation)" in dataset["notes"]
        assert "FEP (First Estimate Product)" not in dataset["notes"]

        resources = dataset.get_resources()
        gpkg_title = "ven_copernicus_ems_aoi01_delineation_initial.gpkg"
        xlsx_title = "ven_copernicus_ems_aoi01_delineation_initial.xlsx"
        pdf_title = "ven_copernicus_ems_aoi01_delineation_initial.pdf"
        boundary_json_title = (
            "ven_copernicus_ems_aoi01_delineation_area_of_interest_initial.json"
        )
        boundary_zip_title = (
            "ven_copernicus_ems_aoi01_delineation_area_of_interest_initial.zip"
        )
        resources_by_name = {r["name"]: r for r in resources}
        # A GeoPackage is present, so observedEventA (core mapped-event
        # layer) is dropped in its favour; areaOfInterestA (AOI boundary) is
        # kept regardless, for context/preview; source (marginal) stays
        # skipped. Resource names are human-readable titles rather than the
        # raw Copernicus EMS filenames, which aren't informative to a
        # non-expert user.
        assert set(resources_by_name) == {
            gpkg_title,
            xlsx_title,
            pdf_title,
            boundary_zip_title,
            boundary_json_title,
        }
        # Single AOI/round, so ordering falls back to gpkg first, xlsx
        # second, pdf last, others in between.
        assert [r["name"] for r in resources] == [
            gpkg_title,
            xlsx_title,
            boundary_json_title,
            boundary_zip_title,
            pdf_title,
        ]
        assert resources_by_name[gpkg_title].get_format() == "geopackage"
        assert resources_by_name[boundary_zip_title].get_format() == "shp"
        assert resources_by_name[boundary_json_title].get_format() == "geojson"
        assert resources_by_name[gpkg_title]["description"] == (
            "GeoPackage containing the delineation (extent) map for Area of "
            "Interest 1 of the Earthquake in Venezuela (EMSR884), from the "
            "initial delivery."
        )
        assert resources_by_name[boundary_zip_title]["description"] == (
            "shapefile containing the delineation (extent) map (Area Of "
            "Interest layer) for Area of Interest 1 of the Earthquake in "
            "Venezuela (EMSR884), from the initial delivery."
        )

        # HDX's default single-resource preview is disabled for now, rather
        # than showing one arbitrary, unstyled layer out of this package.
        assert dataset.data["dataset_preview"] == "no_preview"

    def test_multi_aoi_resources_grouped_by_aoi_and_round(
        self, configuration, input_dir, tmp_path
    ):
        zip_path = tmp_path / "multi_aoi_products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            for aoi in ("AOI02", "AOI01"):
                stem = f"EMSRTEST_{aoi}_DEL_PRODUCT"
                z.writestr(
                    f"{stem}_v1.zip",
                    _nested_zip_bytes(
                        {
                            f"{stem}_v1.gpkg": b"gpkg-data",
                            f"{stem}_areaOfInterestA_v1.shp": b"shp-data",
                            f"{stem}_areaOfInterestA_v1.shx": b"shx-data",
                            f"{stem}_areaOfInterestA_v1.dbf": b"dbf-data",
                            f"{stem}_areaOfInterestA_v1.json": (
                                b'{"type": "FeatureCollection", "features": []}'
                            ),
                        }
                    ),
                )

        detail = _load_activation(input_dir, "EMSR884", str(zip_path))
        pipeline = Pipeline(configuration, {"EMSR884": detail}, str(tmp_path))
        ((dataset, _showcases),) = pipeline.generate_datasets()

        def _boundary_titles(aoi):
            prefix = f"ven_copernicus_ems_{aoi}_delineation"
            return [
                f"{prefix}_initial.gpkg",
                f"{prefix}_area_of_interest_initial.json",
                f"{prefix}_area_of_interest_initial.zip",
            ]

        resources = dataset.get_resources()
        assert [r["name"] for r in resources] == (
            _boundary_titles("aoi01") + _boundary_titles("aoi02")
        )

        assert dataset.data["dataset_preview"] == "no_preview"

    def test_unmapped_category_still_gets_common_tags(
        self, configuration, input_dir, tmp_path
    ):
        detail = _load_activation(
            input_dir, "EMSR884", join(input_dir, "emsr884_products.zip")
        )
        detail["detail"]["category"] = "Landslide"
        pipeline = Pipeline(configuration, {"EMSR884": detail}, str(tmp_path))
        ((dataset, _showcases),) = pipeline.generate_datasets()

        assert set(dataset.get_tags()) == {"natural disasters", "hazards and risk"}

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


class TestLatestDeliveryTime:
    def test_picks_max_among_delivered_only(self):
        detail = {
            "aois": [
                {
                    "products": [
                        {
                            "version": {
                                "statusCode": "F",
                                "deliveryTime": "2025-08-30T03:01:00",
                            }
                        },
                        {
                            "version": {
                                "statusCode": "N",
                                "deliveryTime": "2025-09-05T00:00:00",
                            }
                        },
                        {
                            "version": {
                                "statusCode": "W",
                                "deliveryTime": "2025-09-06T00:00:00",
                            }
                        },
                    ]
                },
                {
                    "products": [
                        {
                            "version": {
                                "statusCode": "F",
                                "deliveryTime": "2025-09-01T02:27:00",
                            }
                        }
                    ]
                },
            ]
        }
        assert _latest_delivery_time(detail) == parse_date("2025-09-01T02:27:00")

    def test_no_delivered_products_returns_none(self):
        detail = {
            "aois": [
                {"products": [{"version": {"statusCode": "W", "deliveryTime": None}}]}
            ]
        }
        assert _latest_delivery_time(detail) is None

    def test_no_aois_returns_none(self):
        assert _latest_delivery_time({}) is None
