#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-"$ROOT/dist/waza.zip"}"
case "$OUT" in
  /*) ;;
  *) OUT="$ROOT/$OUT" ;;
esac

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"

cd "$ROOT"

MANIFEST="$(mktemp)"
FILTERED_MANIFEST="$(mktemp)"
STAGE="$(mktemp -d)"
trap 'rm -f "$MANIFEST" "$FILTERED_MANIFEST"; rm -rf "$STAGE"' EXIT

git ls-files --cached --others --exclude-standard > "$MANIFEST"

# Default-deny: only paths matching packaging.allowlist ship. Structural
# excludes (per-skill SKILL.md, __pycache__, etc.) live inside the filter.
python3 "$ROOT/scripts/packaging_filter.py" "$ROOT/packaging.allowlist" \
  < "$MANIFEST" > "$FILTERED_MANIFEST"

tar -cf - -T "$FILTERED_MANIFEST" | (cd "$STAGE" && tar -xf -)

# Dispatcher body is codegen output: scripts/dispatcher.md. Source of truth is
# scripts/dispatcher-template.md plus SKILL.md frontmatter; regenerate with
# `make regenerate` if the template or any dispatch_intent changes.
if [ ! -f "$ROOT/scripts/dispatcher.md" ]; then
  echo "ERROR: scripts/dispatcher.md missing; run 'make regenerate' first" >&2
  exit 1
fi
cp "$ROOT/scripts/dispatcher.md" "$STAGE/SKILL.md"

find skills -mindepth 2 -maxdepth 2 -name SKILL.md | sort | while IFS= read -r path; do
  skill="$(basename "$(dirname "$path")")"
  {
    printf '\n---\n\n# SKILL: %s\n\n' "$skill"
    awk 'BEGIN{skip=0} /^---$/{if(NR==1){skip=1;next} if(skip){skip=0;next}} !skip' "$path"
  } >> "$STAGE/SKILL.md"
done

perl -0pi -e 's#`skills/([a-z][a-z0-9_-]*)/SKILL\.md`#the **$1** section below#g' "$STAGE/SKILL.md"
find "$STAGE/skills" -type d -empty -delete 2>/dev/null || true

(cd "$STAGE" && find . -type f | sed 's#^\./##' | sort | zip -q "$OUT" -@)

if ! zipinfo -1 "$OUT" | awk '$0 == "SKILL.md" { found = 1 } END { exit found ? 0 : 1 }'; then
  echo "ERROR: root SKILL.md missing from $OUT" >&2
  exit 1
fi

SKILL_COUNT="$(zipinfo -1 "$OUT" | awk '$0 ~ /(^|\/)SKILL\.md$/ { count++ } END { print count + 0 }')"
if [ "$SKILL_COUNT" -ne 1 ]; then
  echo "ERROR: expected exactly one SKILL.md in $OUT, found $SKILL_COUNT" >&2
  exit 1
fi

SIZE=$(wc -c < "$OUT" | tr -d ' ')
echo "OK: wrote $OUT (${SIZE} bytes)"

# Post-package validation: unzip to a temp dir and verify frontmatter integrity.
VALIDATE_DIR="$(mktemp -d)"
trap 'rm -rf "$VALIDATE_DIR"' EXIT
unzip -q "$OUT" -d "$VALIDATE_DIR"

python3 - "$VALIDATE_DIR" <<'VALIDATE_PYEOF'
import sys
from pathlib import Path

stage = Path(sys.argv[1])
root_skill = stage / "SKILL.md"
if not root_skill.exists():
    print("POST-PACKAGE ERROR: SKILL.md missing from extracted ZIP", file=sys.stderr)
    raise SystemExit(1)

text = root_skill.read_text()

# Verify ninja marker is present.
if "Prefix your first line with 🥷 inline" not in text:
    print("POST-PACKAGE ERROR: root SKILL.md missing ninja prefix instruction", file=sys.stderr)
    raise SystemExit(1)

# Verify all 8 skill sections are inlined.
expected = ["think", "design", "check", "hunt", "write", "learn", "read", "health"]
for skill in expected:
    if f"# SKILL: {skill}" not in text:
        print(f"POST-PACKAGE ERROR: SKILL section '{skill}' not inlined in root SKILL.md", file=sys.stderr)
        raise SystemExit(1)

# Verify no broken references to nested SKILL.md paths remain.
if "skills/check/SKILL.md" in text or "skills/think/SKILL.md" in text:
    print("POST-PACKAGE ERROR: root SKILL.md still contains nested SKILL.md path references", file=sys.stderr)
    raise SystemExit(1)

print("ok: post-package validation passed")
VALIDATE_PYEOF
