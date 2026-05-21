#!/usr/bin/env python3
"""Validate Waza skill metadata, references, marketplace, and resolver invariants.

Run as: python3 scripts/verify_skills.py [--root PATH]

Default --root is the repository root inferred from this file's location.
All paths emitted are relative to --root so output stays stable across machines.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import NoReturn


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(1)


# Frontmatter delimited by `---` ... `---` at start of file. Waza frontmatter is
# intentionally tiny: top-level scalar fields plus `metadata.version`. Keeping
# this parser in stdlib avoids adding a hidden CI/runtime dependency.
def parse_frontmatter(path: Path) -> dict:
    text = path.read_text()
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        fail(f"INVALID FRONTMATTER: {path} must start with ---")
    try:
        end = lines.index("---", 1)
    except ValueError:
        fail(f"INVALID FRONTMATTER: {path} missing closing ---")

    def parse_scalar(field: str, raw: str) -> str:
        value = raw.strip()
        if not value:
            fail(f"EMPTY FRONTMATTER VALUE: {path} field {field}")
        if value[0] in ("'", '"'):
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                fail(f"INVALID FRONTMATTER QUOTE: {path} field {field}: {exc}")
            if not isinstance(parsed, str):
                fail(f"INVALID FRONTMATTER VALUE: {path} field {field} must be a string")
            return parsed
        if ": " in value:
            fail(
                f"UNQUOTED FRONTMATTER COLON: {path} field {field}\n"
                f"  Quote values containing ': ' so the metadata contract stays unambiguous."
            )
        return value

    fields: dict[str, str] = {}
    in_metadata = False
    for raw_line in lines[1:end]:
        if not raw_line.strip():
            continue
        if raw_line.startswith("  "):
            if not in_metadata:
                fail(f"INVALID FRONTMATTER INDENT: {path}: {raw_line!r}")
            key, sep, raw_value = raw_line.strip().partition(":")
            if not sep:
                fail(f"INVALID FRONTMATTER LINE: {path}: {raw_line!r}")
            if key == "version":
                fields["version"] = parse_scalar("metadata.version", raw_value)
            continue

        in_metadata = False
        key, sep, raw_value = raw_line.partition(":")
        if not sep:
            fail(f"INVALID FRONTMATTER LINE: {path}: {raw_line!r}")
        if key == "metadata":
            if raw_value.strip():
                fail(f"INVALID FRONTMATTER METADATA: {path} metadata must be a mapping")
            in_metadata = True
        elif key in {"name", "description", "when_to_use", "dispatch_intent"}:
            fields[key] = parse_scalar(key, raw_value)

    name = fields.get("name")
    description = fields.get("description")
    when_to_use = fields.get("when_to_use", "")
    dispatch_intent = fields.get("dispatch_intent", "")
    version = fields.get("version")

    if not name or not name.strip():
        fail(f"MISSING name: in {path}")
    if not description or not description.strip():
        fail(f"MISSING description: in {path}")
    if not version or not version.strip():
        fail(f"MISSING version: in {path}")

    return {
        "name": name.strip(),
        "description": description.strip(),
        "when_to_use": when_to_use.strip(),
        "dispatch_intent": dispatch_intent.strip(),
        "version": version.strip(),
    }


def parse_when_to_use_keywords(when_to_use: str) -> set[str]:
    return {kw.strip().lower() for kw in when_to_use.split(",") if kw.strip()}


REF_PATTERN = re.compile(r'(?<![/.])\b(?:references|agents|scripts)/[\w/.-]+\b')
SCRIPT_VAR_PATTERN = re.compile(r'\}/scripts/([\w/.-]+)')
LINK_RE = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
URL_PREFIXES = ("http://", "https://", "mailto:", "ftp://", "tel:", "data:")
SEP_RE = re.compile(r'^[\s|:\-]+$')
PERSONAL_PATH_PATTERN = re.compile(r'/(?:Users|home)/[A-Za-z0-9._-]+/')
SKILL_REF_RE = re.compile(r'skills/([a-z][a-z0-9_-]*)/SKILL\.md')

DURABLE_CONTEXT_SKILLS = {"think", "check", "hunt", "design", "write", "health"}

NINJA_PREFIX = "Prefix your first line with 🥷 inline, not as its own paragraph."


def pipe_count(s: str) -> int:
    n, tick, i = 0, False, 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            i += 2
            continue
        if s[i] == "`":
            tick = not tick
        elif s[i] == "|" and not tick:
            n += 1
        i += 1
    return n


def check_skill_files(root: Path, expected_version: str):
    skill_files = sorted((root / "skills").glob("*/SKILL.md"))
    if not skill_files:
        fail("NO SKILLS FOUND: expected skills/*/SKILL.md")
    skill_versions: dict[str, str] = {}
    skill_descriptions: dict[str, str] = {}
    skill_keywords: dict[str, set[str]] = {}
    for path in skill_files:
        skill_dir = path.parent.name
        fields = parse_frontmatter(path)
        if fields["name"] != skill_dir:
            fail(f"NAME MISMATCH: {path} frontmatter name={fields['name']} dir={skill_dir}")
        if NINJA_PREFIX not in path.read_text():
            fail(
                f"MISSING NINJA PREFIX INSTRUCTION: {path}\n"
                f"  Every SKILL.md must carry this exact line:\n"
                f"  {NINJA_PREFIX}"
            )
        if fields["version"] != expected_version:
            fail(
                f"VERSION DRIFT: {path} version={fields['version']!r} "
                f"!= VERSION file {expected_version!r}.\n"
                f"  All skills march in lock-step. Update SKILL.md to match VERSION."
            )
        if not fields["dispatch_intent"]:
            fail(
                f"MISSING dispatch_intent: in {path}\n"
                f"  Every skill needs a dispatch_intent line. It feeds the dispatcher "
                f"routing table emitted by scripts/build_metadata.py."
            )
        skill_versions[skill_dir] = fields["version"]
        skill_descriptions[skill_dir] = fields["description"]
        skill_keywords[skill_dir] = parse_when_to_use_keywords(fields["when_to_use"])
        print(f"ok: {path.as_posix()}")
    return skill_files, skill_versions, skill_descriptions, skill_keywords


def check_marketplace(root: Path, expected_version: str, skill_versions: dict[str, str], skill_descriptions: dict[str, str]):
    """Validate marketplace.json shape:

    - One bundle entry: name == "waza", source == "./".
    - Per-skill entries: name == "waza-<skill>", source == "./skills/<skill>".
    - All versions march in lock-step with the top-level VERSION file.
    """
    market_path = root / ".claude-plugin" / "marketplace.json"
    marketplace = json.loads(market_path.read_text())
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        fail("INVALID MARKETPLACE: plugins must be a list")

    market_versions: dict[str, str] = {}
    market_descriptions: dict[str, str] = {}
    seen_names: set[str] = set()
    bundle_version = ""
    for entry in plugins:
        if not isinstance(entry, dict):
            fail("INVALID MARKETPLACE: plugin entry must be an object")
        name = entry.get("name")
        version = entry.get("version")
        source = entry.get("source")
        description = (entry.get("description") or "").strip().strip('"')
        if not name or not version:
            fail("INVALID MARKETPLACE: every plugin needs name and version")
        if not description:
            fail(f"MISSING DESCRIPTION: marketplace plugin {name}")
        if name in seen_names:
            fail(f"DUPLICATE MARKETPLACE ENTRY: {name}")
        seen_names.add(name)

        if name == "waza":
            if source != "./":
                fail(f"WRONG BUNDLE SOURCE: source={source!r} expected='./'")
            bundle_version = version
            continue

        if not name.startswith("waza-"):
            fail(
                f"INVALID PLUGIN NAME: {name!r} must be 'waza' (bundle) or "
                f"'waza-<skill>' (per-skill entry)"
            )
        skill_name = name.removeprefix("waza-")
        if not skill_name:
            fail(
                f"INVALID PLUGIN NAME: {name!r} has an empty <skill> suffix; "
                f"per-skill entries must be named 'waza-<skill>' with a non-empty skill name"
            )
        expected_source = f"./skills/{skill_name}"
        if source != expected_source:
            fail(f"WRONG SOURCE: {name} source={source!r} expected={expected_source!r}")
        market_versions[skill_name] = version
        market_descriptions[skill_name] = description

    if "waza" not in seen_names:
        fail(
            "MISSING BUNDLE ENTRY: marketplace.json must include a 'waza' bundle entry "
            "(name=\"waza\", source=\"./\") so /plugin install waza@waza registers "
            "all skills under the waza namespace"
        )

    missing_from_market = sorted(set(skill_versions) - set(market_versions))
    if missing_from_market:
        fail("NOT IN MARKETPLACE: " + ", ".join(missing_from_market))
    extra_in_market = sorted(set(market_versions) - set(skill_versions))
    if extra_in_market:
        fail("MISSING SKILL DIRECTORY: " + ", ".join(extra_in_market))

    for skill, skill_version in sorted(skill_versions.items()):
        market_version = market_versions[skill]
        if market_version != expected_version:
            fail(
                f"VERSION DRIFT: marketplace waza-{skill} version={market_version!r} "
                f"!= VERSION file {expected_version!r}.\n"
                f"  All marketplace entries march in lock-step. "
                f"Update .claude-plugin/marketplace.json to match VERSION."
            )
        if not market_descriptions[skill].startswith(skill_descriptions[skill]):
            fail(
                f"DESCRIPTION MISMATCH: {skill}\n"
                f"  SKILL.md:    {skill_descriptions[skill]}\n"
                f"  marketplace: {market_descriptions[skill]}\n"
                f"  marketplace description must start with the SKILL.md description"
            )
        print(f"ok: {skill} {skill_version}")

    if bundle_version and bundle_version != expected_version:
        fail(
            f"VERSION DRIFT: waza bundle version={bundle_version!r} "
            f"!= VERSION file {expected_version!r}.\n"
            f"  Update the 'waza' entry in .claude-plugin/marketplace.json to match VERSION."
        )
    print(f"ok: all versions in lock-step with VERSION={expected_version}")


def check_references(root: Path, skill_files: list[Path]):
    for path in skill_files:
        skill_dir = path.parent.name
        text = path.read_text()
        refs = set(REF_PATTERN.findall(text))
        refs |= {"scripts/" + s for s in SCRIPT_VAR_PATTERN.findall(text)}
        for ref in sorted(refs):
            expected = root / "skills" / skill_dir / ref
            if not expected.exists():
                fail(f"BROKEN REFERENCE: {path} references {ref} but file does not exist")
            print(f"ok: reference {skill_dir}/{ref}")


def check_description_conformance(skill_descriptions: dict[str, str]):
    """Every skill needs a triggerable opening, a 'Not for' exclusion, and a sane length.

    Locks the convention so new skills can't drift into vague descriptions that
    the Claude Code resolver can't match.
    """
    for skill, description in sorted(skill_descriptions.items()):
        clean = description.strip().strip('"')
        length = len(clean)
        if length < 40:
            fail(f"DESCRIPTION TOO SHORT: {skill} ({length} chars); need >=40 for reliable resolver matching")
        if length > 500:
            fail(f"DESCRIPTION TOO LONG: {skill} ({length} chars); trim to <=500 to keep the resolver index light")
        first_word = clean.split()[0].lower() if clean.split() else ""
        if first_word in ("the", "a", "an", "this", "it"):
            fail(
                f"DESCRIPTION STARTS WITH ARTICLE: {skill}\n"
                f"  Start with a verb or action phrase (third-person). Got: {clean[:60]!r}"
            )
        if "not for" not in clean.lower():
            fail(
                f"DESCRIPTION MISSING EXCLUSION CLAUSE: {skill}\n"
                f"  Must contain a 'Not for ...' clause so the resolver learns when NOT to fire. Got: {clean[:120]!r}"
            )
        print(f"ok: description {skill} ({length} chars)")


def check_durable_context_and_paths(root: Path, skill_files: list[Path]):
    """Durable context rules must stay portable and evidence-bound.

    Each skill in DURABLE_CONTEXT_SKILLS links to rules/durable-context.md for the
    shared preamble (when to read, read order, type mapping) and then adds
    skill-specific guidance with current-state override evidence. The shared
    rules file itself is checked once for the "raw transcripts" guard.
    """
    rules_path = root / "rules" / "durable-context.md"
    if not rules_path.exists():
        fail(
            f"MISSING SHARED RULE: {rules_path}\n"
            f"  Durable context preamble must live at rules/durable-context.md."
        )
    rules_text = rules_path.read_text().lower()
    if "raw transcripts" not in rules_text:
        fail(
            f"SHARED RULE MAY OVERREAD: {rules_path}\n"
            f"  rules/durable-context.md must forbid reading raw transcripts by default."
        )
    print("ok: rules/durable-context.md forbids raw transcripts")

    for path in skill_files:
        skill = path.parent.name
        text = path.read_text()
        if PERSONAL_PATH_PATTERN.search(text):
            fail(
                f"PERSONAL ABSOLUTE PATH IN SKILL: {path}\n"
                f"  Skill docs must not hard-code personal home-directory paths. "
                f"Use user-provided paths, project-relative paths, or resolver commands instead."
            )

        has_section = "## Durable Context Preflight" in text
        if skill in DURABLE_CONTEXT_SKILLS and not has_section:
            fail(
                f"MISSING DURABLE CONTEXT PREFLIGHT: {path}\n"
                f"  This skill must explain how to consume optional memory/preview context."
            )
        if not has_section:
            continue

        section = text.split("## Durable Context Preflight", 1)[1]
        section = section.split("\n## ", 1)[0]
        section_lower = section.lower()
        if "rules/durable-context.md" not in section:
            fail(
                f"DURABLE CONTEXT MISSING SHARED REFERENCE: {path}\n"
                f"  Section must link to rules/durable-context.md for the shared preamble."
            )
        if "current" not in section_lower or "override" not in section_lower:
            fail(
                f"DURABLE CONTEXT NOT EVIDENCE-BOUND: {path}\n"
                f"  Skill-specific paragraph must name what current state overrides memory."
            )
        print(f"ok: durable context preflight for {skill}")


def check_resolver(root: Path, skill_versions: dict[str, str]):
    """Every skill must be referenced from skills/RESOLVER.md.

    Keeps the human-readable index in lock-step with the SKILL.md descriptions
    the model actually sees.
    """
    resolver_path = root / "skills" / "RESOLVER.md"
    if not resolver_path.exists():
        fail(f"MISSING RESOLVER: expected {resolver_path}")
    resolver_text = resolver_path.read_text()
    for skill in sorted(skill_versions):
        token = f"skills/{skill}/SKILL.md"
        if token not in resolver_text:
            fail(
                f"RESOLVER GAP: {skill} has no entry in {resolver_path}\n"
                f"  Add a row to a triggers table that references {token!r}."
            )
        print(f"ok: resolver entry for {skill}")

    referenced_skills = set(SKILL_REF_RE.findall(resolver_text))
    stale = sorted(referenced_skills - set(skill_versions))
    if stale:
        fail(f"RESOLVER REFERENCES MISSING SKILL: {', '.join(stale)}")
    print("ok: resolver has no stale skill references")
    return resolver_path


def collect_all_md(root: Path, skill_versions: dict[str, str], resolver_path: Path) -> list[Path]:
    all_md: list[Path] = [resolver_path]
    for skill in sorted(skill_versions):
        skill_root = root / "skills" / skill
        all_md.append(skill_root / "SKILL.md")
        for sub in ("references", "agents"):
            sub_dir = skill_root / sub
            if sub_dir.is_dir():
                all_md.extend(sorted(sub_dir.rglob("*.md")))
    return all_md


def check_markdown_links(root: Path, all_md: list[Path]):
    for path in all_md:
        if not path.exists():
            continue
        in_code = False
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for m in LINK_RE.finditer(line):
                raw = m.group(1).strip()
                if not raw or raw.startswith(("#", "/")):
                    continue
                if raw.startswith(URL_PREFIXES) or "://" in raw:
                    continue
                target = raw.split("#", 1)[0].split("?", 1)[0]
                if target and not (path.parent / target).resolve().exists():
                    fail(f"BROKEN MARKDOWN LINK: {path}:{lineno} -> {raw}")
        print(f"ok: markdown links {path.relative_to(root)}")


# Unescaped | in data cells breaks GitHub rendering (#35).
def check_table_pipes(root: Path, all_md: list[Path]):
    for path in all_md:
        if not path.exists():
            continue
        in_fence = False
        sep_pipes = None
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                sep_pipes = None
                continue
            if in_fence:
                sep_pipes = None
                continue
            if SEP_RE.match(stripped) and "---" in stripped and "|" in stripped:
                sep_pipes = pipe_count(stripped)
                continue
            if sep_pipes is not None and stripped.startswith("|"):
                if pipe_count(stripped) > sep_pipes:
                    fail(
                        f"UNESCAPED PIPE IN TABLE: {path}:{lineno}\n"
                        f"  Use '\\|' or wrap the cell text in backticks."
                    )
                continue
            sep_pipes = None
        print(f"ok: table pipes {path.relative_to(root)}")


def check_no_root_skill(root: Path):
    """A root SKILL.md would make `npx skills add tw93/Waza` stop scanning nested
    skills, so the direct coding install path would expose only `/waza`. Claude
    Desktop's single-root SKILL.md is generated by scripts/package-skill.sh
    during release packaging.
    """
    root_skill = root / "SKILL.md"
    if root_skill.exists():
        fail("ROOT SKILL DISALLOWED: generate the Desktop dispatcher during packaging instead")
    print("ok: no root SKILL.md")


def check_trigger_overlap(skill_keywords: dict[str, set[str]]):
    """Pairwise Jaccard >= 0.5 means more than half the combined keywords are shared."""
    names = sorted(skill_keywords)
    found_overlap = False
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = skill_keywords[a] & skill_keywords[b]
            union = skill_keywords[a] | skill_keywords[b]
            if not union:
                continue
            jaccard = len(shared) / len(union)
            if jaccard >= 0.5:
                print(
                    f"TRIGGER OVERLAP: {a} vs {b} jaccard={jaccard:.2f} shared={sorted(shared)}",
                    file=sys.stderr,
                )
                found_overlap = True
    if found_overlap:
        raise SystemExit(1)
    print("ok: trigger keyword overlap below threshold")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--skills-only",
        action="store_true",
        help=(
            "Verify only per-skill frontmatter under <root>/skills/. Skips "
            "marketplace.json, RESOLVER.md, README, and root-level checks. "
            "Use when validating an installed copy that does not ship the "
            "build-only files."
        ),
    )
    args = parser.parse_args()
    root = args.root.resolve()

    if args.skills_only:
        skills_dir = root / "skills"
        if not skills_dir.is_dir():
            fail(f"MISSING SKILLS DIR: {skills_dir}")
        skill_files = sorted(skills_dir.glob("*/SKILL.md"))
        if not skill_files:
            fail(f"NO SKILL.md FILES UNDER {skills_dir}")
        skill_versions: dict[str, str] = {}
        skill_descriptions: dict[str, str] = {}
        for path in skill_files:
            fields = parse_frontmatter(path)
            name = fields["name"]
            if name != path.parent.name:
                fail(f"NAME MISMATCH: {path} frontmatter={name!r} dir={path.parent.name!r}")
            if not fields["description"].strip():
                fail(f"EMPTY DESCRIPTION: {path}")
            skill_versions[name] = fields.get("version", "")
            skill_descriptions[name] = fields["description"]
        check_description_conformance(skill_descriptions)
        # Durable context preflight needs rules/durable-context.md; only run
        # the check when that file is also present in the installed tree.
        if (root / "rules" / "durable-context.md").exists():
            check_durable_context_and_paths(root, skill_files)
        print(f"ok: skills-only verification passed for {len(skill_files)} skills")
        return 0

    version_file = root / "VERSION"
    if not version_file.exists():
        fail("MISSING VERSION FILE: expected top-level VERSION with one line like '3.24.0'")
    expected_version = version_file.read_text().strip()
    if not expected_version:
        fail("EMPTY VERSION FILE: VERSION must contain one line like '3.24.0'")

    skill_files, skill_versions, skill_descriptions, skill_keywords = check_skill_files(root, expected_version)
    check_marketplace(root, expected_version, skill_versions, skill_descriptions)
    check_references(root, skill_files)
    check_description_conformance(skill_descriptions)
    check_durable_context_and_paths(root, skill_files)
    resolver_path = check_resolver(root, skill_versions)
    all_md = collect_all_md(root, skill_versions, resolver_path)
    check_markdown_links(root, all_md)
    check_table_pipes(root, all_md)
    check_no_root_skill(root)
    check_trigger_overlap(skill_keywords)
    return 0


if __name__ == "__main__":
    sys.exit(main())
