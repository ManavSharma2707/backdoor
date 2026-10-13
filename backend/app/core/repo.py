"""Tenant scoped repository base class.

Every query a `TenantRepo` builds carries `tenant_id = :tid`, and every insert sets it. The
tenant id comes from the authenticated context, never from request input. A repository cannot
be built without one.
"""

import uuid
from collections.abc import Sequence
from typing import Any, ClassVar

from sqlalchemy import Delete, Select, Update, delete, func, select, update
from sqlalchemy.orm import Session

from app.models.base import Base


class TenantContextError(RuntimeError):
    """Raised when a repository is used without a valid tenant id."""


class TenantRepo[ModelT: Base]:
    """Base class for repositories over a tenant owned model.

    Subclasses set `model`. Use `select_()`, `update_()` and `delete_()` to build statements
    and `get`, `list`, `add` for the common operations.
    """

    model: ClassVar[type[Base]]

    def __init__(self, session: Session, tenant_id: uuid.UUID | None) -> None:
        if not isinstance(tenant_id, uuid.UUID):
            raise TenantContextError("A tenant id is required to use a repository")
        model = self.model
        if "tenant_id" not in model.__table__.columns or "id" not in model.__table__.columns:
            raise TypeError(f"{model.__name__} is not a tenant owned model with an id column")
        self.session = session
        self.tenant_id = tenant_id

    @property
    def _tenant_column(self) -> Any:
        return getattr(self.model, "tenant_id")  # noqa: B009

    @property
    def _id_column(self) -> Any:
        return getattr(self.model, "id")  # noqa: B009

    def select_(self) -> Select[Any]:
        return select(self.model).where(self._tenant_column == self.tenant_id)

    def update_(self) -> Update:
        return update(self.model).where(self._tenant_column == self.tenant_id)

    def delete_(self) -> Delete:
        return delete(self.model).where(self._tenant_column == self.tenant_id)

    def get(self, entity_id: Any) -> ModelT | None:
        stmt = self.select_().where(self._id_column == entity_id)
        row: ModelT | None = self.session.execute(stmt).scalars().first()
        return row

    def list_(self, *, limit: int = 200, offset: int = 0) -> Sequence[ModelT]:
        stmt = self.select_().order_by(self._id_column).limit(limit).offset(offset)
        return self.session.execute(stmt).scalars().all()

    def count(self) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self._tenant_column == self.tenant_id)
        )
        return int(self.session.execute(stmt).scalar_one())

    def add(self, entity: ModelT) -> ModelT:
        """Attach `entity` to this tenant. A row that names another tenant is refused."""
        current = getattr(entity, "tenant_id", None)
        if current is not None and current != self.tenant_id:
            raise TenantContextError("Entity belongs to a different tenant")
        entity.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        self.session.add(entity)
        return entity
