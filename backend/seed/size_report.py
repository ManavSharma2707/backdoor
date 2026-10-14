"""Database size report: `python -m seed.size_report`. The seed must stay under 400 MB."""

import sys
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_engine

LIMIT_MB = 400.0


def collect(session: Session) -> list[tuple[str, int, float, float]]:
    """(table, estimated rows, table MB, index MB), largest first."""
    rows = session.execute(
        text(
            """
            SELECT c.relname,
                   GREATEST(c.reltuples, 0)::bigint,
                   pg_table_size(c.oid) / 1048576.0,
                   pg_indexes_size(c.oid) / 1048576.0
            FROM pg_class c
            WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC
            """
        )
    ).all()
    return [(r[0], int(r[1]), float(r[2]), float(r[3])) for r in rows]


def report(session: Session) -> tuple[str, float]:
    table = collect(session)
    total = sum(t + i for _, _, t, i in table)
    lines = [f"{'table':32} {'rows':>10} {'table MB':>9} {'index MB':>9} {'total MB':>9}"]
    for name, n, t, i in table[:22]:
        lines.append(f"{name:32} {n:>10,} {t:>9.1f} {i:>9.1f} {t + i:>9.1f}")
    rest = table[22:]
    if rest:
        extra = sum(t + i for _, _, t, i in rest)
        lines.append(
            f"{'(' + str(len(rest)) + ' smaller tables)':32} {'':>10} {'':>9} {'':>9} {extra:>9.1f}"
        )
    lines.append(f"{'TOTAL':32} {'':>10} {'':>9} {'':>9} {total:>9.1f}")
    database = session.execute(
        text("SELECT pg_database_size(current_database()) / 1048576.0")
    ).scalar_one()
    lines.append(f"database on disk: {float(database):.1f} MB, limit {LIMIT_MB:.0f} MB")
    return "\n".join(lines), total


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    with Session(get_engine()) as session:
        body, total = report(session)
    sys.stdout.write(body + "\n")
    if total >= LIMIT_MB:
        sys.stdout.write(f"Over the limit: {total:.1f} MB is not under {LIMIT_MB:.0f} MB.\n")
        return 1
    sys.stdout.write(f"Under the limit: {total:.1f} MB.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
