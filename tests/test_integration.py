# -*- coding: utf-8 -*-
import os
from argparse import Namespace

import pytest
from adr.configuration import Configuration
from adr.query import run_query

from mozci import task
from mozci.push import Push, make_push_objects
from mozci.task import TestTask

pytestmark = pytest.mark.skipif(
    os.environ.get("TRAVIS_EVENT_TYPE") != "cron", reason="Not run by a cron task"
)

if not os.environ.get("ADR_CONFIG_PATH"):
    raise Exception("Set ADR_CONFIG_PATH to tests/config.toml")


@pytest.fixture
def adr_config(tmp_path):
    from pathlib import Path

    config_file = Path.cwd() / "config.toml"
    # config_file = tmp_path / "config.toml"
    # If you need to iterate
    text = (
        """
[adr]
verbose = true
[adr.cache]
default = "file"
retention = 1000
[adr.cache.stores]
file = { driver = "file", path = "%s/adr_cache" }
"""
        % Path.cwd()
    )
    print(config_file)
    config_file.write_text(text)
    # adr_config = Configuration(path=config_file)
    return Configuration()


def test_create_pushes_and_get_regressions():
    """
    An integration test mimicking the mozci usage done by bugbug.
    """
    pushes = make_push_objects(
        from_date="today-7day", to_date="today-6day", branch="autoland",
    )

    assert len(pushes) > 0

    push = pushes[round(len(pushes) / 2)]

    assert len(push.task_labels) > 0
    assert len(push.group_summaries) > 0

    push.get_possible_regressions("label")
    push.get_possible_regressions("group")

    push.get_likely_regressions("label")
    push.get_likely_regressions("group")


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

            if any(s in label for s in {"web-platform-tests", "test-verify-wpt"}):
                group = task.wpt_workaround(group)

            assert (
                not task.is_bad_group("x", group) and "\\" not in group
            ), f"{group} group for task {label} is bad!"


def test_good_result_manifests():
    """
    Ensure there are no bad manifest paths in recent result manifest information.
    """
    result = run_query("test_all_result_groups", Namespace())

    for group, label, _ in result["data"]:
        if group is None:
            continue

        if any(s in label for s in {"web-platform-tests", "test-verify-wpt"}):
            group = task.wpt_workaround(group)

        assert (
            not task.is_bad_group("x", group) and "\\" not in group
        ), f"{group} group for task {label} is bad!"


def test_caching_issue(adr_config):
    from mozci.task import GroupResult

    a = GroupResult(
        group="testing/marionette/harness/marionette_harness/tests/unit-tests.ini",
        ok=True,
    )
    adr_config.cache.put("foo", a, 5)
    print(adr_config.get("foo"))
    assert adr_config.get("foo")


def test_caching_of_push(adr_config):
    # A push if it's very recent, it will have almost no tasks in AD
    # few days later all data will come from AD and after 6 weeks it will have no data there.
    # Data about the results for a task will come via AD or through the errorsummary artifact
    # via Taskcluster. Regardless of which source was used we store in the same data
    # in the cache

    # Once this push is older than a year update the revision
    # Once this push is older than 6 weeks the test will run slower because
    # all test tasks results will come from Taskcluster
    REV = "2fd61eb5c69ce9ac806048a35c7a7a88bf4b9652"  # Push from Apr. 21, 2020.
    BRANCH = "mozilla-central"
    PUSH_UUID = "{}/{}".format(BRANCH, REV)

    try:
        # Making sure there's nothing left in the cache
        if adr_config.cache.get(PUSH_UUID):
            adr_config.cache.forget(PUSH_UUID)
        assert adr_config.cache.get(PUSH_UUID) is None
        # Only use pushes older than 6 weeks (AD's unittest retention data)
        push = Push(REV, branch=BRANCH)
        # Q: Calling push.tasks a second time would hit the cache; Should we test that scenario?
        tasks = push.tasks
        assert len(tasks) > 0
        push_task_map = adr_config.cache.get(PUSH_UUID, {})
        TOTAL_TEST_TASKS = 3126
        # Testing that the tasks associated to a push have been cached
        assert len(push_task_map.keys()) == TOTAL_TEST_TASKS

        cached_test_tasks = 0
        for t in tasks:
            if not isinstance(t, TestTask):
                assert push_task_map.get(t.id) is None

            # Assert all test tasks have written to the cache
            if isinstance(t, TestTask):
                # if t.id == "LXHGVzvqR8KfMCfJW4ZiEQ":
                #     import pdb; pdb.set_trace()
                assert push_task_map[t.id]
                cached_test_tasks += 1

        assert cached_test_tasks == TOTAL_TEST_TASKS
    finally:
        # Make sure we forget the cached data
        adr_config.cache.forget(PUSH_UUID)
