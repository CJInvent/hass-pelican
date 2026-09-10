#!/usr/bin/env python3
"""Repo consistency gate.

Enforces the dev rules a linter cannot see:

  rule 3   every polled attribute has a consumer, and every attribute an
           entity reads is actually polled
  rule 15  strings.json and translations/en.json are byte-identical
  rule 16  manifest version is valid semver and the domain matches the folder
  rule 14  every translation_key used by an entity exists in strings.json

Exits non-zero with a specific message on the first class of failure found.
Run directly, or via scripts/local-gates.sh.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "custom_components" / "pelican"
API = PACKAGE / "api.py"

# Attributes referenced outside the Python source: keys the coordinator uses
# structurally rather than through the attr() helpers.
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

ATTR_CALL = re.compile(r"attr(?:_int|_float)?\(\s*[\"']([A-Za-z0-9_]+)[\"']\s*\)")
# schedule.py reads every ThermostatSchedule attribute through field()/field_int()
# so the same both-directions check applies there too.
FIELD_CALL = re.compile(
    r"\bfield(?:_int)?\(\s*\w+\s*,\s*[\"']([A-Za-z0-9_]+)[\"']\s*\)"
)


def fail(message: str) -> None:
    """Print a failure and exit non-zero."""
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def polled_attributes(name: str) -> list[str]:
    """Parse a tuple of attribute names out of api.py."""
    source = API.read_text(encoding="utf-8")
    match = re.search(rf"{name}\s*=\s*\((.*?)\)", source, re.DOTALL)
    if not match:
        fail(f"could not find {name} in api.py")
    return re.findall(r"[\"']([A-Za-z0-9_]+)[\"']", match.group(1))  # type: ignore[union-attr]


def _check_contract(
    label: str,
    tuple_name: str,
    reader: re.Pattern[str],
    consumers: dict[Path, str],
) -> int:
    """Check one polled-attribute contract in both directions (rule 3)."""
    polled = polled_attributes(tuple_name)
    if not polled:
        fail(f"{tuple_name} is empty")

    duplicates = {item for item in polled if polled.count(item) > 1}
    if duplicates:
        fail(f"{tuple_name} has duplicates: {sorted(duplicates)}")

    combined = "\n".join(consumers.values())
    unused = [
        item
        for item in polled
        if f'"{item}"' not in combined and f"'{item}'" not in combined
    ]
    if unused:
        fail(
            f"these {label} attributes are polled but never read — remove them "
            f"from {tuple_name} or wire them up: {unused}"
        )

    missing: dict[str, set[str]] = {}
    for path, source in consumers.items():
        for item in reader.findall(source):
            if item not in polled:
                missing.setdefault(item, set()).add(path.name)
    if missing:
        detail = ", ".join(
            f"{item} (read in {', '.join(sorted(files))})"
            for item, files in sorted(missing.items())
        )
        fail(
            f"{label} attributes read but not polled — add them to "
            f"{tuple_name}: {detail}"
        )

    return len(polled)


def check_attributes() -> None:
    """Rule 3, both directions, for both polled objects."""
    consumers = {
        path: path.read_text(encoding="utf-8")
        for path in PACKAGE.rglob("*.py")
        if path != API
    }
    thermostat_count = _check_contract(
        "thermostat", "THERMOSTAT_ATTRIBUTES", ATTR_CALL, consumers
    )
    schedule_count = _check_contract(
        "schedule", "SCHEDULE_ATTRIBUTES", FIELD_CALL, consumers
    )
    print(
        f"  attributes: {thermostat_count} thermostat + {schedule_count} schedule, "
        "all consumed, none missing"
    )


def check_strings() -> None:
    """Rules 14 and 15.

    Entity names, exception messages and repair issues all use translation_key
    but live in different sections of strings.json, so they are checked
    separately. An exception key is distinguishable because it is always passed
    alongside translation_domain=DOMAIN.
    """
    strings_path = PACKAGE / "strings.json"
    en_path = PACKAGE / "translations" / "en.json"

    if strings_path.read_bytes() != en_path.read_bytes():
        fail(
            "strings.json and translations/en.json differ — copy strings.json "
            "over translations/en.json (rule 15)"
        )

    strings = json.loads(strings_path.read_text(encoding="utf-8"))

    declared_entity: set[str] = set()
    for platform, entries in (strings.get("entity") or {}).items():
        declared_entity.update(f"{platform}.{key}" for key in entries)

    declared_other: set[str] = set(strings.get("exceptions") or {})
    declared_other.update(strings.get("issues") or {})

    used_entity: set[str] = set()
    used_other: set[str] = set()
    all_source: list[str] = []

    for path in PACKAGE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        all_source.append(source)
        # Keys passed with translation_domain are exception or issue keys.
        domain_scoped = set(
            re.findall(
                r"translation_domain\s*=\s*DOMAIN\s*,\s*"
                r"translation_key\s*=\s*[\"\']([A-Za-z0-9_]+)[\"\']",
                source,
            )
        )
        used_other |= domain_scoped
        for key in re.findall(
            r"translation_key\s*[=:]\s*[\"\']([A-Za-z0-9_]+)[\"\']", source
        ):
            if key not in domain_scoped:
                used_entity.add(f"{path.stem}.{key}")

    combined = "\n".join(all_source)

    orphans = sorted(used_entity - declared_entity)
    if orphans:
        fail(f"entity translation_key used but not declared in strings.json: {orphans}")

    unused = sorted(declared_entity - used_entity)
    if unused:
        fail(f"strings.json declares entity names nothing uses (rule 23): {unused}")

    missing = sorted(used_other - declared_other)
    if missing:
        fail(
            "exception/issue translation_key used but not declared under "
            f"'exceptions' or 'issues' in strings.json: {missing}"
        )

    # Issue keys are referenced through a constant rather than a literal at the
    # call site, so they are matched against the package source as a whole.
    dead = sorted(
        key
        for key in declared_other
        if key not in used_other
        and f'"{key}"' not in combined
        and f"'{key}'" not in combined
    )
    if dead:
        fail(f"strings.json declares exceptions/issues nothing uses (rule 23): {dead}")

    print(
        f"  strings: en.json in sync, {len(declared_entity)} entity names and "
        f"{len(declared_other)} exception/issue messages all used"
    )


def check_manifest() -> None:
    """Rule 16 plus basic manifest hygiene."""
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))

    if manifest["domain"] != PACKAGE.name:
        fail(
            f"manifest domain {manifest['domain']!r} does not match folder "
            f"{PACKAGE.name!r}"
        )

    version = manifest.get("version", "")
    if not SEMVER.match(version):
        fail(f"manifest version {version!r} is not semver")

    if manifest.get("requirements"):
        fail("manifest declares runtime requirements — rule 1 says zero")

    print(f"  manifest: domain={manifest['domain']} version={version} requirements=[]")


def main() -> None:
    """Run every consistency check."""
    print("consistency:")
    check_attributes()
    check_strings()
    check_manifest()
    print("  OK")


if __name__ == "__main__":
    main()
