"""Builds the catalogue YAML for the four tenants from the item templates.

`python -m seed.catalog.builder` rewrites `backend/seed/catalogs/*.yaml`. The output is a pure
function of `base_seed`, so the files are stable and reviewable. The simulation only reads the YAML.
Everything here is fictional: brands, businesses and contacts. No location appears in any name.
"""

import argparse
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np
import yaml

from seed.catalog.fmcg_templates import FMCG_CATEGORIES, Item
from seed.catalog.med_templates import MANUFACTURERS, MED_CATEGORIES, Med
from seed.profiles import CATALOG_DIR, DEFAULT_BASE_SEED, PROFILES, Profile
from seed.rng import stream
from seed.traits import FMCG_TRAITS, MED_TRAITS

CENT = Decimal("0.01")
COST_STEP = Decimal("0.0001")

FMCG_BRANDS: dict[str, tuple[str, ...]] = {
    "staples": (
        "Kisanvadi",
        "Madhuvan",
        "Anaj Ghar",
        "Pavitra Mill",
        "Sunheri",
        "Haritkund",
        "Tilvan",
        "Ojasvi",
    ),
    "oils": ("Sudhan Gold", "Kesaria", "Telvan", "Ghani Pure", "Nandan Select", "Surmai"),
    "snacks": (
        "Zaika Ghar",
        "Crispo",
        "Munchli",
        "Bitezy",
        "Chatpata Corner",
        "Crumbly",
        "Khasta Ghar",
        "Tasty Tarang",
    ),
    "sweets": ("Mithai Mandir", "Kaju Kunj", "Meva Mahal", "Sweet Tarang", "Madhura", "Nutaro"),
    "beverages": ("Zingo", "Coolzy", "Aqua Nirmal", "Fruitoo", "Tropi Gold", "Sip Raja", "Chilla"),
    "foods": ("Easy Bite", "Rasoi Ready", "Quickmeal", "Gharkul", "Foodies Nest", "Swad Sagar"),
    "dairy": ("Ksheer Sagar", "Dugdha Fresh", "Gaay Ghar", "Malai Maa"),
    "care": (
        "Lavanya",
        "Swachh Ghar",
        "Safai Raj",
        "Tazagi",
        "Chamak Pro",
        "Suvasit",
        "Gulab Care",
        "Nirmal Roop",
    ),
    "puja": ("Pooja Mandir", "Divya Jyoti", "Shubh Labh", "Little Steps", "Paperly", "Tinkle Home"),
}
CATEGORY_BRAND_GROUP = {
    "atta-rice-grains": "staples",
    "pulses-dal": "staples",
    "edible-oils-ghee": "oils",
    "sugar-salt-jaggery": "staples",
    "spices-masalas": "staples",
    "tea-coffee": "staples",
    "biscuits-cookies": "snacks",
    "namkeen-snacks": "snacks",
    "chocolates-sweets": "sweets",
    "dry-fruits": "sweets",
    "beverages": "beverages",
    "packaged-foods": "foods",
    "dairy-eggs": "dairy",
    "personal-care": "care",
    "home-care": "care",
    "festival-puja": "puja",
    "baby-misc": "puja",
}

