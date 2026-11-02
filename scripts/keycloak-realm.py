#!/usr/bin/env python3
"""Write the Veyntora realm for your own Keycloak (docs/runbooks/external-services.md).

Takes the bundled realm (deploy/compose/keycloak/veyntora-realm.json), fills in its
placeholders from the environment and leaves out the two development users (admin,
employee). Import the result as a new realm, or with "Partial import" into an existing
one. The output contains the two client secrets: it is written with mode 600.

    VEY_PUBLIC_BASE_URL=https://veyntora.example.com \
    VEY_OIDC_CLIENT_SECRET=... VEY_KEYCLOAK_SYNC_CLIENT_SECRET=... \
    scripts/keycloak-realm.py --realm veyntora --out veyntora-realm.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "deploy/compose/keycloak/veyntora-realm.json"
NEEDED = ("VEY_PUBLIC_BASE_URL", "VEY_OIDC_CLIENT_SECRET", "VEY_KEYCLOAK_SYNC_CLIENT_SECRET")
_MIN_SECRET = 24


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--realm", default="veyntora", help="realm name (default: veyntora)")
    parser.add_argument("--out", type=Path, required=True, help="file to write")
    parser.add_argument(
        "--without-groups",
        action="store_true",
        help="leave out platform-admins and all-employees (your realm has its own groups)",
    )
    args = parser.parse_args()

    missing = [k for k in NEEDED if not os.environ.get(k)]
    if missing:
        sys.stderr.write(f"set {', '.join(missing)} first\n")
        return 2
    for k in NEEDED[1:]:
        if len(os.environ[k]) < _MIN_SECRET:
            sys.stderr.write(f"{k} is shorter than {_MIN_SECRET} characters\n")
            return 2

    # The development users' passwords are the only other placeholders; they are dropped.
    fill = {
        k: os.environ[k].rstrip("/") if k == "VEY_PUBLIC_BASE_URL" else os.environ[k]
        for k in NEEDED
    }
    text = re.sub(
        r"\$\{(VEY_[A-Z_]+)\}",
        lambda m: json.dumps(fill.get(m.group(1), ""))[1:-1],
        SOURCE.read_text(),
    )
    realm = json.loads(text)
    realm["realm"] = args.realm
    realm["users"] = [u for u in realm.get("users", []) if u.get("serviceAccountClientId")]
    if args.without_groups:
        realm.pop("groups", None)

    args.out.touch(mode=0o600, exist_ok=True)
    args.out.chmod(0o600)
    args.out.write_text(json.dumps(realm, indent=2) + "\n")
    sys.stdout.write(
        f"wrote {args.out}: realm {args.realm!r}, clients "
        f"{', '.join(c['clientId'] for c in realm['clients'])}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
