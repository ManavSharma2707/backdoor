"""Pagination and sorting helpers shared by list endpoints (`api-spec.md` section 1)."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.core.messages import ErrorCode
from app.schemas.common import ErrorDetail

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PageDep = Annotated[PageParams, Depends(page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(ge=0)
    page: int
    page_size: int


def paginate(session: Session, stmt: Select[Any], params: PageParams) -> tuple[list[Any], int]:
    """Run `stmt` for one page and count the rows without the paging. Rows are `Row` objects."""
    total = int(
        session.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).scalar_one()
    )
    rows = session.execute(stmt.limit(params.page_size).offset(params.offset)).all()
    return list(rows), total


def parse_sort(
    sort: str | None, allowed: dict[str, ColumnElement[Any]], default: str
) -> list[ColumnElement[Any]]:
    """Turn `name:asc,created_at:desc` into order by clauses, from an allowlist only.

    Unknown fields or directions are a 422. Names never reach SQL as text.
    """
    clauses: list[ColumnElement[Any]] = []
    for part in (sort or default).split(","):
        name, _, direction = part.strip().partition(":")
        direction = direction or "asc"
        if name not in allowed or direction not in {"asc", "desc"}:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[ErrorDetail(field="sort", issue=f"cannot sort by {part.strip()!r}")],
            )
        column = allowed[name]
        clauses.append(
            column.desc().nulls_last() if direction == "desc" else column.asc().nulls_last()
        )
    return clauses
