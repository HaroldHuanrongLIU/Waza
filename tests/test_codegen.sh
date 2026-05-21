#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/test_helpers.sh"

tmpdir=$(make_tmpdir)

# Clean working copy: --check must succeed.
copy_repo "$tmpdir/repo"
(cd "$tmpdir/repo" && python3 scripts/build_metadata.py --check >"$tmpdir/clean.out" 2>"$tmpdir/clean.err")
grep -q 'matches generator' "$tmpdir/clean.out"
(cd "$tmpdir/repo" && python3 -S scripts/build_metadata.py --check >"$tmpdir/no-site.out" 2>"$tmpdir/no-site.err")
grep -q 'installer defaults pinned' "$tmpdir/no-site.out"

# Tampered marketplace.json: --check must detect drift.
copy_repo "$tmpdir/drift"
python3 -c "
import json
p = '$tmpdir/drift/.claude-plugin/marketplace.json'
d = json.load(open(p))
d['plugins'][0]['description'] = 'tampered'
open(p, 'w').write(json.dumps(d, indent=2) + '\n')
"
if (cd "$tmpdir/drift" && python3 scripts/build_metadata.py --check >"$tmpdir/drift.out" 2>"$tmpdir/drift.err"); then
  echo "build_metadata --check should detect tampered marketplace.json"; exit 1
fi
grep -q 'DRIFT:' "$tmpdir/drift.err"

# Default --write mode regenerates from frontmatter + VERSION.
copy_repo "$tmpdir/regen"
printf '%s\n' '{"plugins": []}' > "$tmpdir/regen/.claude-plugin/marketplace.json"
(cd "$tmpdir/regen" && python3 scripts/build_metadata.py >"$tmpdir/regen.out")
test "$(jq '.plugins | length' "$tmpdir/regen/.claude-plugin/marketplace.json")" -eq 9

# README install URLs must be pinned to VERSION, not floating on main.
copy_repo "$tmpdir/readme"
version=$(cat "$tmpdir/readme/VERSION")
sed -i.bak "s|tw93/Waza/v${version}/scripts/|tw93/Waza/main/scripts/|g" "$tmpdir/readme/README.md"
rm "$tmpdir/readme/README.md.bak"
if (cd "$tmpdir/readme" && python3 scripts/build_metadata.py --check >"$tmpdir/readme.out" 2>"$tmpdir/readme.err"); then
  echo "build_metadata --check should detect unpinned README URLs"; exit 1
fi
grep -q "README.md install URLs are not pinned" "$tmpdir/readme.err"
(cd "$tmpdir/readme" && python3 scripts/build_metadata.py >"$tmpdir/readme-regen.out")
grep -q "tw93/Waza/v${version}/scripts/" "$tmpdir/readme/README.md"
if grep -q "tw93/Waza/main/scripts/" "$tmpdir/readme/README.md"; then
  echo "README still has unpinned install URLs after regen"; exit 1
fi

# Installer scripts must also default to the current release tag; overriding
# WAZA_REF=main remains available for bleeding-edge installs.
copy_repo "$tmpdir/scripts"
version=$(cat "$tmpdir/scripts/VERSION")
sed -i.bak 's|WAZA_REF="${WAZA_REF:-v'"$version"'}"|WAZA_REF="${WAZA_REF:-main}"|g' \
  "$tmpdir/scripts/scripts/setup-rule.sh" \
  "$tmpdir/scripts/scripts/setup-statusline.sh"
rm "$tmpdir/scripts/scripts/setup-rule.sh.bak" "$tmpdir/scripts/scripts/setup-statusline.sh.bak"
if (cd "$tmpdir/scripts" && python3 scripts/build_metadata.py --check >"$tmpdir/scripts.out" 2>"$tmpdir/scripts.err"); then
  echo "build_metadata --check should detect unpinned installer WAZA_REF"; exit 1
fi
grep -q 'default WAZA_REF is not pinned' "$tmpdir/scripts.err"
(cd "$tmpdir/scripts" && python3 scripts/build_metadata.py >"$tmpdir/scripts-regen.out")
grep -q 'WAZA_REF="${WAZA_REF:-v'"$version"'}"' "$tmpdir/scripts/scripts/setup-rule.sh"
grep -q 'WAZA_REF="${WAZA_REF:-v'"$version"'}"' "$tmpdir/scripts/scripts/setup-statusline.sh"

# Dispatcher routing table is also generated; tampering the committed copy
# (or deleting it) must trip drift detection.
copy_repo "$tmpdir/dispatcher"
sed -i.bak 's| think | tampered |g' "$tmpdir/dispatcher/scripts/dispatcher.md"
rm "$tmpdir/dispatcher/scripts/dispatcher.md.bak"
if (cd "$tmpdir/dispatcher" && python3 scripts/build_metadata.py --check >"$tmpdir/dispatcher.out" 2>"$tmpdir/dispatcher.err"); then
  echo "build_metadata --check should detect tampered dispatcher.md"; exit 1
fi
grep -q 'routing table is out of sync' "$tmpdir/dispatcher.err"
(cd "$tmpdir/dispatcher" && python3 scripts/build_metadata.py >"$tmpdir/dispatcher-regen.out")
grep -q '| think | `skills/think/SKILL.md` |' "$tmpdir/dispatcher/scripts/dispatcher.md"

echo "codegen smoke: ok"
