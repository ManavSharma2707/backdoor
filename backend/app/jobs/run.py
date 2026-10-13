"""Command line entry point: `python -m app.jobs.run <command>`.

Only `migrate` exists so far. The Monday pipeline, backfill, simulate-week and reset-password
commands arrive in later prompts.
"""

import argparse
import sys
from collections.abc import Sequence

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.jobs.migrate import run_migrations

log = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.run", description="Backroom jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="alembic upgrade head, then refresh reference data")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)
    if args.command == "migrate":
        run_migrations()
        return 0
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
