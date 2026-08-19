import io
import zipfile
from os.path import basename, join
from pathlib import Path

from hdx.scraper.copernicus.ems.product_extractor import (
    describe_product_types,
    describe_resource,
    extract_product_files,
    find_aoi_boundary_resources,
    parse_product_type,
    resource_title,
    round_sort_key,
)


def _nested_zip_bytes(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buffer.getvalue()


class TestProductExtractor:
    def test_direct_file_passthrough(self, input_dir, tmp_path):
        zip_path = join(input_dir, "emsr884_products.zip")
        extracted = extract_product_files(zip_path, str(tmp_path))

        assert [basename(p) for p in extracted] == ["EMSR884_AOI00_GRA_PRODUCT_v1.tif"]

    def test_nested_zip_grouping_and_bundling(self, input_dir, tmp_path):
        zip_path = join(input_dir, "emsrtest_products.zip")
        extracted = extract_product_files(zip_path, str(tmp_path))
        names = {basename(p) for p in extracted}

        stem = "EMSRTEST_AOI01_DEL_PRODUCT"
        # A GeoPackage is present for this AOI/round, so observedEventA (a
        # core mapped-event layer) is dropped in favour of it - the
        # GeoPackage already contains it, styled, so shipping both would
        # just lengthen the resource list with no new information.
        # areaOfInterestA (the AOI boundary) is always kept regardless, for
        # context/preview purposes; source (marginal, no geometry) stays
        # skipped.
        assert names == {
            f"{stem}_v1.gpkg",
            f"{stem}_summaryTable_v1.xlsx",
            f"{stem}_1000_map_v1.pdf",
            f"{stem}_areaOfInterestA_v1.zip",
            f"{stem}_areaOfInterestA_v1.json",
        }

        bundle_path = next(p for p in extracted if p.endswith("areaOfInterestA_v1.zip"))
        with zipfile.ZipFile(bundle_path) as bundle:
            assert set(bundle.namelist()) == {
                f"{stem}_areaOfInterestA_v1.{ext}"
                for ext in ("shp", "shx", "dbf", "prj", "sld", "lyr", "xml")
            }

    def test_per_layer_kept_when_no_geopackage_available(self, tmp_path):
        # If an AOI/round ships no GeoPackage, its vector layers must still
        # be individually downloadable - there's nothing else to fall back to.
        stem = "EMSR900_AOI01_DEL_PRODUCT_observedEventA_v1"
        occurrence = {
            f"{stem}.shp": b"shp-data",
            f"{stem}.shx": b"shx-data",
            f"{stem}.dbf": b"dbf-data",
            f"{stem}.json": b'{"type": "FeatureCollection", "features": []}',
        }
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence)
            )

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert {basename(p) for p in extracted} == {f"{stem}.zip", f"{stem}.json"}

    def test_per_layer_dropped_when_geopackage_available_for_same_aoi_round(
        self, tmp_path, caplog
    ):
        caplog.set_level("INFO")
        stem = "EMSR900_AOI01_DEL_PRODUCT"
        occurrence = {
            f"{stem}_v1.gpkg": b"gpkg-data",
            f"{stem}_observedEventA_v1.shp": b"shp-data",
            f"{stem}_observedEventA_v1.shx": b"shx-data",
            f"{stem}_observedEventA_v1.dbf": b"dbf-data",
        }
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(f"{stem}_v1.zip", _nested_zip_bytes(occurrence))

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert [basename(p) for p in extracted] == [f"{stem}_v1.gpkg"]
        assert "Skipping per-layer product" in caplog.text

    def test_aoi_boundary_kept_even_when_geopackage_available(self, tmp_path):
        stem = "EMSR900_AOI01_DEL_PRODUCT"
        occurrence = {
            f"{stem}_v1.gpkg": b"gpkg-data",
            f"{stem}_areaOfInterestA_v1.shp": b"shp-data",
            f"{stem}_areaOfInterestA_v1.shx": b"shx-data",
            f"{stem}_areaOfInterestA_v1.dbf": b"dbf-data",
            f"{stem}_areaOfInterestA_v1.json": b'{"type": "FeatureCollection", "features": []}',
        }
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(f"{stem}_v1.zip", _nested_zip_bytes(occurrence))

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert {basename(p) for p in extracted} == {
            f"{stem}_v1.gpkg",
            f"{stem}_areaOfInterestA_v1.zip",
            f"{stem}_areaOfInterestA_v1.json",
        }

    def test_dedup_identical_entry_kept_once(self, tmp_path):
        zip_path = tmp_path / "dupe.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("a.tif", b"same-bytes")
            z.writestr("a.tif", b"same-bytes")

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert [basename(p) for p in extracted] == ["a.tif"]

    def test_name_collision_with_different_content_keeps_both(self, tmp_path, caplog):
        # Some real Copernicus EMS archives reuse the same filename for
        # genuinely different content; both must survive under distinct names.
        zip_path = tmp_path / "dupe.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("a.tif", b"first")
            z.writestr("a.tif", b"second-but-longer")

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        names_to_content = {basename(p): Path(p).read_bytes() for p in extracted}
        assert names_to_content == {
            "a.tif": b"first",
            "a__dup2.tif": b"second-but-longer",
        }
        assert "reused for different content" in caplog.text

    def test_dup_group_keeps_siblings_together_when_one_member_differs(
        self, tmp_path, caplog
    ):
        # Real Copernicus EMS archives can redeliver the same nested-zip name
        # (eg. a republished layer bundle) where most sibling files are
        # byte-identical but one (eg. an .xml with just an updated timestamp)
        # differs. All siblings of that occurrence must get the same __dup2
        # suffix together, not just the changed file.
        stem = "EMSR900_AOI01_DEL_PRODUCT_observedEventA_v1"
        occurrence_1 = {
            f"{stem}.shp": b"shp-data",
            f"{stem}.shx": b"shx-data",
            f"{stem}.dbf": b"dbf-data",
            f"{stem}.prj": b"prj-data",
            f"{stem}.xml": b"xml-data-v1",
        }
        occurrence_2 = {**occurrence_1, f"{stem}.xml": b"xml-data-v2"}

        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence_1)
            )
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence_2)
            )

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))
        names = {basename(p) for p in extracted}

        assert names == {f"{stem}.zip", f"{stem}__dup2.zip"}
        with zipfile.ZipFile(
            next(p for p in extracted if p.endswith("__dup2.zip"))
        ) as bundle:
            assert set(bundle.namelist()) == {
                f"{stem}__dup2.{ext}" for ext in ("shp", "shx", "dbf", "prj", "xml")
            }
        assert "reused for different content" in caplog.text

    def test_dup_group_prevents_broken_shapefile_when_geometry_changes(self, tmp_path):
        # Worse case than the above: the .shp/.shx (geometry) change between
        # occurrences but .dbf (attributes) stays byte-identical. Per-file
        # dedup would drop the "unchanged" .dbf and leave the __dup2 bundle
        # missing it entirely - an incomplete, unopenable shapefile.
        stem = "EMSR900_AOI01_DEL_PRODUCT_observedEventA_v1"
        occurrence_1 = {
            f"{stem}.shp": b"shp-geometry-v1",
            f"{stem}.shx": b"shx-geometry-v1",
            f"{stem}.dbf": b"dbf-attributes",
        }
        occurrence_2 = {
            f"{stem}.shp": b"shp-geometry-v2",
            f"{stem}.shx": b"shx-geometry-v2",
            f"{stem}.dbf": b"dbf-attributes",
        }

        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence_1)
            )
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence_2)
            )

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        dup_bundle = next(p for p in extracted if p.endswith("__dup2.zip"))
        with zipfile.ZipFile(dup_bundle) as bundle:
            assert set(bundle.namelist()) == {
                f"{stem}__dup2.shp",
                f"{stem}__dup2.shx",
                f"{stem}__dup2.dbf",
            }
            assert bundle.read(f"{stem}__dup2.shp") == b"shp-geometry-v2"
            assert bundle.read(f"{stem}__dup2.shx") == b"shx-geometry-v2"
            assert bundle.read(f"{stem}__dup2.dbf") == b"dbf-attributes"

    def test_dup_group_fully_dropped_when_byte_identical_across_occurrences(
        self, tmp_path
    ):
        stem = "EMSR900_AOI01_DEL_PRODUCT_observedEventA_v1"
        occurrence = {
            f"{stem}.shp": b"shp-data",
            f"{stem}.shx": b"shx-data",
            f"{stem}.dbf": b"dbf-data",
        }

        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence)
            )
            z.writestr(
                "EMSR900_AOI01_DEL_PRODUCT_v1.zip", _nested_zip_bytes(occurrence)
            )

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert [basename(p) for p in extracted] == [f"{stem}.zip"]
        with zipfile.ZipFile(extracted[0]) as bundle:
            assert set(bundle.namelist()) == {
                f"{stem}.{ext}" for ext in ("shp", "shx", "dbf")
            }

    def test_fep_dropped_when_more_accurate_product_available(self, tmp_path, caplog):
        caplog.set_level("INFO")
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("EMSR900_AOI01_FEP_PRODUCT_v1.tif", b"fep-data")
            z.writestr("EMSR900_AOI01_DEL_PRODUCT_v1.tif", b"del-data")

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert [basename(p) for p in extracted] == ["EMSR900_AOI01_DEL_PRODUCT_v1.tif"]
        assert "Skipping FEP product" in caplog.text

    def test_fep_kept_when_no_more_accurate_product_available(self, tmp_path):
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("EMSR900_AOI01_FEP_PRODUCT_v1.tif", b"fep-data")

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert [basename(p) for p in extracted] == ["EMSR900_AOI01_FEP_PRODUCT_v1.tif"]

    def test_fep_dropped_when_more_accurate_monitoring_product_available(
        self, tmp_path, caplog
    ):
        caplog.set_level("INFO")
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("EMSR900_AOI01_FEP_PRODUCT_v1.tif", b"fep-data")
            z.writestr("EMSR900_AOI01_DEL_MONIT01_v1.tif", b"del-monitoring-data")

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert [basename(p) for p in extracted] == ["EMSR900_AOI01_DEL_MONIT01_v1.tif"]
        assert "Skipping FEP product" in caplog.text

    def test_fep_for_other_aoi_not_affected_by_unrelated_del(self, tmp_path):
        zip_path = tmp_path / "products.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("EMSR900_AOI01_FEP_PRODUCT_v1.tif", b"fep-data")
            z.writestr("EMSR900_AOI02_DEL_PRODUCT_v1.tif", b"del-data")

        output_dir = tmp_path / "out"
        extracted = extract_product_files(str(zip_path), str(output_dir))

        assert {basename(p) for p in extracted} == {
            "EMSR900_AOI01_FEP_PRODUCT_v1.tif",
            "EMSR900_AOI02_DEL_PRODUCT_v1.tif",
        }


