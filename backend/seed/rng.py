"""Seeded random streams. One stream per tenant, purpose and (optionally) day.

Every stream is a pure function of `(base_seed, tenant index, purpose, extra)`, so changing the
code that draws from one purpose never shifts the numbers of another. Only numpy generators.
"""

import numpy as np

PURPOSES: dict[str, int] = {
    "catalog": 1,
    "supplier": 2,
    "demand": 3,
    "calibrate": 4,
    "bills": 5,
    "returns": 6,
    "adjust": 7,
    "order": 8,
    "delivery": 9,
    "counts": 10,
    "stockout": 11,
    "promo": 12,
    "price": 13,
    "scenario": 14,
    "batch": 15,
    "corpus": 16,
    "misc": 17,
}


def stream(base_seed: int, tenant_index: int, purpose: str, extra: int = 0) -> np.random.Generator:
    seq = np.random.SeedSequence([base_seed, tenant_index, PURPOSES[purpose], extra])
    return np.random.Generator(np.random.PCG64(seq))
