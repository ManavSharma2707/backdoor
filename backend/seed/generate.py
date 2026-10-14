"""Generate one tenant in memory (no database) and fingerprint the result."""

import hashlib
import time
from dataclasses import dataclass
from datetime import date

from seed.demand import Demand, build_demand
from seed.model import Catalog, load_catalog
from seed.pricing import Timelines, build_timelines
from seed.profiles import Profile
from seed.scenarios import ScenarioPlan, plan_scenarios
from seed.sim import Simulation, TenantData

CHECKSUM_TABLES = (
    "product_batches",
    "purchase_orders",
    "purchase_order_lines",
    "goods_receipts",
    "receipt_lines",
    "sales",
    "sale_lines",
    "sale_returns",
    "sale_return_lines",
    "inventory_movements",
    "stock_counts",
    "stock_count_lines",
    "stock_adjustments",
    "stockout_intervals",
)


@dataclass
class Generated:
    profile: Profile
    catalog: Catalog
    plan: ScenarioPlan
    timelines: Timelines
    demand: Demand
    data: TenantData
    seconds: float


def generate_tenant(profile: Profile, base_seed: int, end_date: date, scale: float) -> Generated:
    started = time.time()
    catalog = load_catalog(profile)
    plan = plan_scenarios(catalog, end_date, base_seed)
    timelines = build_timelines(catalog, plan, base_seed, end_date)
    demand = build_demand(catalog, plan, timelines, base_seed, scale, end_date)
    data = Simulation(catalog, plan, timelines, demand, base_seed, end_date, scale).run()
    return Generated(profile, catalog, plan, timelines, demand, data, time.time() - started)


def checksum(gen: Generated) -> str:
    """SHA-256 over the key tables and the true demand. Same inputs give the same digest."""
    digest = hashlib.sha256()
    for table in CHECKSUM_TABLES:
        digest.update(table.encode())
        for row in gen.data.rows[table]:
            digest.update(repr(row).encode())
    digest.update(gen.demand.true_demand.tobytes())
    digest.update(gen.timelines.sell.tobytes())
    digest.update(gen.timelines.cost.tobytes())
    return digest.hexdigest()
