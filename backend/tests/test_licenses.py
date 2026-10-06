from check_licenses import problems


def test_permissive_licenses_pass():
    assert problems([("a", "MIT"), ("b", "Apache-2.0 OR BSD-2-Clause"), ("c", "MIT License\n\nCopyright (c) 2022")]) == []


def test_strong_and_weak_copyleft_fail():
    found = problems([("x", "AGPL-3.0"), ("y", "LGPL-3.0-or-later"), ("z", "GNU General Public License v3 (GPLv3)")])
    assert [line.split(":")[0] for line in found] == ["x", "y", "z"]


def test_mpl_is_allowed_for_certifi_only():
    assert problems([("certifi", "MPL-2.0 | Mozilla Public License 2.0 (MPL 2.0)"), ("other", "MPL-2.0")]) == [
        "other: MPL-2.0"
    ]


def test_certifi_under_another_copyleft_still_fails():
    assert problems([("certifi", "GPL-3.0")]) == ["certifi: GPL-3.0"]


def test_no_declared_license_fails():
    assert problems([("mystery", "")]) == ["mystery: declares no license"]
