# -*- coding: utf-8 -*-
import os
from argparse import Namespace

import pytest
from adr.configuration import Configuration
from adr.query import run_query

from mozci import task
from mozci.push import Push

pytestmark = pytest.mark.skipif(
    os.environ.get("TRAVIS_EVENT_TYPE") != "cron", reason="Not run by a cron task"
)

if not os.environ.get("ADR_CONFIG_PATH"):
    raise Exception("Set ADR_CONFIG_PATH to tests/config.toml")


@pytest.fixture
def adr_config(tmp_path):
    config_file = tmp_path / "config.toml"
    text = (
        """
[adr]
verbose = true
[adr.cache]
default = "file"
retention = 1000
[adr.cache.stores]
file = { driver = "file", path = "%s" }
"""
        % tmp_path
    )
    config_file.write_text(text)
    return Configuration(path=config_file)


def test_missing_manifests():
    """
    Ensure all suites (except a blacklist) are generating manifest information.
    """
    BLACKLIST = (
        "web-platform-tests",
        "talos",
        "web-platform-tests-reftest",
        "web-platform-tests-wdspec",
        "web-platform-tests-crashtest",
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
    BLACKLIST = {
        "marionette",
        "web-platform-tests",
        "web-platform-tests-reftest",
        "web-platform-tests-wdspec",
    }
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

    for (groups, label) in result["data"]:
        if groups is None:
            continue

        if not isinstance(groups, list):
            groups = [groups]

        for group in groups:
            assert (
                not task.is_bad_group("x", label, group) and "\\" not in group
            ), f"{group} group for task {label} is bad!"


def test_good_result_manifests():
    """
    Ensure there are no bad manifest paths in recent result manifest information.
    """
    result = run_query("test_all_result_groups", Namespace())

    for group, label, _ in result["data"]:
        if group is None:
            continue

        assert (
            not task.is_bad_group("x", label, group) and "\\" not in group
        ), f"{group} group for task {label} is bad!"


def test_caching_of_push(adr_config):
    # Once we reach Nov. 23rd, 2020 the test should be updated with a more recent push and task ID
    TASK_ID = "WGNh9Xd8RmSG_170-0-mkQ"
    REV = "6e87f52e6eebdf777f975baa407d5c22e9756e80"
    # Making sure there's nothing left in the cache
    assert adr_config.cache.get(REV) is None
    # Push from Nov. 22nd, 2019
    push = Push(REV, branch="mozilla-beta")
    tasks = push.tasks

    found_task = False
    for t in tasks:
        # We are just testing that the task was retrieved
        if t.id == TASK_ID:
            found_task = True
            break
    assert found_task

    # Testing that the tasks associated to a push have been cached
    assert len(adr_config.cache.get(REV)) == 2166

    # XXX: We could test here that a 2nd call hits the cache
    push.tasks

    # Q: Is it good practice to clean the test here?
    adr_config.cache.forget(REV)
    assert adr_config.cache.get(REV) is None