class TestDescribeProductTypes:
    def test_no_recognised_types(self):
        assert describe_product_types(["EMSR999_AOI01_XXX_PRODUCT_v1.tif"]) == ""

    def test_del_only(self):
        note = describe_product_types(["EMSR900_AOI01_DEL_PRODUCT_v1.gpkg"])
        assert "DEL (Delineation)" in note
        assert "GRA (Grading)" not in note
        assert "FEP (First Estimate Product)" not in note

    def test_mentions_every_type_present(self):
        note = describe_product_types(
            [
                "EMSR900_AOI01_DEL_PRODUCT_v1.gpkg",
                "EMSR900_AOI02_GRA_PRODUCT_v1.gpkg",
                "EMSR900_AOI03_FEP_PRODUCT_v1.tif",
            ]
        )
        assert "DEL (Delineation)" in note
        assert "GRA (Grading)" in note
        assert "FEP (First Estimate Product)" in note

    def test_mentions_gpkg_preference_when_gpkg_present(self):
        note = describe_product_types(["EMSR900_AOI01_DEL_PRODUCT_v1.gpkg"])
        assert "prefer it in GIS software" in note

    def test_no_gpkg_preference_note_when_no_gpkg_present(self):
        note = describe_product_types(["EMSR900_AOI01_DEL_PRODUCT_v1.tif"])
        assert "prefer it in GIS software" not in note


