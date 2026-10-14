"""Command line entry point: `python -m app.jobs.run <command>`.

Commands: `migrate`, `openapi`, `monday`, `backfill`, `simulate-week` and `reset-password`.
`monday` runs the weekly pipeline (`--profile full` is what the scheduled job uses), `backfill`
creates the retrospective plans of the demo tenants.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.jobs.migrate import run_migrations

log = get_logger(__name__)

SIMULATE_WEEK_MESSAGE = (
    "simulate-week is not built yet. It arrives with the demo tools of the last prompt (P8.03): "
    "it will extend the history of a synthetic tenant by one week."
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.run", description="Backroom jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="alembic upgrade head, then refresh reference data")
    commands.add_parser("openapi", help="write backend/openapi.json from the running app code")

    monday = commands.add_parser("monday", help="run the Monday pipeline")
    monday.add_argument("--tenant", default="all", help="business id, slug or all")
    monday.add_argument("--all-tenants", action="store_true", help="same as --tenant all")
    monday.add_argument("--profile", choices=("light", "full"), default="light")
    monday.add_argument("--force", action="store_true", help="write a new version of the report")
    monday.add_argument("--as-of", type=_date, default=None, help="a Monday, default this week")

    backfill = commands.add_parser("backfill", help="plans for past Mondays with demo decisions")
    backfill.add_argument("--tenant", default="all", help="business id, slug or all")
    backfill.add_argument("--weeks", type=int, default=8)
    backfill.add_argument("--as-of", type=_date, default=None, help="the plan week to stop before")

    commands.add_parser("simulate-week", help="extend a demo business by one week (not built yet)")

    reset = commands.add_parser("reset-password", help="set a new password for an owner")
    reset.add_argument("--email", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    if args.command == "migrate":
        run_migrations()
        return 0
    if args.command == "openapi":
        from app.jobs.openapi import write_openapi

        log.info("openapi.written", path=str(write_openapi()))
        return 0
    if args.command == "monday":
        from app.jobs.monday import run_monday

        tenant = "all" if args.all_tenants else args.tenant
        return run_monday(tenant, args.profile, args.force, args.as_of)
    if args.command == "backfill":
        from app.jobs.monday import run_backfill

        return run_backfill(args.tenant, args.weeks, args.as_of)
    if args.command == "simulate-week":
        sys.stdout.write(SIMULATE_WEEK_MESSAGE + "\n")
        return 0
    if args.command == "reset-password":
        from app.jobs.accounts import reset_password

        return reset_password(args.email)
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
