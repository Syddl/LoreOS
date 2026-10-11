"""The license rule in check_licenses.problems(), and the npm tree reader behind check:licenses.

Proves: decision 0007's rule (MPL-2.0 passes, GPL, LGPL and AGPL fail, no license fails); that npm_packages()
lists each package once per name and version, with its license in every shape npm writes; and that
`check_licenses.py --npm-tree -` reads a non-ASCII tree from a real pipe in an interpreter without UTF-8 mode,
the Windows default.
Does NOT exercise: whether an MPL-2.0 dependency is in fact unmodified (no check can see that), or the real
`npm ls` output and installed backend distributions, which `npm run check:licenses` reads.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from check_licenses import npm_packages, problems

BACKEND = Path(__file__).resolve().parent.parent


def test_permissive_licenses_pass():
    assert problems([("a", "MIT"), ("b", "Apache-2.0 OR BSD-2-Clause"), ("c", "MIT License\n\nCopyright (c) 2022")]) == []


def test_strong_and_weak_copyleft_fail():
    found = problems([("x", "AGPL-3.0"), ("y", "LGPL-3.0-or-later"), ("z", "GNU General Public License v3 (GPLv3)")])
    assert [line.split(":")[0] for line in found] == ["x", "y", "z"]


def test_mpl_is_allowed_unmodified():
    # Decision 0007: MPL-2.0 binds only changes to its own files, so any unmodified MPL-2.0 dependency passes.
    found = problems(
        [
            ("lightningcss", "MPL-2.0"),
            ("tqdm", "MPL-2.0 AND MIT"),
            ("certifi", "MPL-2.0 | Mozilla Public License 2.0 (MPL 2.0)"),
        ]
    )
    assert found == [], f"MPL-2.0 must pass unmodified (decision 0007): {found}"


def test_certifi_under_another_copyleft_still_fails():
    assert problems([("certifi", "GPL-3.0")]) == ["certifi: GPL-3.0"]


def test_no_declared_license_fails():
    assert problems([("mystery", "")]) == ["mystery: declares no license"]


# The shape of `npm ls --all --json --long`. npm writes a repeated package in full at one place and as a stub
# without `dependencies` at the others, and the stub can come first, as `shared` does here.
TREE = {
    "name": "loreos-frontend",
    "dependencies": {
        "a": {
            "version": "1.0.0",
            "license": "MIT",
            "dependencies": {
                "shared": {"version": "2.0.0", "license": "ISC"},
                "old": {"version": "0.1.0", "license": {"type": "BSD-3-Clause", "url": "https://example.test"}},
            },
        },
        "shared": {
            "version": "2.0.0",
            "license": "ISC",
            "dependencies": {
                "legacy": {"version": "3.0.0", "licenses": [{"type": "MIT"}, {"type": "Apache-2.0"}]},
                "bare": {"version": "1.2.3"},
            },
        },
        "b": {"version": "1.0.0", "license": "Apache-2.0", "dependencies": {"shared": {"version": "1.0.0", "license": "MIT"}}},
    },
}


def test_npm_packages_lists_each_name_and_version_once():
    assert sorted(npm_packages(TREE)) == [
        ("a", "MIT"),
        ("b", "Apache-2.0"),
        ("bare", ""),
        ("legacy", "MIT OR Apache-2.0"),
        ("old", "BSD-3-Clause"),
        ("shared", "ISC"),
        ("shared", "MIT"),
    ]
    assert problems(npm_packages(TREE)) == ["bare: declares no license"]


def run_npm_tree(tree: dict) -> subprocess.CompletedProcess:
    """check:licenses's own call, from backend/, with UTF-8 mode off as on a stock Windows Python."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")} | {"PYTHONUTF8": "0"}
    return subprocess.run(
        [sys.executable, "check_licenses.py", "--npm-tree", "-"],
        cwd=BACKEND,
        input=json.dumps(tree, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env=env,
    )


# UTF-8 for Ё and č carries the bytes 0x81 and 0x8D, which cp1252 cannot decode.
DESCRIPTION = "Ёлка, čaj, 日本語 ✓"


def test_npm_tree_with_a_non_ascii_description_passes_through_a_pipe():
    tree = {"dependencies": {"x": {"version": "1.0.0", "license": "MIT", "description": DESCRIPTION}}}
    r = run_npm_tree(tree)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert b"1/1 frontend npm packages pass" in r.stdout


def test_npm_tree_with_a_copyleft_package_fails_through_a_pipe():
    nested = {"y": {"version": "2.0.0", "license": "LGPL-3.0-only"}}
    tree = {"dependencies": {"x": {"version": "1.0.0", "license": "MIT", "description": DESCRIPTION, "dependencies": nested}}}
    r = run_npm_tree(tree)
    assert r.returncode == 1, r.stderr.decode("utf-8", "replace")
    assert b"FAIL y: LGPL-3.0-only" in r.stdout
    assert b"1/2 frontend npm packages pass" in r.stdout
