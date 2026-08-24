import json
from os.path import join

from hdx.utilities.dateparse import parse_date

from hdx.scraper.copernicus.ems.pipeline import Pipeline, _latest_delivery_time

_ALL_FORMAT_LINKS = {
    "vectors": "https://rapidmapping.example/product.zip?type=vectors",
    "gpkg": "https://rapidmapping.example/product.zip?type=gpkg",
    "pdf": "https://rapidmapping.example/product.zip?type=pdf",
    "xlsx": "https://rapidmapping.example/product.zip?type=xlsx",
}


def _load_activation(input_dir, code, links_by_key=None):
    """Loads a real activation detail fixture and attaches "links" to each
    product as api_retriever.APIRetriever.process would, using links_by_key
    (a {(aoiNumber, type, monitoring, monitoringNumber): links} mapping) for
    the products that should resolve any - every other product gets no
    links, matching an infeasible/unresolved product."""
    with open(join(input_dir, f"activation-{code.lower()}.json")) as f:
        detail = json.load(f)["results"][0]
    links_by_key = links_by_key or {}
    for aoi in detail.get("aois") or []:
        for product in aoi.get("products") or []:
            key = (
                product["aoiNumber"],
                product["type"],
                product["monitoring"],
                product["monitoringNumber"],
            )
            product["links"] = links_by_key.get(key, {})
    return {"detail": detail}


def _synthetic_activation(detail_overrides, aois):
    """Builds a minimal activation dict for tests that don't need a full
    real fixture, given a list of product dicts (already carrying "links")
    grouped one-per-AOI-dict as select_products expects."""
    detail = {
        "name": "Test Activation",
        "countries": [{"name": "Venezuela"}],
        "category": "Flood",
        "aois": aois,
    }
    detail.update(detail_overrides)
    return {"detail": detail}


def _product(
    aoi_number, product_type, monitoring=False, monitoring_number=0, links=None
):
    return {
        "aoiNumber": aoi_number,
        "type": product_type,
        "monitoring": monitoring,
        "monitoringNumber": monitoring_number,
        "links": links if links is not None else {},
        "version": {"statusCode": "F", "deliveryTime": "2026-01-01T00:00:00"},
    }