MED_BRAND_STARTS: dict[str, tuple[str, ...]] = {
    "default": (
        "Nova",
        "Zeta",
        "Arvi",
        "Lumi",
        "Veno",
        "Tera",
        "Mexa",
        "Rovi",
        "Fenz",
        "Orva",
        "Kelo",
        "Zyra",
        "Sanz",
        "Trio",
    ),
    "cardiac-antihypertensives": ("Cardi", "Vasco", "Hera", "Pulso", "Rhythmo", "Beato"),
    "antidiabetics": ("Gluco", "Sugar", "Insu", "Glyce", "Diabe", "Metro"),
    "dermatology": ("Derma", "Skino", "Cutis", "Epi", "Dermi"),
    "respiratory-cough-cold": ("Pulmo", "Breathe", "Respi", "Tussi", "Nasa"),
    "gastro-antacids": ("Gastro", "Acido", "Digesto", "Stoma", "Pepto"),
    "antibiotics": ("Bacto", "Zymo", "Cefo", "Mycin", "Vira"),
    "vitamins-supplements": ("Vita", "Nutri", "Revi", "Vigo", "Calci"),
}
MED_BRAND_ENDS = (
    "cet",
    "mox",
    "vir",
    "zol",
    "pril",
    "dex",
    "lin",
    "fen",
    "cip",
    "flam",
    "zine",
    "pan",
    "stat",
    "vit",
    "cure",
    "lex",
    "sone",
    "tin",
    "ral",
    "max",
)
HOUSE_BRANDS = ("Wellmark", "Healo", "Curo", "Sehat Plus", "Nirogi", "Aarogya Select")

FMCG_SUPPLIERS: dict[str, list[dict[str, Any]]] = {
    "fmcg_a": [
        {
            "name": "Om Sai Staples Wholesale",
            "contact": "Bhaskar Gadgil",
            "cats": ["atta-rice-grains", "pulses-dal", "sugar-salt-jaggery", "spices-masalas"],
        },
        {
            "name": "Kundan Oil and Ghee Distributors",
            "contact": "Prakash Naik",
            "cats": ["edible-oils-ghee"],
        },
        {
            "name": "Priya Biscuit and Snack Agency",
            "contact": "Meena Sawant",
            "cats": ["biscuits-cookies", "namkeen-snacks", "chocolates-sweets", "packaged-foods"],
        },
        {
            "name": "Shubh Beverage Distributors",
            "contact": "Rohit Phadke",
            "cats": ["beverages", "tea-coffee", "dairy-eggs"],
        },
        {
            "name": "Navkar Personal and Home Care Distributors",
            "contact": "Jayesh Shah",
            "cats": ["personal-care", "home-care", "baby-misc"],
        },
        {
            "name": "Mehta Dry Fruits and Puja Traders",
            "contact": "Hitesh Mehta",
            "cats": ["dry-fruits", "festival-puja"],
        },
    ],
    "fmcg_b": [
        {
            "name": "Vishwas Grain and Staples Company",
            "contact": "Anant Bhosale",
            "cats": ["atta-rice-grains", "pulses-dal", "sugar-salt-jaggery", "spices-masalas"],
        },
        {"name": "Sagar Edible Oil Agency", "contact": "Dilip Rane", "cats": ["edible-oils-ghee"]},
        {
            "name": "Rasik Biscuits and Snacks Distribution",
            "contact": "Neha Kamat",
            "cats": ["biscuits-cookies", "namkeen-snacks", "chocolates-sweets", "tea-coffee"],
        },
        {"name": "Coolwave Beverage Agency", "contact": "Sameer Pathak", "cats": ["beverages"]},
        {
            "name": "Gharkul Care Products Distributors",
            "contact": "Vinita More",
            "cats": ["personal-care", "home-care", "baby-misc"],
        },
        {
            "name": "Shreeji Dry Fruits and Festival Goods",
            "contact": "Kiran Jain",
            "cats": ["dry-fruits", "festival-puja"],
        },
        {"name": "Ksheer Fresh Dairy Distribution", "contact": "Ashok Lad", "cats": ["dairy-eggs"]},
        {
            "name": "Foodline Packaged Foods Distributors",
            "contact": "Tanvi Oak",
            "cats": ["packaged-foods"],
        },
    ],
}
MED_SUPPLIERS: dict[str, list[dict[str, Any]]] = {
    "med_a": [
        {
            "name": "Lifeline General Stockists",
            "contact": "Dinesh Pawar",
            "cats": [
                "analgesics-antipyretics",
                "gastro-antacids",
                "vitamins-supplements",
                "first-aid-dressings",
                "ors-hydration",
                "hygiene-sanitisers",
                "eye-ear-oral",
            ],
        },
        {
            "name": "Acute Care Pharma Distribution",
            "contact": "Sheetal Kadam",
            "cats": [
                "antibiotics",
                "respiratory-cough-cold",
                "antiallergics",
                "dermatology",
                "pain-relief-topicals",
            ],
        },
        {
            "name": "Chronic Care Stockists",
            "contact": "Mahesh Thakur",
            "cats": ["antidiabetics", "cardiac-antihypertensives", "thyroid-chronic"],
        },
        {
            "name": "Medico Devices and OTC Wholesale",
            "contact": "Rupal Doshi",
            "cats": ["devices-diagnostics", "womens-health", "baby-care"],
        },
        {
            "name": "Ayushya Wellness Traders",
            "contact": "Smita Bapat",
            "cats": ["ayurvedic-wellness", "nutrition-diabetic-foods"],
        },
    ],
    "med_b": [
        {
            "name": "Sehat General Distributors",
            "contact": "Girish Salvi",
            "cats": [
                "analgesics-antipyretics",
                "gastro-antacids",
                "vitamins-supplements",
                "first-aid-dressings",
                "ors-hydration",
                "hygiene-sanitisers",
                "eye-ear-oral",
            ],
        },
        {
            "name": "Rapid Acute Medicines Agency",
            "contact": "Namrata Gupte",
            "cats": [
                "antibiotics",
                "respiratory-cough-cold",
                "antiallergics",
                "dermatology",
                "pain-relief-topicals",
            ],
        },
        {
            "name": "Hridaya Chronic Medicines Stockist",
            "contact": "Vivek Apte",
            "cats": ["antidiabetics", "cardiac-antihypertensives", "thyroid-chronic"],
        },
        {
            "name": "Surgi Devices and OTC Wholesale",
            "contact": "Payal Chheda",
            "cats": ["devices-diagnostics", "womens-health"],
        },
        {
            "name": "Prakruti Ayurvedic Traders",
            "contact": "Omkar Joshi",
            "cats": ["ayurvedic-wellness"],
        },
        {
            "name": "Little Ones Baby and Nutrition Supply",
            "contact": "Reshma Dixit",
            "cats": ["baby-care", "nutrition-diabetic-foods"],
        },
    ],
}
CASH_VENDOR = {"name": "Walk-in Cash Vendor", "contact": "Counter purchase"}

