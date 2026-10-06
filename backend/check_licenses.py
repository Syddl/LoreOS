"""Fail when an installed backend package declares a copyleft license, strong or weak, or none at all.

Run from backend/: python check_licenses.py. Allowed exception: certifi under MPL-2.0, which tiktoken
needs through requests (docs/decisions/0002-parsing-and-driver-libraries.md).
"""

import re
import sys
from importlib.metadata import distributions

COPYLEFT = re.compile(
    r"\b(?:A?GPL|LGPL|General Public|SSPL|Server Side Public|EUPL|European Union Public|MPL|Mozilla Public"
    r"|EPL|Eclipse Public|CDDL|OSL|Open Software License|CECILL|CC-BY-SA|ShareAlike|copyleft)\b",
    re.I,
)
MPL = re.compile(r"\b(?:MPL|Mozilla Public)\b[^|]*", re.I)
MPL_ALLOWED = {"certifi"}


def declared(dist) -> str:
    """License-Expression when present, else the License field and the license classifiers."""
    meta = dist.metadata
    if expression := meta.get("License-Expression"):
        return expression
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return " | ".join(part for part in [meta.get("License") or "", *classifiers] if part.strip())


def problems(packages: list[tuple[str, str]]) -> list[str]:
    out = []
    for name, license_ in packages:
        checked = MPL.sub("", license_) if name.lower() in MPL_ALLOWED else license_
        if not license_.strip():
            out.append(f"{name}: declares no license")
        elif COPYLEFT.search(checked):
            out.append(f"{name}: {license_.splitlines()[0]}")
    return out


if __name__ == "__main__":
    packages = sorted((d.metadata["Name"], declared(d)) for d in distributions())
    found = problems(packages)
    for line in found:
        print(f"  FAIL {line}")
    print(f"check:licenses: {len(packages) - len(found)}/{len(packages)} installed backend packages pass")
    sys.exit(1 if found else 0)
