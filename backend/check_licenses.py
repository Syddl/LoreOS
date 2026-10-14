"""Fail when a backend or frontend dependency declares a copyleft license other than MPL-2.0, or none at all.

MPL-2.0 passes: LoreOS uses its MPL-2.0 dependencies unmodified (docs/decisions/0007-mpl-2-0-dependencies-unmodified.md).
Run from backend/:
- python check_licenses.py checks the installed backend distributions;
- npm ls --omit=dev --all --json --long --prefix frontend | python check_licenses.py --npm-tree -
  checks the frontend's production tree.
"""

import argparse
import json
import re
import sys
from importlib.metadata import distributions

COPYLEFT = re.compile(
    r"\b(?:A?GPL|LGPL|General Public|SSPL|Server Side Public|EUPL|European Union Public"
    r"|EPL|Eclipse Public|CDDL|OSL|Open Software License|CECILL|CC-BY-SA|ShareAlike|copyleft)\b",
    re.I,
)
# The opening words of the permissive license texts a package may ship without declaring its license.
PERMISSIVE_TEXT = re.compile(
    r"\b(?:MIT License|Permission is hereby granted|Apache License|BSD \d-Clause|Redistribution and use in source and binary"
    r"|ISC License|Permission to use, copy, modify|Zlib License|This is free and unencumbered software)\b",
    re.I,
)


def declared(dist) -> str:
    """License-Expression when present, else the License field and the license classifiers, else the text of the
    license files the package ships (License-File), whole, so a copyleft name anywhere in them fails."""
    meta = dist.metadata
    if expression := meta.get("License-Expression"):
        return expression
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if found := " | ".join(part for part in [meta.get("License") or "", *classifiers] if part.strip()):
        return found
    # Metadata 2.4 keeps them under licenses/ in .dist-info; older wheels at its top.
    texts = [dist.read_text(f"licenses/{name}") or dist.read_text(name) or "" for name in meta.get_all("License-File") or []]
    text = "\n".join(text.strip() for text in texts if text.strip())
    # License-File also takes AUTHORS and NOTICE: text that names no license is no license, and a copyleft name still fails.
    return text if PERMISSIVE_TEXT.search(text) or COPYLEFT.search(text) else ""


def npm_license(pkg: dict) -> str:
    """`license` as a string or a {type} object, else the legacy `licenses` list; "" when there is none."""
    value = pkg.get("license") or pkg.get("licenses") or []
    items = value if isinstance(value, list) else [value]
    names = [item.get("type") if isinstance(item, dict) else item for item in items]
    # An unreadable entry (a number, a {type} without a type) counts as no license, which fails.
    return " OR ".join(n for n in names if isinstance(n, str) and n.strip())


def npm_packages(tree: dict) -> list[tuple[str, str]]:
    """(name, license) once per name and version in `npm ls --all --json --long` output.

    npm writes a repeated package as a stub without `dependencies` at all but one place, and the stub can come
    first, so every node's children are walked and only the listing is deduplicated.
    """
    seen, out = set(), []

    def walk(deps: dict) -> None:
        for name, pkg in deps.items():
            if (name, pkg.get("version")) not in seen:
                seen.add((name, pkg.get("version")))
                out.append((name, npm_license(pkg)))
            walk(pkg.get("dependencies") or {})

    walk(tree.get("dependencies") or {})
    return out


def problems(packages: list[tuple[str, str]]) -> list[str]:
    out = []
    for name, license_ in packages:
        if not license_.strip():
            out.append(f"{name}: declares no license")
        elif COPYLEFT.search(license_):
            out.append(f"{name}: {license_.splitlines()[0]}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--npm-tree", choices=["-"], help="read `npm ls --all --json --long` output from stdin")
    if parser.parse_args().npm_tree:
        # Bytes, not text: a text-mode stdin decodes in the ANSI code page on Windows, and npm's --long
        # output carries non-ASCII package descriptions.
        packages, label = sorted(npm_packages(json.load(sys.stdin.buffer))), "frontend npm packages"
    else:
        packages, label = sorted((d.metadata["Name"], declared(d)) for d in distributions()), "installed backend packages"
    found = problems(packages)
    for line in found:
        print(f"  FAIL {line}")
    print(f"check:licenses: {len(packages) - len(found)}/{len(packages)} {label} pass")
    sys.exit(1 if found else 0)