# Order value bands scaled to the size of each business (spec band is 3,000 to 25,000).
MOV_BANDS = {
    "fmcg_a": (3000, 9000),
    "fmcg_b": (6000, 25000),
    "med_a": (3000, 10000),
    "med_b": (4000, 15000),
}


def _money(value: float | Decimal, step: Decimal = CENT) -> str:
    return str(Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP))


def _supplier_rows(profile: Profile, rng: np.random.Generator) -> list[dict[str, Any]]:
    specs = (MED_SUPPLIERS if profile.is_medical else FMCG_SUPPLIERS)[profile.key]
    lo_lead, hi_lead = (1, 3) if profile.is_medical else (1, 4)
    mov_lo, mov_hi = MOV_BANDS[profile.key]
    rows: list[dict[str, Any]] = []
    for i, spec in enumerate(specs, start=1):
        n_days = int(rng.integers(2, 6))
        delivery = sorted(int(d) for d in rng.choice(np.arange(1, 7), size=n_days, replace=False))
        n_order = int(rng.integers(1, 3))
        order_days = sorted(
            int(d) for d in rng.choice(delivery, size=min(n_order, n_days), replace=False)
        )
        accepts = bool(rng.random() < (0.8 if profile.is_medical else 0.2))
        rows.append(
            {
                "code": f"S{i:02d}",
                "name": spec["name"],
                "contact_name": spec["contact"],
                "payment_terms_days": int(rng.choice([0, 7, 15, 21, 30])),
                "default_lead_time_days": int(rng.integers(lo_lead, hi_lead + 1)),
                "delivery_weekdays": delivery,
                "order_weekdays": order_days,
                "min_order_value": _money(int(round(rng.uniform(mov_lo, mov_hi), -2))),
                "credit_limit": _money(int(round(rng.uniform(40000, 250000), -3))),
                "accepts_expiry_returns": accepts,
                "expiry_return_window_days": int(rng.choice([60, 75, 90])) if accepts else None,
                "return_window_days": int(rng.integers(3, 16)),
                "delay_prob": round(float(rng.uniform(0.08, 0.25)), 3),
                "delay_days_min": 1,
                "delay_days_max": int(rng.integers(2, 5)),
                "fill_rate": round(float(rng.uniform(0.9, 1.0)), 3),
                "categories": spec["cats"],
                "planted": None,
            }
        )
    rows.append(
        {
            "code": f"S{len(rows) + 1:02d}",
            "name": CASH_VENDOR["name"],
            "contact_name": CASH_VENDOR["contact"],
            "payment_terms_days": 0,
            "default_lead_time_days": None,
            "delivery_weekdays": [1, 2, 3, 4, 5, 6],
            "order_weekdays": [3],
            "min_order_value": None,
            "credit_limit": None,
            "accepts_expiry_returns": False,
            "expiry_return_window_days": None,
            "return_window_days": None,
            "delay_prob": 0.1,
            "delay_days_min": 1,
            "delay_days_max": 2,
            "fill_rate": 0.98,
            "categories": [],
            "planted": "cash_vendor",
        }
    )
    return rows