class TestDescribeResource:
    def test_initial_delivery(self):
        description = describe_resource(
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_v1.gpkg",
            "EMSR900",
            "Wildfire in Central Spain",
        )
        assert description == (
            "GeoPackage containing the delineation (extent) map for Area of "
            "Interest 1 of the Wildfire in Central Spain (EMSR900), from the "
            "initial delivery."
        )

    def test_monitoring_round(self):
        description = describe_resource(
            "/tmp/EMSR900_AOI02_DEL_MONIT01_v1.gpkg",
            "EMSR900",
            "Wildfire in Central Spain",
        )
        assert description == (
            "GeoPackage containing the delineation (extent) map for Area of "
            "Interest 2 of the Wildfire in Central Spain (EMSR900), from "
            "monitoring round 1."
        )

    def test_layer_fragment_only_for_zip_and_geojson(self):
        zip_description = describe_resource(
            "/tmp/EMSR838_AOI01_DEL_PRODUCT_floodDepthA_v1.zip",
            "EMSR838",
            "Flood in Pakistan",
        )
        assert "(Flood Depth layer)" in zip_description

        json_description = describe_resource(
            "/tmp/EMSR838_AOI01_DEL_PRODUCT_floodDepthA_v1.json",
            "EMSR838",
            "Flood in Pakistan",
        )
        assert "(Flood Depth layer)" in json_description

        gpkg_description = describe_resource(
            "/tmp/EMSR838_AOI01_DEL_PRODUCT_v1.gpkg",
            "EMSR838",
            "Flood in Pakistan",
        )
        assert "layer" not in gpkg_description

    def test_falls_back_for_unrecognised_type_code(self):
        description = describe_resource(
            "/tmp/EMSR999_AOI01_XXX_PRODUCT_v1.tif",
            "EMSR999",
            "Made-up Activation",
        )
        assert description == (
            "Rapid Mapping product file for activation EMSR999 "
            "(Made-up Activation): EMSR999_AOI01_XXX_PRODUCT_v1.tif"
        )


