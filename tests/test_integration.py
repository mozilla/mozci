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
        "talos",
        "jittest",
        "geckoview-junit",
        "cppunittest",
        None,
    )
    ALLOWED_MISSING = 5

    result = run_query("test_missing_manifests", Namespace())

    missing = []

    for suite, count in result["data"]:
        if suite not in BLACKLIST:
            if count > ALLOWED_MISSING:
                missing.append((suite, count))

    assert missing == []

    # Ensure the blacklist doesn't contain more than necessary.
    unblacklistable = []
    found_suites = {suite: count for suite, count in result["data"]}
    for suite in BLACKLIST:
        if suite not in found_suites or found_suites[suite] < ALLOWED_MISSING:
            unblacklistable.append(suite)

    assert unblacklistable == []


def test_missing_result_manifests():
    """
    Ensure unittest results from all manifest-based suites (except a blacklist)
    have information on what manifest the result corresponds to.
    """
    BLACKLIST = {
        "marionette",
    }
    ALLOWED_MISSING = 70

    result = run_query("test_missing_result_manifests", Namespace())

    missing = []

    for suite, count in result["data"]:
        if suite not in BLACKLIST:
            if count > ALLOWED_MISSING:
                missing.append((suite, count))

    assert missing == []

    # Ensure the blacklist doesn't contain more than necessary.
    unblacklistable = []
    found_suites = {suite: count for suite, count in result["data"]}
    for suite in BLACKLIST:
        if suite not in found_suites or found_suites[suite] < ALLOWED_MISSING:
            unblacklistable.append(suite)

    assert unblacklistable == []


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


def test_caching_of_tasks(adr_config):
    return
    # Once we reach Nov. 23rd, 2020 the test should be updtated with a more recent push and task ID
    TASK_ID = "WGNh9Xd8RmSG_170-0-mkQ"
    # Making sure there's nothing left in the cache
    assert adr_config.cache.get(TASK_ID) is None
    # Push from Nov. 22nd, 2019
    push = Push("6e87f52e6eebdf777f975baa407d5c22e9756e80", branch="mozilla-beta")
    tasks = push.tasks
    found_task = False
    for t in tasks:
        if t.id == TASK_ID:
            task = adr_config.cache.get(TASK_ID)
            assert task is None
            # Calling one of the three properties will call _load_error_summary
            # and cache the data
            t.results
            task = adr_config.cache.get(TASK_ID)
            assert task["groups"]
            assert not task["errors"]
            assert not task["results"]
            found_task = True
            break

    assert found_task
