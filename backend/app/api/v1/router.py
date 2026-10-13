"""Mounts every v1 router. Feature routers are added here as they are built."""

from fastapi import APIRouter

from app.api.v1 import auth, catalogue, health, settings, suppliers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(catalogue.categories)
api_router.include_router(catalogue.products)
api_router.include_router(catalogue.tax_rates)
api_router.include_router(suppliers.suppliers)
api_router.include_router(suppliers.terms)
