from hdx.scraper.copernicus.ems.product_links import (
    describe_product_types,
    describe_resource,
    resource_format,
    resource_sort_key,
    resource_title,
    select_products,
)


def _product(
    aoi_number, product_type, monitoring=False, monitoring_number=0, links=None
):
    return {
        "aoiNumber": aoi_number,
        "type": product_type,
        "monitoring": monitoring,
        "monitoringNumber": monitoring_number,
        "links": links
        if links is not None
        else {"gpkg": "https://example.com/x.zip?type=gpkg"},
    }


class TestSelectProducts:
    def test_drops_products_with_no_links(self):
        aois = [
            {
                "products": [
                    _product(1, "DEL", links={"gpkg": "https://example.com/1"}),
                    _product(2, "DEL", links={}),
                ]
            }
        ]
        selected = select_products(aois)
        assert [p["aoiNumber"] for p in selected] == [1]

    def test_fep_dropped_when_more_accurate_product_available_same_aoi(self):
        aois = [
            {
                "products": [
                    _product(1, "FEP"),
                    _product(1, "DEL"),
                ]
            }
        ]
        selected = select_products(aois)
        assert [p["type"] for p in selected] == ["DEL"]

    def test_fep_kept_when_no_more_accurate_product_available(self):
        aois = [{"products": [_product(1, "FEP")]}]
        selected = select_products(aois)
        assert [p["type"] for p in selected] == ["FEP"]

    def test_fep_for_other_aoi_not_affected_by_unrelated_del(self):
        aois = [
            {"products": [_product(1, "FEP")]},
            {"products": [_product(2, "DEL")]},
        ]
        selected = select_products(aois)
        assert {(p["aoiNumber"], p["type"]) for p in selected} == {
            (1, "FEP"),
            (2, "DEL"),
        }

    def test_fep_dropped_when_more_accurate_monitoring_product_available(self):
        aois = [
            {
                "products": [
                    _product(1, "FEP"),
                    _product(1, "DEL", monitoring=True, monitoring_number=1),
                ]
            }
        ]
        selected = select_products(aois)
        assert [p["type"] for p in selected] == ["DEL"]

    def test_empty_aois(self):
        assert select_products([]) == []
        assert select_products(None) == []


class TestResourceSortKey:
    def test_sorts_by_aoi_then_round_then_format(self):
        p_aoi2 = _product(2, "DEL")
        p_aoi1_initial = _product(1, "DEL")
        p_aoi1_monit = _product(1, "DEL", monitoring=True, monitoring_number=1)

        specs = [
            (p_aoi2, "gpkg"),
            (p_aoi1_monit, "gpkg"),
            (p_aoi1_initial, "pdf"),
            (p_aoi1_initial, "gpkg"),
        ]
        ordered = sorted(specs, key=lambda spec: resource_sort_key(*spec))
        assert ordered == [
            (p_aoi1_initial, "gpkg"),
            (p_aoi1_initial, "pdf"),
            (p_aoi1_monit, "gpkg"),
            (p_aoi2, "gpkg"),
        ]

    def test_format_order_within_round_is_gpkg_xlsx_vectors_pdf(self):
        product = _product(1, "DEL")
        keys = ["pdf", "vectors", "gpkg", "xlsx"]
        ordered = sorted(keys, key=lambda k: resource_sort_key(product, k))
        assert ordered == ["gpkg", "xlsx", "vectors", "pdf"]


class TestResourceFormat:
    def test_maps_format_keys_to_hdx_formats(self):
        assert resource_format("vectors") == "shp"
        assert resource_format("gpkg") == "geopackage"
        assert resource_format("pdf") == "pdf"
        assert resource_format("xlsx") == "xlsx"


class TestResourceTitle:
    def test_initial_delivery(self):
        title = resource_title(_product(1, "DEL"), "gpkg", "ven_copernicus_ems")
        assert title == "ven_copernicus_ems_aoi01_delineation_initial.gpkg"

    def test_monitoring_round(self):
        product = _product(2, "DEL", monitoring=True, monitoring_number=1)
        title = resource_title(product, "vectors", "ven_copernicus_ems")
        assert title == "ven_copernicus_ems_aoi02_delineation_monitoring1_vectors.zip"

    def test_multi_country_uses_bare_prefix(self):
        title = resource_title(_product(1, "DEL"), "xlsx", "copernicus_ems")
        assert title == "copernicus_ems_aoi01_delineation_initial.xlsx"

    def test_unrecognised_type_code_falls_back_to_lowercased_type(self):
        title = resource_title(_product(1, "GRM"), "pdf", "ven_copernicus_ems")
        assert title == "ven_copernicus_ems_aoi01_grm_initial.pdf"

    def test_titles_stay_unique_across_related_resources(self):
        products_and_formats = [
            (_product(1, "DEL"), "gpkg"),
            (_product(1, "DEL"), "xlsx"),
            (_product(1, "DEL"), "vectors"),
            (_product(1, "GRA"), "gpkg"),
            (_product(1, "DEL", monitoring=True, monitoring_number=1), "gpkg"),
        ]
        titles = [
            resource_title(product, format_key, "ven_copernicus_ems")
            for product, format_key in products_and_formats
        ]
        assert len(titles) == len(set(titles))


class TestDescribeResource:
    def test_initial_delivery(self):
        description = describe_resource(
            _product(1, "DEL"), "gpkg", "EMSR900", "Wildfire in Central Spain"
        )
        assert description == (
            "GeoPackage containing the delineation (extent) map for Area of "
            "Interest 1 of the Wildfire in Central Spain (EMSR900), from the "
            "initial delivery."
        )

    def test_monitoring_round(self):
        product = _product(2, "DEL", monitoring=True, monitoring_number=1)
        description = describe_resource(
            product, "gpkg", "EMSR900", "Wildfire in Central Spain"
        )
        assert description == (
            "GeoPackage containing the delineation (extent) map for Area of "
            "Interest 2 of the Wildfire in Central Spain (EMSR900), from "
            "monitoring round 1."
        )

    def test_falls_back_for_unrecognised_type_code(self):
        description = describe_resource(
            _product(1, "GRM"), "vectors", "EMSR999", "Made-up Activation"
        )
        assert "GRM product" in description


class TestDescribeProductTypes:
    def test_no_recognised_types(self):
        assert describe_product_types([_product(1, "GRM")]) == ""

    def test_del_only(self):
        note = describe_product_types([_product(1, "DEL")])
        assert "DEL (Delineation)" in note
        assert "GRA (Grading)" not in note
        assert "FEP (First Estimate Product)" not in note

    def test_mentions_every_type_present(self):
        note = describe_product_types(
            [_product(1, "DEL"), _product(2, "GRA"), _product(3, "FEP")]
        )
        assert "DEL (Delineation)" in note
        assert "GRA (Grading)" in note
        assert "FEP (First Estimate Product)" in note

    def test_mentions_gpkg_preference_when_gpkg_available(self):
        note = describe_product_types(
            [_product(1, "DEL", links={"gpkg": "https://example.com/x?type=gpkg"})]
        )
        assert "prefer it in GIS software" in note

    def test_no_gpkg_preference_note_when_no_gpkg_available(self):
        note = describe_product_types(
            [_product(1, "DEL", links={"pdf": "https://example.com/x?type=pdf"})]
        )
        assert "prefer it in GIS software" not in note
