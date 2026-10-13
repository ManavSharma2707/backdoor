"""Request and response bodies for the auth endpoints."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import PASSWORD_MAX_LENGTH


def _normalise_email(value: str) -> str:
    return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    @classmethod
    def _lower(cls, value: str) -> str:
        return _normalise_email(value)


class RegisterRequest(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    business_type: Literal["fmcg", "medical"]
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    @classmethod
    def _lower(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("business_name", "full_name", mode="after")
    @classmethod
    def _strip(cls, value: str) -> str:
        return " ".join(value.split())


class DemoLoginRequest(BaseModel):
    profile_key: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_-]+$")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    business_type: str
    is_synthetic: bool


class SettingsSummary(BaseModel):
    weekly_budget: str | None
    service_level: str
    default_lead_time_days: int
    agents_enabled: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int = Field(description="Seconds until the access token expires")
    user: UserOut
    tenant: TenantOut


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut
    settings: SettingsSummary


class MessageResponse(BaseModel):
    message: str
