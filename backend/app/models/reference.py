"""Global reference tables: no tenant."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, enum_check


class TaxRate(IdMixin, Base):
    __tablename__ = "tax_rates"
    __table_args__ = (UniqueConstraint("code"),)

    code: Mapped[str] = mapped_column(Text)
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    label: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class CalendarEvent(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("slug"),
        UniqueConstraint("event_key", "start_date"),
        CheckConstraint("end_date >= start_date", name="end_after_start"),
        enum_check("kind", ("festival", "season", "holiday")),
    )

    slug: Mapped[str] = mapped_column(Text)
    event_key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    pre_window_days: Mapped[int] = mapped_column(SmallInteger, server_default="7")
    post_window_days: Mapped[int] = mapped_column(SmallInteger, server_default="3")
    delivery_delay_days: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    affects_hours: Mapped[bool] = mapped_column(server_default=false())
    region_scope: Mapped[str] = mapped_column(Text, server_default="maharashtra")
    is_verified: Mapped[bool] = mapped_column(server_default=false())
    is_active: Mapped[bool] = mapped_column(server_default=true())
    source_note: Mapped[str | None] = mapped_column(Text)


class ModelVersion(IdMixin, CreatedAtMixin, Base):
    """One row per engine release, for example `forecast-engine` or `replenishment-engine`."""

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    git_sha: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
