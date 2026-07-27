import zipfile
from os.path import basename, join
from pathlib import Path

from hdx.scraper.copernicus.ems.product_extractor import (
    describe_product_types,
    extract_product_files,
)


class TestProductExtractor:
    def test_direct_file_passthrough(self, input_dir, tmp_path):
        zip_path = join(input_dir, "emsr884_products.zip")
        extracted = extract_product_files(zip_path, str(tmp_path))

        assert [basename(p) for p in extracted] == ["EMSR884_AOI00_GRM_PRODUCT_v1.tif"]

    def test_nested_zip_grouping_and_bundling(self, input_dir, tmp_path):
        zip_path = join(input_dir, "emsrtest_products.zip")
        extracted = extract_product_files(zip_path, str(tmp_path))
        names = {basename(p) for p in extracted}

        stem = "EMSRTEST_AOI01_DEL_PRODUCT"
        # observedEventA is a core mapped-event layer and must be kept, bundled
        # as one shapefile zip plus its own standalone geojson; areaOfInterestA
        # (supporting) and source (marginal, no geometry) must be skipped.
        assert names == {
            f"{stem}_v1.gpkg",
            f"{stem}_summaryTable_v1.xlsx",
            f"{stem}_1000_map_v1.pdf",
            f"{stem}_observedEventA_v1.zip",
            f"{stem}_observedEventA_v1.json",
        }

        bundle_path = next(p for p in extracted if p.endswith("observedEventA_v1.zip"))
        with zipfile.ZipFile(bundle_path) as bundle:
            assert set(bundle.namelist()) == {
                f"{stem}_observedEventA_v1.{ext}"
                for ext in ("shp", "shx", "dbf", "prj", "sld", "lyr", "xml")
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

        names_to_content = {
            basename(p): Path(p).read_bytes() for p in extracted
        }
        assert names_to_content == {
            "a.tif": b"first",
            "a__dup2.tif": b"second-but-longer",
        }
        assert "reused for different content" in caplog.text

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
        assert describe_product_types(["EMSR884_AOI00_GRM_PRODUCT_v1.tif"]) == ""

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
