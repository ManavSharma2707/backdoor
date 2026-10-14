"""Catalogue YAML: counts per category, supplier bands, fictional names, no locations."""

import re
from collections import Counter
from typing import Any

import pytest
import yaml

from seed.catalog.builder import build_tenant
from seed.catalog.fmcg_templates import FMCG_CATEGORIES
from seed.catalog.med_templates import MED_CATEGORIES
from seed.profiles import DEFAULT_BASE_SEED, PROFILES, Profile

# Small blocklist of real brands and chains the catalogue must not imitate.
REAL_BRANDS = (
    "tata",
    "amul",
    "britannia",
    "parle",
    "nestle",
    "maggi",
    "fortune",
    "saffola",
    "aashirvaad",
    "dabur",
    "patanjali",
    "colgate",
    "dettol",
    "surf excel",
    "ariel",
    "crocin",
    "dolo",
    "calpol",
    "combiflam",
    "augmentin",
    "azithral",
    "glycomet",
    "amaryl",
    "januvia",
    "norvasc",
    "telma",
    "lipitor",
    "pantocid",
    "eltroxin",
    "thyronorm",
    "volini",
    "moov",
    "betadine",
    "savlon",
    "himalaya",
    "zandu",
    "pampers",
    "huggies",
    "whisper",
    "stayfree",
    "accu-chek",
    "omron",
    "revital",
    "becosules",
    "shelcal",
    "limcee",
    "digene",
    "gelusil",
    "vicks",
    "benadryl",
    "ascoril",
    "haldiram",
    "bisleri",
    "pepsi",
    "coca",
    "sprite",
    "lays",
    "kurkura",
    "cadbury",
    "dairy milk",
    "kitkat",
    "dmart",
    "reliance",
    "bigbasket",
    "apollo",
    "medplus",
    "wellness forever",
)
LOCATION_WORDS = (
    "mumbai",
    "pune",
    "nagpur",
    "nashik",
    "thane",
    "delhi",
    "kolkata",
    "chennai",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "maharashtra",
    "gujarat",
    "karnataka",
    "kerala",
    "goa",
    "india",
    "district",
    "taluka",
    "road",
    "nagar",
    "street",
    "colony",
)

CATALOGS = [pytest.param(k, id=k) for k in PROFILES]


def _load(profile: Profile) -> dict[str, Any]:
    with profile.catalog_path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return data


@pytest.mark.parametrize("key", CATALOGS)
def test_catalogue_counts_match_the_spec(key: str) -> None:
    profile = PROFILES[key]
    data = _load(profile)
    assert len(data["products"]) == profile.skus
    table = MED_CATEGORIES if profile.is_medical else FMCG_CATEGORIES
    per_category = Counter(p["category"] for p in data["products"])
    for slug, (_, n_a, n_b, _items) in table.items():
        expected = n_a if key.endswith("_a") else n_b
        assert per_category[slug] == expected, slug
    assert {c["slug"] for c in data["categories"]} == set(table)


@pytest.mark.parametrize("key", CATALOGS)
def test_catalogue_file_is_what_the_builder_produces(key: str) -> None:
    profile = PROFILES[key]
    built = yaml.safe_load(
        yaml.safe_dump(build_tenant(profile, DEFAULT_BASE_SEED), sort_keys=False)
    )
    assert built == _load(profile)


@pytest.mark.parametrize("key", CATALOGS)
def test_suppliers_stay_within_the_spec_bands(key: str) -> None:
    profile = PROFILES[key]
    data = _load(profile)
    suppliers = data["suppliers"]
    assert 5 <= len(suppliers) <= 9
    codes = {s["code"] for s in suppliers}
    assert len(codes) == len(suppliers)
    lead_cap = 3 if profile.is_medical else 4
    for s in suppliers:
        if s["planted"] == "cash_vendor":
            assert s["default_lead_time_days"] is None
            continue
        assert 1 <= s["default_lead_time_days"] <= lead_cap
        assert 2 <= len(s["delivery_weekdays"]) <= 5
        assert set(s["order_weekdays"]) <= set(s["delivery_weekdays"])
        assert 0 <= s["payment_terms_days"] <= 30
        assert 0.08 <= s["delay_prob"] <= 0.25
        assert 0.9 <= s["fill_rate"] <= 1.0
        assert 3 <= s["return_window_days"] <= 15
        if s["accepts_expiry_returns"]:
            assert s["expiry_return_window_days"] in {60, 75, 90}
    assigned = {p["supplier"] for p in data["products"]}
    assert assigned <= codes


@pytest.mark.parametrize("key", CATALOGS)
def test_products_are_priced_and_named_sensibly(key: str) -> None:
    data = _load(PROFILES[key])
    skus = [p["sku"] for p in data["products"]]
    names = [p["name"] for p in data["products"]]
    assert len(set(skus)) == len(skus)
    assert len(set(names)) == len(names)
    for p in data["products"]:
        mrp = float(p["mrp"])
        assert 0 < float(p["selling_price"]) <= mrp
        assert float(p["purchase_price"]) < float(p["selling_price"])
        assert p["tax"] in {"GST0", "GST5", "GST18", "GST40"}
        assert p["pack_size"] >= 1
        assert p["moq_units"] % p["pack_size"] == 0
        if p["is_batch_tracked"]:
            assert p["shelf_life_days"]
            assert p["shelf_life_days"] > 0
        if PROFILES[key].is_medical:
            assert 5 <= mrp <= 2500
        margin = 1 - float(p["purchase_price"]) / float(p["selling_price"])
        assert margin < 0.40


@pytest.mark.parametrize("key", CATALOGS)
def test_no_real_brands_and_no_locations_in_the_catalogue(key: str) -> None:
    text = PROFILES[key].catalog_path.read_text(encoding="utf-8").lower()
    for brand in REAL_BRANDS:
        assert not re.search(rf"\b{re.escape(brand)}\b", text), brand
    for word in LOCATION_WORDS:
        assert not re.search(rf"\b{re.escape(word)}\b", text), word


def test_medical_records_have_generic_names_and_no_clinical_text() -> None:
    for key in ("med_a", "med_b"):
        data = _load(PROFILES[key])
        drugs = [p for p in data["products"] if p["generic_name"]]
        assert len(drugs) > 100
        for p in drugs:
            assert p["strength"]
            assert p["dosage_form"]
            assert p["manufacturer"]
            assert p["schedule_class"] in {None, "H", "H1"}
        text = PROFILES[key].catalog_path.read_text(encoding="utf-8").lower()
        for word in ("dose", "doses", "dosage", "indication", "patient", "prescription", "treats"):
            assert not re.search(rf"{word}", text), word
