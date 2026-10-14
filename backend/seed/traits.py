"""Category behaviour tables: how each category sells (`seed-data-spec.md` sections 5 and 7).

Weekday profiles run Monday to Sunday. Season keys map the three seasonal windows of the India
calendar to multipliers. Event tables give (pre peak, during, post) multipliers per category slug.
"""

from dataclasses import dataclass

WEEKDAY_PROFILES: dict[str, tuple[float, ...]] = {
    "flat": (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    "staple": (0.9, 1.0, 1.0, 1.0, 1.0, 1.05, 1.0),
    "weekend": (0.9, 0.95, 0.95, 1.0, 1.05, 1.25, 1.3),
    "mild_weekend": (0.92, 0.97, 0.97, 1.0, 1.03, 1.1, 1.12),
    "chronic": (1.1, 1.0, 1.0, 1.0, 1.0, 1.1, 0.8),
    "otc": (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.85),
}


@dataclass(frozen=True)
class FmcgTraits:
    base_lo: float
    base_hi: float
    weekday: str
    monthday: str
    season: str
    elast_lo: float
    elast_hi: float
    tracked: bool
    shelf_lo: int
    shelf_hi: int
    margin_lo: float
    margin_hi: float
    q: float = 1.0  # probability that a day has any demand when intermittent


FMCG_TRAITS: dict[str, FmcgTraits] = {
    "atta-rice-grains": FmcgTraits(
        1, 6, "staple", "ration", "none", 0.2, 0.4, False, 180, 365, 0.89, 0.92
    ),
    "pulses-dal": FmcgTraits(
        1, 4, "staple", "ration", "none", 0.2, 0.4, False, 365, 365, 0.88, 0.92
    ),
    "edible-oils-ghee": FmcgTraits(
        1, 4, "staple", "ration", "oil", 0.25, 0.5, False, 270, 365, 0.89, 0.93
    ),
    "sugar-salt-jaggery": FmcgTraits(
        2, 5, "staple", "ration", "sugar", 0.2, 0.4, False, 365, 730, 0.9, 0.93
    ),
    "spices-masalas": FmcgTraits(
        1, 3, "flat", "flat", "none", 0.3, 0.6, False, 365, 365, 0.82, 0.9
    ),
    "tea-coffee": FmcgTraits(1, 4, "flat", "flat", "tea", 0.4, 0.8, False, 365, 365, 0.84, 0.9),
    "biscuits-cookies": FmcgTraits(
        3, 12, "weekend", "flat", "monsoon_snack", 0.8, 1.6, True, 180, 270, 0.82, 0.9
    ),
    "namkeen-snacks": FmcgTraits(
        2, 8, "weekend", "salary", "monsoon_snack", 0.8, 1.6, True, 90, 180, 0.8, 0.88
    ),
    "chocolates-sweets": FmcgTraits(
        1, 6, "weekend", "salary", "none", 0.9, 1.6, False, 180, 365, 0.8, 0.9
    ),
    "dry-fruits": FmcgTraits(
        0.3, 2, "mild_weekend", "flat", "dry", 0.8, 1.4, True, 150, 180, 0.84, 0.88, 0.8
    ),
    "beverages": FmcgTraits(2, 10, "weekend", "flat", "bev", 0.8, 1.6, False, 90, 270, 0.82, 0.9),
    "packaged-foods": FmcgTraits(
        1, 5, "mild_weekend", "salary", "none", 0.6, 1.2, True, 180, 365, 0.82, 0.9
    ),
    "dairy-eggs": FmcgTraits(1, 5, "flat", "flat", "none", 0.3, 0.6, True, 30, 180, 0.88, 0.92),
    "personal-care": FmcgTraits(
        1, 5, "flat", "salary", "none", 0.5, 1.0, False, 730, 1095, 0.8, 0.9
    ),
    "home-care": FmcgTraits(1, 4, "flat", "flat", "none", 0.5, 1.0, False, 730, 730, 0.8, 0.9),
    "festival-puja": FmcgTraits(
        0.2, 3, "flat", "flat", "none", 0.5, 1.0, False, 365, 1095, 0.8, 0.9, 0.7
    ),
    "baby-misc": FmcgTraits(
        0.3, 1.5, "flat", "flat", "none", 0.3, 0.8, False, 730, 730, 0.82, 0.9, 0.55
    ),
}

# Season key -> multipliers for the three windows.
FMCG_SEASONS: dict[str, dict[str, float]] = {
    "none": {},
    "bev": {"summer": 1.5, "monsoon": 0.9, "winter": 0.95},
    "tea": {"monsoon": 1.3, "winter": 1.3, "summer": 0.85},
    "monsoon_snack": {"monsoon": 1.2},
    "dry": {"winter": 1.4, "summer": 0.9},
    "oil": {"winter": 1.1},
    "sugar": {"winter": 1.1},
}

# Event effects on FMCG categories: event_key -> category slug -> (pre peak, during, post).
FMCG_EVENTS: dict[str, dict[str, tuple[float, float, float]]] = {
    "diwali": {
        "dry-fruits": (2.2, 2.6, 0.8),
        "chocolates-sweets": (1.8, 2.2, 0.85),
        "namkeen-snacks": (1.5, 1.6, 0.9),
        "home-care": (1.5, 1.2, 0.9),
        "festival-puja": (3.0, 3.5, 0.4),
        "edible-oils-ghee": (1.3, 1.2, 0.95),
        "sugar-salt-jaggery": (1.3, 1.2, 0.95),
    },
    "ganesh_chaturthi": {
        "festival-puja": (2.5, 3.0, 0.5),
        "dry-fruits": (1.3, 1.4, 0.9),
        "sugar-salt-jaggery": (1.3, 1.4, 0.9),
        "atta-rice-grains": (1.3, 1.4, 0.9),
    },
    "navratri_dussehra": {
        "festival-puja": (1.8, 2.0, 0.6),
        "dry-fruits": (1.2, 1.2, 1.0),
        "chocolates-sweets": (1.2, 1.2, 1.0),
    },
    "raksha_bandhan": {
        "chocolates-sweets": (1.8, 2.0, 0.8),
        "dry-fruits": (1.3, 1.3, 0.9),
    },
    "gudi_padwa": {
        "sugar-salt-jaggery": (1.4, 1.5, 0.9),
        "festival-puja": (1.4, 1.5, 0.9),
        "chocolates-sweets": (1.4, 1.5, 0.9),
    },
    "holi": {
        "beverages": (1.3, 1.4, 0.9),
        "chocolates-sweets": (1.3, 1.4, 0.9),
        "namkeen-snacks": (1.3, 1.4, 0.9),
    },
    "eid_fitr": {
        "dry-fruits": (1.4, 1.5, 0.9),
        "sugar-salt-jaggery": (1.4, 1.5, 0.9),
        "dairy-eggs": (1.4, 1.5, 0.9),
    },
    "eid_adha": {
        "dry-fruits": (1.4, 1.5, 0.9),
        "sugar-salt-jaggery": (1.4, 1.5, 0.9),
        "dairy-eggs": (1.4, 1.5, 0.9),
    },
    "christmas_ny": {
        "chocolates-sweets": (1.3, 1.4, 0.9),
        "beverages": (1.3, 1.4, 0.9),
        "namkeen-snacks": (1.3, 1.4, 0.9),
    },
    "makar_sankranti": {
        "sugar-salt-jaggery": (1.4, 1.5, 0.9),
        "chocolates-sweets": (1.4, 1.5, 0.9),
        "dry-fruits": (1.4, 1.5, 0.9),
    },
}

# Planted negative cases (scenario S02): no real effect of the event on the category.
NO_EFFECT_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "fmcg_a": (("holi", "namkeen-snacks"), ("raksha_bandhan", "dry-fruits")),
    "fmcg_b": (("holi", "beverages"), ("christmas_ny", "namkeen-snacks")),
}
TENANT_EVENT_BOOST: dict[str, dict[str, float]] = {
    "fmcg_a": {"ganesh_chaturthi": 1.15, "diwali": 1.15},
    "fmcg_b": {},
}
# Events that stocked up categories dip after the post window (spec: 0.85 for 3 days).
MAJOR_EVENTS = frozenset({"diwali", "ganesh_chaturthi"})
AFTER_DIP_DAYS = 3
AFTER_DIP_LEVEL = 0.85
# Reduced trading hours: volume factor on the single day (spec section 4).
REDUCED_HOURS_FACTOR = 0.4


