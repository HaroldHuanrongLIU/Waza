#!/usr/bin/env python3
"""Verify dispatcher routing table and RESOLVER.md cover every skill.

Both files must reference the same set of skill names found under
`skills/*/SKILL.md`. Treated as a sanity tripwire alongside the codegen in
`build_metadata.py`; cheap enough to keep even after routing tables become
generated.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKILL_REF_RE = re.compile(r"skills/([a-z][a-z0-9_-]*)/SKILL\.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (default: parent of scripts/)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    expected = {
        p.parent.name for p in (root / "skills").glob("*/SKILL.md")
    }
    if not expected:
        print("ERROR: no skills found under skills/*/SKILL.md", file=sys.stderr)
        return 1

    dispatcher = set(
        SKILL_REF_RE.findall((root / "scripts" / "dispatcher.md").read_text())
    )
    resolver = set(
        SKILL_REF_RE.findall((root / "skills" / "RESOLVER.md").read_text())
    )

    drift = False

    missing_dispatcher = expected - dispatcher
    if missing_dispatcher:
        print(
            "ROUTING DRIFT: skills missing from scripts/dispatcher.md: "
            f"{sorted(missing_dispatcher)}",
            file=sys.stderr,
        )
        drift = True

    missing_resolver = expected - resolver
    if missing_resolver:
        print(
            f"ROUTING DRIFT: skills missing from RESOLVER.md: {sorted(missing_resolver)}",
            file=sys.stderr,
        )
        drift = True

    stale_dispatcher = dispatcher - expected
    if stale_dispatcher:
        print(
            f"ROUTING DRIFT: stale skill refs in scripts/dispatcher.md: {sorted(stale_dispatcher)}",
            file=sys.stderr,
        )
        drift = True

    if drift:
        return 1

    print(
        f"ok: routing consistent across {len(expected)} skills (scripts/dispatcher.md + RESOLVER.md)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
