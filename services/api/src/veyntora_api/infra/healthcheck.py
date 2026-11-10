"""Container health, without loading the whole application.

    python -m veyntora_api.infra.healthcheck --bootstrapped
    python -m veyntora_api.infra.healthcheck --url http://127.0.0.1:2026/health

`veyntora-api healthcheck` does the same, but loads every module first (about two seconds),
which a container health check with a short timeout cannot afford on a busy machine.
"""

from __future__ import annotations

import argparse
import sys

from veyntora_api.infra import launcher


def main() -> None:
    parser = argparse.ArgumentParser(prog="healthcheck")
    parser.add_argument("--bootstrapped", action="store_true", help="healthy once bootstrapped")
    parser.add_argument("--url", help="healthy when this answers 200, or while still waiting")
    args = parser.parse_args()
    sys.exit(0 if launcher.healthy(bootstrapped=args.bootstrapped, url=args.url) else 1)


if __name__ == "__main__":
    main()
