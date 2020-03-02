# -*- coding: utf-8 -*-
from argparse import Namespace

from adr.query import run_query


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

    result = run_query("test_missing_manifests", Namespace())

    for suite, count in result["data"]:
        assert (
            suite in BLACKLIST
        ), f"{suite} is missing manifests information ({count} entries)"

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
    ALLOWED_MISSING = 50

    result = run_query("test_missing_result_manifests", Namespace())

    for suite, count in result["data"]:
        if suite not in BLACKLIST:
            assert (
                count < ALLOWED_MISSING
            ), f"{suite} is missing result manifest information"

    # Ensure the blacklist doesn't contain more than necessary.
    found_suites = {
        suite for suite, count in result["data"] if count >= ALLOWED_MISSING
    }
    for suite in BLACKLIST:
        assert suite in found_suites, f"{suite} might be removed from the blacklist"
