# -*- coding: utf-8 -*-
import os
from argparse import Namespace

import pytest
from adr.query import run_query

from mozci import task

pytestmark = pytest.mark.skipif(
    os.environ.get("TRAVIS_EVENT_TYPE") != "cron", reason="Not run by a cron task"
)


def test_missing_manifests():
    """
    Ensure all suites (except a blacklist) are generating manifest information.
    """
    BLACKLIST = (
        "web-platform-tests",
        "talos",
        "web-platform-tests-reftests",
        "web-platform-tests-wdspec",
        "web-platform-tests-crashtests",
        "jittest",
        "geckoview-junit",
        "cppunittest",
        "test-verify-wpt",
        None,
    )
    ALLOWED_MISSING = 5

    result = run_query("test_missing_manifests", Namespace())

    for suite, count in result["data"]:
        if suite not in BLACKLIST:
            assert count < ALLOWED_MISSING, f"{suite} is missing manifest information"

    # Ensure the blacklist doesn't contain more than necessary.
    found_suites = {suite for suite, count in result["data"]}
    for suite in BLACKLIST:
        assert suite in found_suites, f"{suite} might be removed from the blacklist"


def test_missing_result_manifests():
    """
    Ensure unittest results from all manifest-based suites (except a blacklist)
    have information on what manifest the result corresponds to.
    """
    BLACKLIST = {"marionette"}
    ALLOWED_MISSING = 70

    result = run_query("test_missing_result_manifests", Namespace())

    for suite, count in result["data"]:
        if suite not in BLACKLIST:
            assert (
                count < ALLOWED_MISSING
            ), f"{suite} is missing result manifest information"

    # Ensure the blacklist doesn't contain more than necessary.
    found_suites = {suite for suite, count in result["data"]}
    for suite in BLACKLIST:
        assert suite in found_suites, f"{suite} might be removed from the blacklist"


def test_good_manifests():
    """
    Ensure there are no bad manifest paths in recent manifest information.
    """
    result = run_query("test_all_groups", Namespace())

    for (groups,) in result["data"]:
        if groups is None:
            continue

        if not isinstance(groups, list):
            groups = [groups]

        for group in groups:
            assert (
                not task.is_bad_group("x", group) and "\\" not in group
            ), f"{group} group is bad!"


def test_good_result_manifests():
    """
    Ensure there are no bad manifest paths in recent result manifest information.
    """
    result = run_query("test_all_result_groups", Namespace())

    for group, count in result["data"]:
        if group is None:
            continue

        assert (
            not task.is_bad_group("x", group) and "\\" not in group
        ), f"{group} group is bad!"
