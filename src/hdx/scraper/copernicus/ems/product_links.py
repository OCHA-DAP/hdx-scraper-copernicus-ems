#!/usr/bin/python
"""Selects and describes the Copernicus EMS Rapid Mapping product downloads
to publish as HDX resources, given the per-product `links` dicts that
api_retriever.APIRetriever resolves (format -> direct Copernicus download
URL).

Every product entry in the detail API's `aois[].products[]` array can offer
up to four downloads - matching Copernicus's own viewer buttons: "vectors"
(zipped shapefile), "gpkg" (GeoPackage), "pdf" (map) and "xlsx" (summary
table) - though not every product has every format. A product is excluded
entirely if none of its formats resolved (api_retriever already dropped
those from `links`), or if it's a FEP (First Estimate Product) for an AOI
that also has a more accurate DEL or GRA product (from any delivery round) -
FEP is a rapid, less precise product superseded once better data exists for
the same AOI.
"""

_MORE_ACCURATE_TYPES = ("DEL", "GRA")

_PRODUCT_TYPE_NOTES = {
    "DEL": (
        "**DEL (Delineation)**: maps the extent of the event itself "
        "(eg. flood, fire, landslide boundary)."
    ),
    "GRA": (
        "**GRA (Grading)**: assesses damage to individual features "
        "(eg. buildings, infrastructure)."
    ),
    "FEP": (
        "**FEP (First Estimate Product)**: a rapid, less precise product "
        "released shortly after activation for immediate situational "
        "awareness; excluded from this dataset once a more accurate DEL or "
        "GRA product for the same AOI is available."
    ),
}

_PRODUCT_TYPE_LABELS = {
    "DEL": "delineation (extent) map",
    "GRA": "grading (damage assessment) map",
    "FEP": "first estimate product",
}

_PRODUCT_TYPE_SLUGS = {
    "DEL": "delineation",
    "GRA": "grading",
    "FEP": "first_estimate",
}

# Leading noun for a resource's description sentence, matching the labels on
# Copernicus's own per-product download buttons.
_FORMAT_LABELS = {
    "vectors": "Zipped shapefile",
    "gpkg": "GeoPackage",
    "pdf": "PDF map",
    "xlsx": "Summary table (spreadsheet)",
}

_FORMAT_EXTENSIONS = {"vectors": "zip", "gpkg": "gpkg", "pdf": "pdf", "xlsx": "xlsx"}

_FORMAT_HDX_FORMATS = {
    "vectors": "shp",
    "gpkg": "geopackage",
    "pdf": "pdf",
    "xlsx": "xlsx",
}

# Within a single AOI/round, order resources GeoPackage/spreadsheet first,
# then vectors, with the PDF map last - so the list reads as "data, then
# map" rather than an arbitrary order.
_FORMAT_ORDER = {"gpkg": 0, "xlsx": 1, "vectors": 2, "pdf": 3}


def _round_label(monitoring: bool, monitoring_number: int) -> str:
    return (
        "the initial delivery"
        if not monitoring
        else f"monitoring round {monitoring_number}"
    )


def _round_slug(monitoring: bool, monitoring_number: int) -> str:
    return "initial" if not monitoring else f"monitoring{monitoring_number}"


def select_products(aois: list) -> list:
    """Returns the product entries worth publishing as resources: every
    product across aois with at least one resolved format link, excluding
    FEP products for an AOI that also has a more accurate DEL/GRA product.

    Args:
        aois: An activation detail's "aois" list

    Returns:
        Selected product dicts (each with a non-empty "links" dict)
    """
    products = [
        product
        for aoi in aois or []
        for product in aoi.get("products") or []
        if product.get("links")
    ]
    accurate_aois = {
        product["aoiNumber"]
        for product in products
        if product["type"] in _MORE_ACCURATE_TYPES
    }
    return [
        product
        for product in products
        if not (product["type"] == "FEP" and product["aoiNumber"] in accurate_aois)
    ]


