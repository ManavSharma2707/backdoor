"""Structural checks on the metadata. No database needed."""

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint, Table
from sqlalchemy import UniqueConstraint as UniqueConstraintType

from app.models import Base

TABLES = Base.metadata.tables

# Not owned by a tenant at all.
GLOBAL_TABLES = {"tax_rates", "calendar_events", "model_versions", "tenants"}
# Carry a tenant_id that may be NULL (global rows) or have none by design.
TENANT_OPTIONAL = {"job_runs", "audit_logs", "knowledge_documents", "knowledge_chunks"}
# Tenant owned parents that plain (non composite) foreign keys may point at.
PLAIN_FK_TARGETS = {"tenants", "users", "model_versions", "tax_rates", "knowledge_documents"}

HIGH_VOLUME_BIGINT_IDS = {
    "sale_lines",
    "sale_return_lines",
    "inventory_movements",
    "forecast_values",
    "audit_logs",
    "agent_steps",
}


def tenant_owned() -> list[Table]:
    return [t for name, t in TABLES.items() if name not in GLOBAL_TABLES | TENANT_OPTIONAL]


def test_every_table_in_database_md_exists() -> None:
    assert len(TABLES) == 51
    for name in (
        "tenants",
        "users",
        "products",
        "sale_lines",
        "inventory_movements",
        "stock_balances",
        "recommendation_lines",
        "weekly_reports",
        "audit_logs",
        "knowledge_chunks",
        "daily_product_stats",
    ):
        assert name in TABLES


def test_tenant_owned_tables_carry_a_not_null_tenant_id() -> None:
    for table in tenant_owned():
        column = table.columns.get("tenant_id")
        assert column is not None, table.name
        assert not column.nullable, table.name


def test_tenant_optional_tables_have_a_nullable_tenant_id() -> None:
    for name in TENANT_OPTIONAL:
        column = TABLES[name].columns.get("tenant_id")
        assert column is not None, name
        assert column.nullable, name


def _tenant_unique_parents() -> set[str]:
    parents = set()
    for name, table in TABLES.items():
        for constraint in table.constraints:
            columns = [c.name for c in getattr(constraint, "columns", [])]
            if isinstance(constraint, UniqueConstraintType | PrimaryKeyConstraint) and columns[
                :2
            ] == ["tenant_id", "id"]:
                parents.add(name)
        if {c.name for c in table.primary_key.columns} == {"id", "tenant_id"}:
            parents.add(name)
    return parents


def test_intra_tenant_foreign_keys_are_composite() -> None:
    offenders = []
    for table in tenant_owned():
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            parent = constraint.referred_table.name
            if parent in PLAIN_FK_TARGETS:
                continue
            columns = [c.name for c in constraint.columns]
            if columns[0] != "tenant_id" or len(columns) != 2:
                offenders.append(f"{table.name}.{columns} -> {parent}")
    assert offenders == []


def test_composite_foreign_keys_target_tenant_unique_parents() -> None:
    parents = _tenant_unique_parents()
    offenders = []
    for table in TABLES.values():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint) and len(constraint.columns) == 2:
                target = constraint.referred_table.name
                refs = [element.column.name for element in constraint.elements]
                if refs != ["tenant_id", "id"] or target not in parents:
                    offenders.append(f"{table.name} -> {target} {refs}")
    assert offenders == []


def test_plain_foreign_keys_only_point_at_allowed_tables() -> None:
    for table in TABLES.values():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint) and len(constraint.columns) == 1:
                assert constraint.referred_table.name in PLAIN_FK_TARGETS, (
                    f"{table.name}.{next(iter(constraint.columns)).name}"
                )


def test_all_constraints_and_indexes_are_named() -> None:
    for table in TABLES.values():
        for constraint in table.constraints:
            assert constraint.name is not None, f"unnamed constraint on {table.name}"
        for index in table.indexes:
            assert index.name is not None, f"unnamed index on {table.name}"


def test_check_constraint_names_follow_the_convention() -> None:
    for table in TABLES.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                assert str(constraint.name).startswith(f"ck_{table.name}_"), constraint.name


def test_primary_key_types() -> None:
    for name, table in TABLES.items():
        pk_columns = list(table.primary_key.columns)
        if name in HIGH_VOLUME_BIGINT_IDS:
            assert len(pk_columns) == 1
            assert pk_columns[0].type.python_type is int, name
            assert pk_columns[0].identity is not None, name
        elif name in {"daily_product_stats", "synthetic_true_demand"}:
            assert next(c.name for c in pk_columns) == "tenant_id"
        elif name == "business_settings":
            assert [c.name for c in pk_columns] == ["tenant_id"]
        else:
            assert [c.name for c in pk_columns] == ["id"], name


def test_no_native_enums_and_no_floats_for_money() -> None:
    for table in TABLES.values():
        for column in table.columns:
            type_name = type(column.type).__name__
            assert type_name not in {"Enum", "ENUM"}, f"{table.name}.{column.name}"
            assert type_name not in {"Float", "FLOAT", "REAL", "DOUBLE_PRECISION"}, (
                f"{table.name}.{column.name}"
            )


@pytest.mark.parametrize(
    "name",
    [
        "tax_rates",
        "calendar_events",
        "model_versions",
        "tenants",
        "users",
        "refresh_tokens",
        "business_settings",
    ],
)
def test_spec_tables_have_the_expected_core_columns(name: str) -> None:
    assert "id" in TABLES[name].columns or name == "business_settings"
