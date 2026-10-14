"""Typed view of a catalogue YAML file, plus small id and money helpers shared by the generator."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import yaml

from seed.profiles import Profile

UTC = UTC
IST_OFFSET = timedelta(hours=5, minutes=30)

# Kinds used to build deterministic ids. One number space per kind keeps ids unique per tenant.
K_TENANT, K_USER, K_CATEGORY, K_PRODUCT, K_SUPPLIER, K_TERM, K_PRICE = 1, 2, 3, 4, 5, 6, 7
K_PROMO, K_BATCH, K_PO, K_POLINE, K_RECEIPT, K_RLINE, K_SALE = 8, 9, 10, 11, 12, 13, 14
K_RETURN, K_COUNT, K_CLINE, K_ADJ, K_STOCKOUT, K_BALANCE, K_DOC, K_CHUNK = (
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
)


def make_uuid(tenant_index: int, kind: int, n: int) -> uuid.UUID:
    return uuid.UUID(f"5eed{tenant_index:04x}-{kind:04x}-4000-8000-{n:012x}")


def tenant_uuid(profile: Profile) -> uuid.UUID:
    return make_uuid(profile.index, K_TENANT, 1)


def paise(value: str | Decimal | float | int) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value())


def money(p: int) -> str:
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}{p // 100}.{p % 100:02d}"


def cost4(p: int) -> str:
    """Unit costs are kept in ten thousandths of a rupee."""
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}{p // 10000}.{p % 10000:04d}"


def ist_midnight_utc(d: date) -> datetime:
    """The instant 00:00 IST of a business date, as a UTC datetime."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC) - IST_OFFSET


@dataclass
class SupplierSpec:
    index: int
    code: str
    name: str
    contact_name: str | None
    payment_terms_days: int
    default_lead_time_days: int | None
    delivery_weekdays: list[int]
    order_weekdays: list[int]
    min_order_value: int | None  # paise
    credit_limit: int | None  # paise
    accepts_expiry_returns: bool
    expiry_return_window_days: int | None
    return_window_days: int | None
    delay_prob: float
    delay_days_min: int
    delay_days_max: int
    fill_rate: float
    categories: list[str]
    planted: str | None


@dataclass
class ProductSpec:
    index: int
    sku: str
    barcode: str
    name: str
    brand: str | None
    category: str
    base_unit: str
    pack_label: str | None
    tax: str
    mrp: int  # paise
    selling_price: int  # paise
    is_batch_tracked: bool
    shelf_life_days: int | None
    supplier: int  # index into suppliers
    purchase_price: int  # in 1/10000 rupee
    pack_size: int
    moq_units: int
    term_lead_time_days: int | None
    min_stock_qty: int
    is_seasonal: bool
    chronic: bool
    item_tag: str
    generic_name: str | None
    strength: str | None
    dosage_form: str | None
    manufacturer: str | None
    schedule_class: str | None
    base_rate: float
    q: float
    nb_size: float
    elasticity: float
    trend_pct_year: float
    event_jitter: float
    # Filled in by the scenario planner and the simulation.
    launched_on: date | None = None
    has_term: bool = True
    unbatched: bool = False
    category_index: int = 0


@dataclass
class Catalog:
    profile: Profile
    suppliers: list[SupplierSpec]
    categories: list[dict[str, Any]]
    products: list[ProductSpec]
    gst_codes: tuple[str, ...] = field(default=("GST0", "GST5", "GST18", "GST40"))

    def category_slugs(self) -> list[str]:
        return [c["slug"] for c in self.categories]


def load_catalog(profile: Profile) -> Catalog:
    with profile.catalog_path.open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)
    code_to_idx: dict[str, int] = {}
    suppliers: list[SupplierSpec] = []
    for i, s in enumerate(raw["suppliers"]):
        code_to_idx[s["code"]] = i
        suppliers.append(
            SupplierSpec(
                index=i,
                code=s["code"],
                name=s["name"],
                contact_name=s.get("contact_name"),
                payment_terms_days=s["payment_terms_days"],
                default_lead_time_days=s["default_lead_time_days"],
                delivery_weekdays=list(s["delivery_weekdays"]),
                order_weekdays=list(s["order_weekdays"]),
                min_order_value=paise(s["min_order_value"]) if s["min_order_value"] else None,
                credit_limit=paise(s["credit_limit"]) if s["credit_limit"] else None,
                accepts_expiry_returns=s["accepts_expiry_returns"],
                expiry_return_window_days=s["expiry_return_window_days"],
                return_window_days=s["return_window_days"],
                delay_prob=s["delay_prob"],
                delay_days_min=s["delay_days_min"],
                delay_days_max=s["delay_days_max"],
                fill_rate=s["fill_rate"],
                categories=list(s["categories"]),
                planted=s.get("planted"),
            )
        )
    slugs = [c["slug"] for c in raw["categories"]]
    products: list[ProductSpec] = []
    for i, p in enumerate(raw["products"]):
        t = p["traits"]
        products.append(
            ProductSpec(
                index=i,
                sku=p["sku"],
                barcode=p["barcode"],
                name=p["name"],
                brand=p.get("brand"),
                category=p["category"],
                base_unit=p["base_unit"],
                pack_label=p.get("pack_label"),
                tax=p["tax"],
                mrp=paise(p["mrp"]),
                selling_price=paise(p["selling_price"]),
                is_batch_tracked=p["is_batch_tracked"],
                shelf_life_days=p["shelf_life_days"],
                supplier=code_to_idx[p["supplier"]],
                purchase_price=int((Decimal(p["purchase_price"]) * 10000).to_integral_value()),
                pack_size=p["pack_size"],
                moq_units=p["moq_units"],
                term_lead_time_days=p["term_lead_time_days"],
                min_stock_qty=p["min_stock_qty"],
                is_seasonal=p["is_seasonal"],
                chronic=p["chronic"],
                item_tag=p.get("item_tag", ""),
                generic_name=p.get("generic_name"),
                strength=p.get("strength"),
                dosage_form=p.get("dosage_form"),
                manufacturer=p.get("manufacturer"),
                schedule_class=p.get("schedule_class"),
                base_rate=t["base_rate"],
                q=t["q"],
                nb_size=t["nb_size"],
                elasticity=t["elasticity"],
                trend_pct_year=t["trend_pct_year"],
                event_jitter=t["event_jitter"],
                category_index=slugs.index(p["category"]),
            )
        )
    return Catalog(
        profile=profile, suppliers=suppliers, categories=raw["categories"], products=products
    )
