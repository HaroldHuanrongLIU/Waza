#!/usr/bin/env bash
# Verify dispatcher routing table and RESOLVER.md cover every skill.
# Thin shell wrapper; logic lives in scripts/check_routing_drift.py.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check_routing_drift.py" --root "$ROOT" "$@"
