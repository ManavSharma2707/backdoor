"""Mounts every v1 router. Feature routers are added here as they are built."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    calendar,
    catalogue,
    health,
    insights,
    inventory,
    jobs,
    purchasing,
    reports,
    sales,
    settings,
    suppliers,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(calendar.router)
api_router.include_router(catalogue.categories)
api_router.include_router(catalogue.products)
api_router.include_router(catalogue.tax_rates)
api_router.include_router(suppliers.suppliers)
api_router.include_router(suppliers.terms)
api_router.include_router(sales.router)
api_router.include_router(purchasing.orders)
api_router.include_router(purchasing.receipts)
api_router.include_router(inventory.inventory)
api_router.include_router(inventory.product_stock)
api_router.include_router(inventory.supplier_returns)
api_router.include_router(reports.reports)
api_router.include_router(reports.report_lines)
api_router.include_router(insights.dashboard)
api_router.include_router(insights.insights)
api_router.include_router(insights.quality)
api_router.include_router(jobs.router)