@dataclass(frozen=True)
class MedTraits:
    base: float
    weekday: str
    monthday: str
    season: dict[str, float]
    q: float = 1.0


MED_TRAITS: dict[str, MedTraits] = {
    "analgesics-antipyretics": MedTraits(1.2, "otc", "flat", {"monsoon": 1.35}),
    "antibiotics": MedTraits(0.7, "otc", "flat", {"monsoon": 1.3, "winter": 1.25}, 0.8),
    "antidiabetics": MedTraits(1.4, "chronic", "chronic", {}),
    "cardiac-antihypertensives": MedTraits(1.5, "chronic", "chronic", {}),
    "gastro-antacids": MedTraits(1.0, "otc", "flat", {"monsoon": 1.5, "summer": 1.15}),
    "respiratory-cough-cold": MedTraits(0.8, "otc", "flat", {"monsoon": 1.3, "winter": 1.5}, 0.85),
    "antiallergics": MedTraits(0.6, "otc", "flat", {"monsoon": 1.25, "winter": 1.2}, 0.8),
    "vitamins-supplements": MedTraits(0.9, "otc", "flat", {"winter": 1.3, "monsoon": 1.1}),
    "dermatology": MedTraits(0.6, "otc", "flat", {"monsoon": 1.6, "winter": 1.3}, 0.8),
    "eye-ear-oral": MedTraits(0.4, "otc", "flat", {"monsoon": 1.2}, 0.6),
    "first-aid-dressings": MedTraits(0.5, "otc", "flat", {}, 0.65),
    "baby-care": MedTraits(0.7, "otc", "flat", {}, 0.85),
    "womens-health": MedTraits(0.8, "otc", "flat", {}, 0.9),
    "devices-diagnostics": MedTraits(0.12, "otc", "flat", {"winter": 1.1}, 0.4),
    "ors-hydration": MedTraits(0.7, "otc", "flat", {"summer": 1.8, "monsoon": 1.5}, 0.9),
    "pain-relief-topicals": MedTraits(0.6, "otc", "flat", {"winter": 1.4}, 0.8),
    "thyroid-chronic": MedTraits(1.1, "chronic", "chronic", {}),
    "hygiene-sanitisers": MedTraits(0.5, "otc", "flat", {}, 0.85),
    "ayurvedic-wellness": MedTraits(0.5, "otc", "flat", {"winter": 1.35}, 0.8),
    "nutrition-diabetic-foods": MedTraits(0.5, "otc", "flat", {}, 0.8),
}

# Planted spurious single-occurrence uplift in medical (scenario S02 negative case).
MED_SPURIOUS: dict[str, tuple[str, str, float]] = {
    "med_a": ("diwali", "vitamins-supplements", 1.35),
    "med_b": ("diwali", "ors-hydration", 1.35),
}
