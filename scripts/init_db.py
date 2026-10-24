"""Create any missing tables. Safe to run on every deploy.

Set SEED_ON_START=true to also load the demo Shivajinagar shops. It is off by
default on purpose: the seed rewrites names and prices for the shops it owns, so
leaving it on would undo a butcher's own price edits at every deploy.
"""

import os

from app.db import DATABASE_URL, init_db

_TRUTHY = {"1", "true", "yes", "on"}


def main() -> None:
    init_db()
    print("tables ready on {}".format(DATABASE_URL.split("@")[-1]))

    if os.getenv("SEED_ON_START", "").strip().lower() in _TRUTHY:
        from scripts.seed import main as seed

        print("SEED_ON_START set - loading the demo catalogue")
        seed()


if __name__ == "__main__":
    main()