def resource_sort_key(product: dict, format_key: str):
    """Sorts (product, format) resource pairs by AOI number, then
    chronological delivery round (initial delivery before monitoring round
    1 before round 2, etc), then by format category (GeoPackage/spreadsheet
    first, PDF map last) - so the list reads as the event's timeline rather
    than an arbitrary order."""
    round_rank = product["monitoringNumber"] if product.get("monitoring") else 0
    return (product["aoiNumber"], round_rank, _FORMAT_ORDER.get(format_key, 99))


def resource_format(format_key: str) -> str:
    """Returns the HDX format string for a resource format key, eg. "gpkg" ->
    "geopackage"."""
    return _FORMAT_HDX_FORMATS[format_key]


def resource_title(product: dict, format_key: str, resource_prefix: str) -> str:
    """Returns a lowercase, underscore-separated name for a (product,
    format) resource, for use as the HDX resource's name.

    Args:
        product: A selected product dict (see select_products)
        format_key: One of "vectors"/"gpkg"/"pdf"/"xlsx"
        resource_prefix: Country/org prefix, eg. "ven_copernicus_ems" for a
            single-country activation or "copernicus_ems" for a
            multi-country one (the activation code itself isn't included
            here - it's already in describe_resource's description text)

    Returns:
        A resource name, eg. "ven_copernicus_ems_aoi01_delineation_initial.gpkg" - the
        format key is only added as a name segment when the extension alone wouldn't
        convey it (eg. "vectors", a zipped shapefile, would otherwise just read ".zip").
    """
    type_slug = _PRODUCT_TYPE_SLUGS.get(product["type"], product["type"].lower())
    round_slug = _round_slug(product.get("monitoring"), product.get("monitoringNumber"))
    extension = _FORMAT_EXTENSIONS[format_key]
    format_part = f"_{format_key}" if format_key != extension else ""
    return (
        f"{resource_prefix}_aoi{product['aoiNumber']:02d}_{type_slug}_{round_slug}"
        f"{format_part}.{extension}"
    )


def describe_resource(
    product: dict, format_key: str, code: str, activation_name: str
) -> str:
    """Returns a human-readable description for a single (product, format)
    resource.

    Args:
        product: A selected product dict (see select_products)
        format_key: One of "vectors"/"gpkg"/"pdf"/"xlsx"
        code: Activation code, eg. "EMSR900"
        activation_name: Activation name, eg. "Wildfire in Central Spain"

    Returns:
        A one-sentence resource description
    """
    type_label = _PRODUCT_TYPE_LABELS.get(product["type"], f"{product['type']} product")
    round_label = _round_label(
        product.get("monitoring"), product.get("monitoringNumber")
    )
    format_label = _FORMAT_LABELS[format_key]
    return (
        f"{format_label} containing the {type_label} for Area of Interest "
        f"{product['aoiNumber']} of the {activation_name} ({code}), from "
        f"{round_label}."
    )


def describe_product_types(products: list) -> str:
    """Returns a dataset-notes snippet explaining which Copernicus EMS
    product type codes (DEL/GRA/FEP) are present among the given selected
    products.

    Args:
        products: Selected product dicts (see select_products)

    Returns:
        A notes snippet, or "" if none of the recognised codes are present
    """
    types_present = {product["type"] for product in products}
    lines = [
        _PRODUCT_TYPE_NOTES[product_type]
        for product_type in ("DEL", "GRA", "FEP")
        if product_type in types_present
    ]
    if not lines:
        return ""
    note = (
        "\n\n**Product types present in this dataset's resources:**  \n"
        + "  \n".join(lines)
    )
    if any("gpkg" in product.get("links", {}) for product in products):
        note += (
            "\n\nWhere a GeoPackage download is available for an Area of "
            "Interest/round, it already contains every layer with its "
            "official Copernicus styling and colours - prefer it in GIS "
            "software over the zipped shapefile download."
        )
    return note