def _pack_size(
    rng: np.random.Generator, mrp: int, category: str, is_medical: bool, device: bool
) -> int:
    if device:
        return 1
    if is_medical:
        if mrp < 60:
            return int(rng.choice([50, 100]))
        if mrp < 250:
            return int(rng.choice([10, 50]))
        return 10 if mrp < 700 else 5
    if category in {"atta-rice-grains", "pulses-dal", "sugar-salt-jaggery"} and mrp >= 90:
        return int(rng.choice([1, 5]))
    if mrp < 30:
        return int(rng.choice([24, 48]))
    if mrp < 80:
        return int(rng.choice([12, 24]))
    if mrp < 200:
        return int(rng.choice([6, 12]))
    if mrp < 500:
        return int(rng.choice([4, 6]))
    return int(rng.choice([1, 2]))


def _selling(rng: np.random.Generator, profile: Profile, mrp: int) -> int:
    if profile.key in {"fmcg_b", "med_b"} and mrp >= 40 and rng.random() < 0.35:
        return max(1, math.floor(mrp * float(rng.uniform(0.95, 0.98))))
    return mrp


def _med_brand(rng: np.random.Generator, category: str, used: set[str]) -> str:
    starts = MED_BRAND_STARTS.get(category, MED_BRAND_STARTS["default"])
    for _ in range(200):
        pool = starts if rng.random() < 0.6 else MED_BRAND_STARTS["default"]
        stem = str(rng.choice(pool)) + str(rng.choice(MED_BRAND_ENDS))
        if stem not in used:
            used.add(stem)
            return stem
    raise RuntimeError("Could not make a unique brand name")


def _digits(text: str) -> str:
    out = ""
    for ch in text:
        if ch.isdigit():
            out += ch
        elif out:
            break
    return out