class TestResourceTitle:
    def test_initial_delivery(self):
        title = resource_title(
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_v1.gpkg", "ven_copernicus_ems"
        )
        assert title == "ven_copernicus_ems_aoi01_delineation_initial.gpkg"

    def test_monitoring_round(self):
        title = resource_title(
            "/tmp/EMSR900_AOI02_DEL_MONIT01_v1.gpkg", "ven_copernicus_ems"
        )
        assert title == "ven_copernicus_ems_aoi02_delineation_monitoring1.gpkg"

    def test_multi_country_uses_bare_prefix(self):
        title = resource_title(
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_v1.gpkg", "copernicus_ems"
        )
        assert title == "copernicus_ems_aoi01_delineation_initial.gpkg"

    def test_layer_fragment_included_for_zip_and_geojson(self):
        zip_title = resource_title(
            "/tmp/EMSR838_AOI01_DEL_PRODUCT_floodDepthA_v1.zip", "pak_copernicus_ems"
        )
        assert (
            zip_title == "pak_copernicus_ems_aoi01_delineation_flood_depth_initial.zip"
        )

        json_title = resource_title(
            "/tmp/EMSR838_AOI01_DEL_PRODUCT_floodDepthA_v1.json", "pak_copernicus_ems"
        )
        assert (
            json_title
            == "pak_copernicus_ems_aoi01_delineation_flood_depth_initial.json"
        )

    def test_duplicate_delivery_disambiguated(self):
        title = resource_title(
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_observedEventA_v1__dup2.zip",
            "ven_copernicus_ems",
        )
        assert title == (
            "ven_copernicus_ems_aoi01_delineation_observed_event_initial_dup2.zip"
        )

    def test_falls_back_to_raw_filename_for_unrecognised_type_code(self):
        title = resource_title(
            "/tmp/EMSR999_AOI01_XXX_PRODUCT_v1.tif", "ven_copernicus_ems"
        )
        assert title == "EMSR999_AOI01_XXX_PRODUCT_v1.tif"

    def test_titles_stay_unique_across_related_resources(self):
        # Names must never collide for genuinely distinct files - CKAN falls
        # back to matching name+format when names aren't unique, which is
        # weaker than a plain name match.
        stems = [
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_v1.gpkg",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_summaryTable_v1.xlsx",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_areaOfInterestA_v1.zip",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_areaOfInterestA_v1.json",
            "/tmp/EMSR900_AOI01_GRA_PRODUCT_v1.gpkg",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_areaOfInterestA_v1__dup2.zip",
        ]
        titles = [resource_title(p, "ven_copernicus_ems") for p in stems]
        assert len(titles) == len(set(titles))


class TestFindAoiBoundaryResources:
    def test_finds_boundary_geojson_ordered_by_aoi(self):
        paths = [
            "/tmp/EMSR900_AOI02_DEL_PRODUCT_areaOfInterestA_v1.json",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_areaOfInterestA_v1.json",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_observedEventA_v1.json",
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_v1.gpkg",
        ]
        assert find_aoi_boundary_resources(paths) == [
            "/tmp/EMSR900_AOI01_DEL_PRODUCT_areaOfInterestA_v1.json",
            "/tmp/EMSR900_AOI02_DEL_PRODUCT_areaOfInterestA_v1.json",
        ]

    def test_empty_when_no_boundary_present(self):
        paths = ["/tmp/EMSR900_AOI01_DEL_PRODUCT_v1.gpkg"]
        assert find_aoi_boundary_resources(paths) == []


class TestRoundSortKey:
    def test_initial_delivery_sorts_first(self):
        assert round_sort_key("PRODUCT") < round_sort_key("MONIT01")

    def test_monitoring_rounds_sort_numerically(self):
        assert (
            round_sort_key("MONIT01")
            < round_sort_key("MONIT02")
            < round_sort_key("MONIT10")
        )


class TestParseProductType:
    def test_parses_matching_filename(self):
        assert parse_product_type("/tmp/EMSR900_AOI01_DEL_MONIT01_v1.gpkg") == (
            "AOI01",
            "DEL",
            "MONIT01",
        )

    def test_returns_none_tuple_for_unrecognised_filename(self):
        assert parse_product_type("/tmp/random.tif") == (None, None, None)
