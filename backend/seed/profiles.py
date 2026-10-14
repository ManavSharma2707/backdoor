"""Tenant profiles: names, owners and size targets (`seed-data-spec.md` sections 1 and 4)."""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DEFAULT_BASE_SEED = 20261011
DEFAULT_END_DATE = date(2026, 10, 11)
HISTORY_DAYS = 546
OPENING_OFFSET_DAYS = 1

SEED_ROOT = Path(__file__).resolve().parent
CATALOG_DIR = SEED_ROOT / "catalogs"
SCENARIOS_PATH = SEED_ROOT / "scenarios.yaml"
REALISM_PATH = SEED_ROOT / "realism_report.md"


@dataclass(frozen=True)
class Profile:
    key: str
    index: int
    slug: str
    name: str
    business_type: str
    skus: int
    owner_name: str
    owner_email: str
    bills_per_day: float
    lines_per_bill: float
    story: str

    @property
    def is_medical(self) -> bool:
        return self.business_type == "medical"

    @property
    def target_lines_per_day(self) -> float:
        return self.bills_per_day * self.lines_per_bill

    @property
    def catalog_path(self) -> Path:
        return CATALOG_DIR / f"{self.key}.yaml"


PROFILES: dict[str, Profile] = {
    p.key: p
    for p in (
        Profile(
            "fmcg_a",
            0,
            "shree-sai-kirana",
            "Shree Sai Kirana and General Stores",
            "fmcg",
            92,
            "Ramesh Kulkarni",
            "owner.fmcg-a@backroom-demo.com",
            55,
            2.4,
            "Small neighbourhood grocery with tight cash",
        ),
        Profile(
            "fmcg_b",
            1,
            "mahalaxmi-super-mart",
            "Mahalaxmi Super Mart",
            "fmcg",
            118,
            "Sunita Deshmukh",
            "owner.fmcg-b@backroom-demo.com",
            110,
            2.9,
            "Mid-size supermarket with many promotions",
        ),
        Profile(
            "med_a",
            2,
            "sanjivani-medical",
            "Sanjivani Medical and General",
            "medical",
            150,
            "Anil Joshi",
            "owner.med-a@backroom-demo.com",
            55,
            1.7,
            "Neighbourhood pharmacy, chronic refills",
        ),
        Profile(
            "med_b",
            3,
            "aarogya-care-pharmacy",
            "Aarogya Care Pharmacy",
            "medical",
            152,
            "Pooja Patil",
            "owner.med-b@backroom-demo.com",
            90,
            1.9,
            "Clinic adjacent pharmacy with large expiry exposure",
        ),
    )
}


def history_start(end_date: date) -> date:
    return end_date - timedelta(days=HISTORY_DAYS - 1)


def opening_date(end_date: date) -> date:
    return history_start(end_date) - timedelta(days=OPENING_OFFSET_DAYS)


def resolve_tenants(spec: str) -> list[Profile]:
    if spec == "all":
        return list(PROFILES.values())
    keys = [k.strip() for k in spec.split(",") if k.strip()]
    unknown = [k for k in keys if k not in PROFILES]
    if unknown:
        raise ValueError(f"Unknown tenant key(s): {', '.join(unknown)}")
    return [PROFILES[k] for k in keys]
