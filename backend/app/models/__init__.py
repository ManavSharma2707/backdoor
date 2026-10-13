"""Importing this package registers every table on `Base.metadata`."""

from app.models import (
    agents,
    catalogue,
    intelligence,
    inventory,
    ops,
    purchasing,
    reference,
    sales,
    suppliers,
    tenancy,
)
from app.models.base import Base

__all__ = [
    "Base",
    "agents",
    "catalogue",
    "intelligence",
    "inventory",
    "ops",
    "purchasing",
    "reference",
    "sales",
    "suppliers",
    "tenancy",
]