def _fmcg_products(
    profile: Profile, rng: np.random.Generator, suppliers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    is_a = profile.key == "fmcg_a"
    sup_by_cat = {c: s["code"] for s in suppliers for c in s["categories"]}
    cats: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for position, (slug, (cname, n_a, n_b, items)) in enumerate(FMCG_CATEGORIES.items()):
        cats.append({"slug": slug, "name": cname, "position": position})
        n = n_a if is_a else n_b
        traits = FMCG_TRAITS[slug]
        group = FMCG_BRANDS[CATEGORY_BRAND_GROUP[slug]]
        order = list(rng.permutation(len(items)))
        for k in range(n):
            item: Item = items[order[k % len(items)]]
            pack = str(rng.choice(item.packs))
            label, unit, mrp_s = pack.split(":")
            mrp = int(mrp_s)
            brand = str(rng.choice(group))
            name = f"{brand} {item.name} {label}"
            if name in used_names:
                brand = str(rng.choice(group))
                name = f"{brand} {item.name} {label}"
            suffix = 2
            while name in used_names:
                name = f"{brand} {item.name} {label} Pack {suffix}"
                suffix += 1
            used_names.add(name)
            seq = len(products) + 1
            base = float(rng.uniform(traits.base_lo, traits.base_hi))
            base *= float(np.clip(rng.lognormal(0.0, 0.35), 0.5, 1.8))
            base *= float(np.clip((60.0 / mrp) ** 0.2, 0.6, 1.5))
            q = traits.q if traits.q < 1.0 else (0.6 if base < 0.8 else 1.0)
            margin = float(rng.uniform(traits.margin_lo, traits.margin_hi))
            if slug == "dry-fruits":
                margin = 0.85
            shelf = int(rng.integers(traits.shelf_lo, traits.shelf_hi + 1))
            pack_size = _pack_size(rng, mrp, slug, False, False)
            products.append(
                {
                    "sku": f"{'FA' if is_a else 'FB'}-{seq:03d}",
                    "barcode": f"2{profile.index}{seq:05d}{int(rng.integers(100000, 999999))}",
                    "name": name,
                    "brand": brand,
                    "category": slug,
                    "base_unit": unit,
                    "pack_label": label,
                    "tax": item.gst,
                    "mrp": _money(mrp),
                    "selling_price": _money(_selling(rng, profile, mrp)),
                    "is_batch_tracked": traits.tracked,
                    "shelf_life_days": shelf,
                    "supplier": sup_by_cat[slug],
                    "purchase_price": _money(mrp * margin, COST_STEP),
                    "pack_size": pack_size,
                    "moq_units": pack_size * int(rng.integers(0, 4)),
                    "term_lead_time_days": int(rng.integers(1, 5)) if rng.random() < 0.15 else None,
                    "min_stock_qty": max(1, math.ceil(base * 2)),
                    "is_seasonal": slug in {"festival-puja", "dry-fruits"}
                    or traits.season not in {"none"},
                    "chronic": False,
                    "item_tag": item.tag,
                    "traits": {
                        "base_rate": round(base, 4),
                        "q": q,
                        "nb_size": round(float(rng.uniform(4.0, 12.0)), 2),
                        "elasticity": round(
                            float(rng.uniform(traits.elast_lo, traits.elast_hi)), 3
                        ),
                        "trend_pct_year": round(float(rng.uniform(-15.0, 20.0)), 2),
                        "event_jitter": round(float(rng.uniform(0.85, 1.15)), 3),
                    },
                }
            )
    return cats, products


def _med_products(
    profile: Profile, rng: np.random.Generator, suppliers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    is_a = profile.key == "med_a"
    sup_by_cat = {c: s["code"] for s in suppliers for c in s["categories"]}
    cats: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    used_brands: set[str] = set()
    used_names: set[str] = set()
    for position, (slug, (cname, n_a, n_b, items)) in enumerate(MED_CATEGORIES.items()):
        cats.append({"slug": slug, "name": cname, "position": position})
        n = n_a if is_a else n_b
        traits = MED_TRAITS[slug]
        order = list(rng.permutation(len(items)))
        for k in range(n):
            m: Med = items[order[k % len(items)]]
            seq = len(products) + 1
            if m.kind in {"drug"}:
                brand = _med_brand(rng, slug, used_brands)
                digits = _digits(m.strength)
                name = f"{brand} {digits}" if digits else f"{brand} {m.form}"
            else:
                brand = str(rng.choice(HOUSE_BRANDS))
                name = f"{brand} {m.generic}"
                if m.strength not in {"standard"}:
                    name += f" {m.strength}"
            if name in used_names:
                name += f" {m.pack}"
            n_try = 2
            while name in used_names:
                name = f"{name} {n_try}"
                n_try += 1
            used_names.add(name)
            base = traits.base * float(np.clip(rng.lognormal(0.0, 0.5), 0.35, 2.4))
            base *= float(np.clip((80.0 / m.mrp) ** 0.2, 0.6, 1.6))
            margin = float(rng.uniform(0.78, 0.88))
            tracked = m.tracked and m.shelf_months > 0
            pack_size = _pack_size(rng, m.mrp, slug, True, m.kind == "device")
            drug = m.kind == "drug"
            products.append(
                {
                    "sku": f"{'MA' if is_a else 'MB'}-{seq:03d}",
                    "barcode": f"2{profile.index}{seq:05d}{int(rng.integers(100000, 999999))}",
                    "name": name,
                    "brand": brand,
                    "category": slug,
                    "base_unit": m.unit,
                    "pack_label": m.pack,
                    "tax": m.gst,
                    "mrp": _money(m.mrp),
                    "selling_price": _money(_selling(rng, profile, m.mrp)),
                    "is_batch_tracked": tracked,
                    "shelf_life_days": m.shelf_months * 30 if tracked else None,
                    "supplier": sup_by_cat[slug],
                    "purchase_price": _money(m.mrp * margin, COST_STEP),
                    "pack_size": pack_size,
                    "moq_units": pack_size * int(rng.integers(0, 3)),
                    "term_lead_time_days": int(rng.integers(1, 4)) if rng.random() < 0.15 else None,
                    "min_stock_qty": max(1, math.ceil(base * 3)),
                    "is_seasonal": bool(traits.season),
                    "chronic": m.chronic,
                    "item_tag": m.kind,
                    "generic_name": m.generic if drug else None,
                    "strength": m.strength if drug else None,
                    "dosage_form": m.form if drug else None,
                    "manufacturer": str(rng.choice(MANUFACTURERS)) if drug else None,
                    "schedule_class": (m.sched or None) if drug else None,
                    "traits": {
                        "base_rate": round(base, 4),
                        "q": traits.q if traits.q < 1.0 else (0.7 if base < 0.4 else 1.0),
                        "nb_size": round(float(rng.uniform(3.0, 10.0)), 2),
                        "elasticity": round(float(rng.uniform(0.1, 0.3)), 3),
                        "trend_pct_year": round(float(rng.uniform(-15.0, 20.0)), 2),
                        "event_jitter": 1.0,
                    },
                }
            )
    return cats, products


def build_tenant(profile: Profile, base_seed: int = DEFAULT_BASE_SEED) -> dict[str, Any]:
    sup_rng = stream(base_seed, profile.index, "supplier")
    suppliers = _supplier_rows(profile, sup_rng)
    rng = stream(base_seed, profile.index, "catalog")
    builder = _med_products if profile.is_medical else _fmcg_products
    categories, products = builder(profile, rng, suppliers)
    if len(products) != profile.skus:
        raise RuntimeError(
            f"{profile.key}: built {len(products)} products, expected {profile.skus}"
        )
    return {
        "tenant": profile.key,
        "note": "Synthetic catalogue. Brands, businesses and prices are fictional.",
        "gst_note": "GST slab mapping is representative only and is not tax advice.",
        "suppliers": suppliers,
        "categories": categories,
        "products": products,
    }


def write_all(base_seed: int = DEFAULT_BASE_SEED) -> list[str]:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for profile in PROFILES.values():
        data = build_tenant(profile, base_seed)
        path = profile.catalog_path
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True, width=100)
        written.append(str(path))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the catalogue YAML files")
    parser.add_argument("--seed", type=int, default=DEFAULT_BASE_SEED)
    args = parser.parse_args()
    for path in write_all(args.seed):
        print(path)  # noqa: T201


if __name__ == "__main__":
    main()
