"""Schemas shared by every endpoint."""

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    field: str = Field(description="Dotted path of the field, for example lines[0].quantity")
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class HealthStatus(BaseModel):
    status: str
    version: str | None = None
    database: str | None = None
    migration: str | None = Field(
        default=None, description="current when the database is at the migration head"
    )
