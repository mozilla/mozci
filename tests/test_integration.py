# -*- coding: utf-8 -*-
import os
import shutil
from argparse import Namespace

import adr
import pytest
from adr.query import run_query

from mozci import config, task
from mozci.push import Push, make_push_objects
from mozci.task import TestTask

here = os.path.abspath(os.path.dirname(__file__))
pytestmark = pytest.mark.skipif(
    os.environ.get("TRAVIS_EVENT_TYPE") != "cron", reason="Not run by a cron task"
)

if not os.environ.get("MOZCI_CONFIG_PATH"):
    raise Exception("Set MOZCI_CONFIG_PATH to tests/config.toml")


@pytest.fixture
def cache():
    # The directory is defined in tests/config.toml
    # If you want to iterate fast on tests that use the cache you can temporarily
    # comment out the steps deleting the cache
    cache_path = "mozci_tests_cache"
    try:
        if os.path.isdir(cache_path):
            # Make sure we start from a clean slate
            shutil.rmtree(cache_path)
        yield config.cache
    finally:
        shutil.rmtree(cache_path)


@pytest.fixture(scope="module", autouse=True)
def load_source():
    adr.sources.load_source(here)


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
    Ensure all suites (except an ignorelist) are generating manifest information.
    """
    IGNORELIST = {
        "talos": None,
        "jittest": None,
        "geckoview-junit": None,
        "cppunittest": None,
        "default": 5,
    }

    result = run_query("test_missing_manifests", Namespace())

    missing = []

    for suite, count in result["data"]:
        allowed_missing = IGNORELIST.get(suite, IGNORELIST["default"])
        if allowed_missing is None:
            continue

        if count > allowed_missing:
            missing.append((suite, count))

    assert missing == []

    # Ensure the ignorelist doesn't contain more than necessary.
    unignorable = []
    found_suites = {suite: count for suite, count in result["data"]}
    for suite, allowed_missing in IGNORELIST.items():
        if suite == "default":
            continue

        allowed_missing = allowed_missing or IGNORELIST["default"]
        if suite not in found_suites or found_suites[suite] < allowed_missing:
            unignorable.append((suite, found_suites.get(suite)))

    assert unignorable == []


def test_missing_result_manifests():
    """
    Ensure unittest results from all manifest-based suites (except an ignorelist)
    have information on what manifest the result corresponds to.
    """
    IGNORELIST = {
        "marionette",
    }
    ALLOWED_MISSING = 70

    result = run_query("test_missing_result_manifests", Namespace())

    missing = []

    for suite, count in result["data"]:
        if suite not in IGNORELIST:
            if count > ALLOWED_MISSING:
                missing.append((suite, count))

    assert missing == []

    # Ensure the ignorelist doesn't contain more than necessary.
    unignorable = []
    found_suites = {suite: count for suite, count in result["data"]}
    for suite in IGNORELIST:
        if suite not in found_suites or found_suites[suite] < ALLOWED_MISSING:
            unignorable.append(suite)

    assert unignorable == []


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


def test_caching_of_push(cache):
    # A recent push will have almost no tasks in AD, few days later it will have
    # all data come from AD and after 6 weeks it will have no data there.
    # Results data for a task will either come via AD or through the errorsummary artifact
    # via Taskcluster. Regardless of which source was used we store in the same data
    # in the cache.

    # Once this push is older than a year update the revision
    # Once this push is older than 6 weeks the test will run slower because
    # all test tasks results will come from Taskcluster
    REV = "08c29f9d87799463cdf99ab81f08f62339b49328"  # Push from Jul. 23, 2020.
    BRANCH = "mozilla-central"
    PUSH_UUID = "{}/{}".format(BRANCH, REV)

    # Making sure there's nothing left in the cache
    if cache.get(PUSH_UUID):
        cache.forget(PUSH_UUID)
    assert cache.get(PUSH_UUID) is None

    push = Push(REV, branch=BRANCH)
    # Q: Calling push.tasks a second time would hit the cache; Should we test that scenario?
    tasks = push.tasks
    assert len(tasks) > 0
    push_task_map = cache.get(PUSH_UUID, {})
    TOTAL_TEST_TASKS = 3245
    # Testing that the tasks associated to a push have been cached
    assert len(push_task_map.keys()) == TOTAL_TEST_TASKS

    cached_test_tasks = 0
    for t in tasks:
        if not isinstance(t, TestTask):
            assert push_task_map.get(t.id) is None

        # Assert all test tasks have written to the cache
        if isinstance(t, TestTask):
            assert push_task_map[t.id]
            cached_test_tasks += 1

    assert cached_test_tasks == TOTAL_TEST_TASKS
