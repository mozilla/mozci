# -*- coding: utf-8 -*-
import os
import shutil

import pytest

from mozci import config
from mozci.push import Push, make_push_objects

here = os.path.abspath(os.path.dirname(__file__))
pytestmark = pytest.mark.skipif(
    os.environ.get("TRAVIS_EVENT_TYPE") != "cron", reason="Not run by a cron task"
)


@pytest.fixture(autouse=True)
def set_config_path(monkeypatch):
    monkeypatch.setenv("MOZCI_CONFIG_PATH", os.path.join(here, "config.toml"))


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


def test_create_pushes_and_get_regressions():
    """
    An integration test mimicking the mozci usage done by bugbug.
    """
    pushes = make_push_objects(
        from_date="today-7day",
        to_date="today-6day",
        branch="autoland",
    )

    assert len(pushes) > 0

    push = pushes[round(len(pushes) / 2)]

    assert len(push.task_labels) > 0
    assert len(push.group_summaries) > 0

    push.get_possible_regressions("label")
    push.get_possible_regressions("group")

    push.get_likely_regressions("label")
    push.get_likely_regressions("group")


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
    TASKS_KEY = "{}/{}/tasks".format(BRANCH, REV)

    # Making sure there's nothing left in the cache
    if cache.get(TASKS_KEY):
        cache.forget(TASKS_KEY)
    assert cache.get(TASKS_KEY) is None

    push = Push(REV, branch=BRANCH)
    # Q: Calling push.tasks a second time would hit the cache; Should we test that scenario?
    assert len(push.tasks) > 0
    cached_tasks = cache.get(TASKS_KEY)
    assert cached_tasks is not None
    TOTAL_TEST_TASKS = 3517
    # Testing that the tasks associated to a push have been cached
    assert len(cached_tasks) == TOTAL_TEST_TASKS
    assert len(cached_tasks) == len(push.tasks)
    assert cached_tasks == push.tasks
