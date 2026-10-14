"""Determinism check: `python -m seed.checksum --tenants all [--scale 1.0] [--twice]`.

Generates each tenant in memory and prints a SHA-256 over the key tables. With `--twice` the
generation runs two times and the command fails if the digests differ.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from app.core.config import get_settings
from seed.generate import checksum, generate_tenant
from seed.profiles import DEFAULT_END_DATE, resolve_tenants


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seed.checksum")
    parser.add_argument("--tenants", default="all")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END_DATE)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--twice", action="store_true")
    args = parser.parse_args(argv)
    base_seed = args.seed if args.seed is not None else get_settings().seed_base
    failed = False
    for profile in resolve_tenants(args.tenants):
        first = checksum(generate_tenant(profile, base_seed, args.end_date, args.scale))
        line = f"{profile.key} {first}"
        if args.twice:
            second = checksum(generate_tenant(profile, base_seed, args.end_date, args.scale))
            same = first == second
            failed = failed or not same
            line += " identical" if same else f" DIFFERENT {second}"
        sys.stdout.write(line + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
