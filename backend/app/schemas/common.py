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
    database: str | None = None