class TestPipeline:
    def test_generate_datasets(self, configuration, input_dir, config_dir):
        activations = {
            "EMSR884": _load_activation(
                input_dir,
                "EMSR884",
                {(0, "GRA", False, 0): {"gpkg": _ALL_FORMAT_LINKS["gpkg"]}},
            ),
            "EMSR838": _load_activation(
                input_dir,
                "EMSR838",
                {(1, "DEL", False, 0): {"gpkg": _ALL_FORMAT_LINKS["gpkg"]}},
            ),
        }
        pipeline = Pipeline(configuration, activations)
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
        assert resources[0]["name"] == "ven_copernicus_ems_aoi00_grading_initial.gpkg"
        assert resources[0].get_format() == "geopackage"
        assert resources[0]["url"] == _ALL_FORMAT_LINKS["gpkg"]
        assert resources[0]["description"] == (
            "GeoPackage containing the grading (damage assessment) map for "
            "Area of Interest 0 of the Earthquake in Venezuela (EMSR884), "
            "from the initial delivery."
        )
        showcase_urls = {s["url"] for s in showcases}
        assert (
            "https://mapping.emergency.copernicus.eu/activations/EMSR884/reporting/"
            in showcase_urls
        )
        assert (
            "https://mapping.emergency.copernicus.eu/activations/EMSR884/"
            in showcase_urls
        )
        # Every resource is a link to Copernicus's own servers, not a file
        # hosted by HDX, so there's nothing HDX could preview.
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

    def test_generate_dataset_creates_one_resource_per_available_format(
        self, configuration
    ):
        activation = _synthetic_activation(
            {},
            [{"products": [_product(1, "DEL", links=dict(_ALL_FORMAT_LINKS))]}],
        )
        pipeline = Pipeline(configuration, {"EMSR900": activation})
        ((dataset, _showcases),) = pipeline.generate_datasets()

        assert "DEL (Delineation)" in dataset["notes"]
        assert "FEP (First Estimate Product)" not in dataset["notes"]

        resources = dataset.get_resources()
        gpkg_title = "ven_copernicus_ems_aoi01_delineation_initial.gpkg"
        xlsx_title = "ven_copernicus_ems_aoi01_delineation_initial.xlsx"
        vectors_title = "ven_copernicus_ems_aoi01_delineation_initial_vectors.zip"
        pdf_title = "ven_copernicus_ems_aoi01_delineation_initial.pdf"
        resources_by_name = {r["name"]: r for r in resources}
        assert set(resources_by_name) == {
            gpkg_title,
            xlsx_title,
            vectors_title,
            pdf_title,
        }
        # Single AOI/round: gpkg first, xlsx second, vectors third, pdf last.
        assert [r["name"] for r in resources] == [
            gpkg_title,
            xlsx_title,
            vectors_title,
            pdf_title,
        ]
        assert resources_by_name[gpkg_title].get_format() == "geopackage"
        assert resources_by_name[vectors_title].get_format() == "shp"
        assert resources_by_name[xlsx_title].get_format() == "xlsx"
        assert resources_by_name[pdf_title].get_format() == "pdf"
        assert resources_by_name[gpkg_title]["url"] == _ALL_FORMAT_LINKS["gpkg"]
        assert resources_by_name[gpkg_title]["description"] == (
            "GeoPackage containing the delineation (extent) map for Area of "
            "Interest 1 of the Test Activation (EMSR900), from the initial "
            "delivery."
        )

        assert dataset.data["dataset_preview"] == "no_preview"

    def test_multi_aoi_resources_grouped_by_aoi_and_round(self, configuration):
        activation = _synthetic_activation(
            {},
            [
                {"products": [_product(2, "DEL", links=dict(_ALL_FORMAT_LINKS))]},
                {"products": [_product(1, "DEL", links=dict(_ALL_FORMAT_LINKS))]},
            ],
        )
        pipeline = Pipeline(configuration, {"EMSR900": activation})
        ((dataset, _showcases),) = pipeline.generate_datasets()

        def _titles(aoi):
            prefix = f"ven_copernicus_ems_{aoi}_delineation_initial"
            return [
                f"{prefix}.gpkg",
                f"{prefix}.xlsx",
                f"{prefix}_vectors.zip",
                f"{prefix}.pdf",
            ]

        resources = dataset.get_resources()
        assert [r["name"] for r in resources] == (_titles("aoi01") + _titles("aoi02"))

        assert dataset.data["dataset_preview"] == "no_preview"

    def test_fep_superseded_by_del_produces_no_fep_resource(self, configuration):
        activation = _synthetic_activation(
            {},
            [
                {
                    "products": [
                        _product(1, "FEP", links=dict(_ALL_FORMAT_LINKS)),
                        _product(1, "DEL", links={"gpkg": _ALL_FORMAT_LINKS["gpkg"]}),
                    ]
                }
            ],
        )
        pipeline = Pipeline(configuration, {"EMSR900": activation})
        ((dataset, _showcases),) = pipeline.generate_datasets()

        resources = dataset.get_resources()
        assert len(resources) == 1
        assert "delineation" in resources[0]["name"]

    def test_unmapped_category_still_gets_common_tags(self, configuration, input_dir):
        activation = _load_activation(
            input_dir,
            "EMSR884",
            {(0, "GRA", False, 0): {"gpkg": _ALL_FORMAT_LINKS["gpkg"]}},
        )
        activation["detail"]["category"] = "Landslide"
        pipeline = Pipeline(configuration, {"EMSR884": activation})
        ((dataset, _showcases),) = pipeline.generate_datasets()

        assert set(dataset.get_tags()) == {"natural disasters", "hazards and risk"}

    def test_skips_sensitive_activation(self, configuration, input_dir):
        activation = _load_activation(input_dir, "EMSR884")
        activation["detail"]["sensitive"] = True
        pipeline = Pipeline(configuration, {"EMSR884": activation})
        assert pipeline.generate_datasets() == []

    def test_skips_activation_with_no_downloadable_products(
        self, configuration, input_dir
    ):
        activation = _load_activation(input_dir, "EMSR884")
        pipeline = Pipeline(configuration, {"EMSR884": activation})
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
