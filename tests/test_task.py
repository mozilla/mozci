# -*- coding: utf-8 -*-

import copy
import json

import pytest
from responses import matchers
from taskcluster.exceptions import TaskclusterRestFailure

from mozci import config
from mozci.errors import ArtifactNotFound, TaskNotFound
from mozci.push import Push
from mozci.task import (
    FailureType,
    GroupResult,
    GroupSummary,
    Task,
    TestTask,
    get_test_variant,
    is_autoclassifiable,
)
from mozci.util.taskcluster import (
    PRODUCTION_TASKCLUSTER_ROOT_URL,
    get_artifact_url,
    get_index_url,
)

GR_2 = GroupResult(group="group2", ok=True, duration=42)
GR_3 = GroupResult(group="group2", ok=True, duration=42)

ACTIONS_ARTIFACT_EXTRACT = {
    "actions": [
        {
            "context": [{}],
            "description": "Given a task schedule it on previous pushes in the same project.",
            "extra": {"actionPerm": "backfill"},
            "hookGroupId": "project-gecko",
            "hookId": "in-tree-action-3-backfill/9ffde487f6",
            "hookPayload": {
                "decision": {
                    "action": {
                        "cb_name": "backfill",
                        "description": "Given a task schedule it on previous pushes in the same project.",
                        "name": "backfill",
                        "symbol": "Bk",
                        "taskGroupId": "cIysKHAiSBOhhHrvgKMo1w",
                        "title": "Backfill",
                    },
                    "push": {
                        "owner": "mozilla-taskcluster-maintenance@mozilla.com",
                        "pushlog_id": "163357",
                        "revision": "5f90901a36bb9735cef6dc7d746d06880a61226d",
                    },
                    "repository": {
                        "level": "3",
                        "project": "autoland",
                        "url": "https://hg.mozilla.org/integration/autoland",
                    },
                },
                "user": {
                    "input": {"$eval": "input"},
                    "taskGroupId": {"$eval": "taskGroupId"},
                    "taskId": {"$eval": "taskId"},
                },
            },
            "kind": "hook",
            "name": "backfill",
            "title": "Backfill",
        },
    ]
}

RETRIGGER_ACTIONS_ARTIFACT_EXTRACT = {
    "actions": [
        {
            "context": [{}],
            "description": "Create a clone of the task (retriggering decision, action, and cron tasks requires\nspecial scopes).",
            "extra": {"actionPerm": "generic"},
            "hookGroupId": "project-gecko",
            "hookId": "in-tree-action-3-generic/9ffde487f6",
            "hookPayload": {
                "decision": {
                    "action": {
                        "cb_name": "retrigger-decision",
                        "description": "Create a clone of the task (retriggering decision, action, and cron tasks requires\nspecial scopes).",
                        "name": "retrigger",
                        "symbol": "rt",
                        "taskGroupId": "cIysKHAiSBOhhHrvgKMo1w",
                        "title": "Retrigger",
                    },
                    "push": {
                        "owner": "mozilla-taskcluster-maintenance@mozilla.com",
                        "pushlog_id": "163357",
                        "revision": "5f90901a36bb9735cef6dc7d746d06880a61226d",
                    },
                    "repository": {
                        "level": "3",
                        "project": "autoland",
                        "url": "https://hg.mozilla.org/integration/autoland",
                    },
                },
                "user": {
                    "input": {"$eval": "input"},
                    "taskGroupId": {"$eval": "taskGroupId"},
                    "taskId": {"$eval": "taskId"},
                },
            },
            "kind": "hook",
            "name": "retrigger",
            "title": "Retrigger",
        },
    ]
}


class FakePush:
    def __init__(self, branch, rev):
        self.branch = branch
        self.rev = rev


@pytest.fixture
def create_task():
    id = 0

    def inner(**kwargs):
        nonlocal id
        task = Task.create(id=id, **kwargs)
        id += 1
        return task

    return inner


def test_missing_artifacts(responses, create_task):
    artifact = "public/artifact.txt"
    task = create_task(label="foobar")

    responses.add(
        responses.GET,
        get_artifact_url(task.id, artifact),
        status=404,
    )

    with pytest.raises(ArtifactNotFound):
        task.get_artifact(artifact)


def test_create(responses):
    # Creating a task with just a label doesn't work.
    with pytest.raises(TypeError):
        Task.create(label="foobar")

    # Specifying an id works with or without label.
    assert Task.create(id=1, label="foobar").label == "foobar"
    assert Task.create(id=1).label is None

    # Can also specify an index.
    index = "index.path"
    responses.add(
        responses.GET,
        get_index_url(index),
        json={"taskId": 1},
        status=200,
    )
    assert Task.create(index=index, label="foobar").label == "foobar"
    assert Task.create(index=index).label is None

    # Specifying non-existent task index raises.
    responses.replace(responses.GET, get_index_url(index), status=404)
    with pytest.raises(TaskNotFound):
        Task.create(index=index)


def test_retrigger_should_retrigger(responses, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    decision_task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(
        responses.GET, decision_task_url, status=200, json={"taskId": "a" * 10}
    )

    responses.add(
        responses.GET,
        get_artifact_url(push.decision_task.id, "public/actions.json"),
        status=200,
        json=RETRIGGER_ACTIONS_ARTIFACT_EXTRACT,
    )

    config._config["taskcluster_firefox_ci"] = {
        "client_id": "a client id",
        "access_token": "an access token",
    }

    task = create_task(label="foobar", tags={"retrigger": "true"})

    hookGroupId = RETRIGGER_ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookGroupId"]
    hookId = RETRIGGER_ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookId"].replace(
        "/", "%2F"
    )
    hookPayload = copy.deepcopy(
        RETRIGGER_ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookPayload"]
    )
    hookPayload["user"] = {
        "input": {"times": 3},
        "taskGroupId": push.decision_task.id,
        "taskId": task.id,
    }
    responses.add(
        responses.POST,
        f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/hooks/v1/hooks/{hookGroupId}/{hookId}/trigger",
        status=200,
        json={"status": {"taskId": "new-retrigger-task"}},
        match=[matchers.json_params_matcher(hookPayload)],
    )

    assert task.retrigger(push) == "new-retrigger-task"


def test_retrigger_should_not_retrigger(responses, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    task = create_task(label="foobar")
    task.retrigger(push)


def test_backfill_missing_actions_artifact(responses, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    decision_task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(
        responses.GET, decision_task_url, status=200, json={"taskId": "a" * 10}
    )

    responses.add(
        responses.GET,
        get_artifact_url(push.decision_task.id, "public/actions.json"),
        status=404,
    )

    task = create_task(label="foobar")
    with pytest.raises(ArtifactNotFound):
        task.backfill(push)


def test_backfill_wrong_action_kind(responses, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)
    decision_task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(
        responses.GET, decision_task_url, status=200, json={"taskId": "a" * 10}
    )

    invalid_actions = copy.deepcopy(ACTIONS_ARTIFACT_EXTRACT)
    invalid_actions["actions"][0]["kind"] = "not a hook"
    responses.add(
        responses.GET,
        get_artifact_url(push.decision_task.id, "public/actions.json"),
        status=200,
        json=invalid_actions,
    )

    task = create_task(label="foobar")
    with pytest.raises(AssertionError):
        task.backfill(push)


@pytest.mark.parametrize(
    "secret_content",
    [{}, {"client_id": "a client id"}, {"access_token": "an access token"}],
)
def test_backfill_incomplete_secret(responses, secret_content, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)
    decision_task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(
        responses.GET, decision_task_url, status=200, json={"taskId": "a" * 10}
    )

    responses.add(
        responses.GET,
        get_artifact_url(push.decision_task.id, "public/actions.json"),
        status=200,
        json=ACTIONS_ARTIFACT_EXTRACT,
    )

    # Update configuration
    config._config["taskcluster_firefox_ci"] = secret_content

    task = create_task(label="foobar")
    with pytest.raises(
        AssertionError,
        match="Missing Taskcluster Firefox CI credentials in mozci config secret",
    ):
        task.backfill(push)


def test_backfill_trigger_hook_error(responses, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)
    decision_task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(
        responses.GET, decision_task_url, status=200, json={"taskId": "a" * 10}
    )

    responses.add(
        responses.GET,
        get_artifact_url(push.decision_task.id, "public/actions.json"),
        status=200,
        json=ACTIONS_ARTIFACT_EXTRACT,
    )

    config._config["taskcluster_firefox_ci"] = {
        "client_id": "a client id",
        "access_token": "an access token",
    }

    hookGroupId = ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookGroupId"]
    hookId = ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookId"].replace("/", "%2F")
    responses.add(
        responses.POST,
        f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/hooks/v1/hooks/{hookGroupId}/{hookId}/trigger",
        status=500,
    )

    task = create_task(label="foobar")
    with pytest.raises(TaskclusterRestFailure):
        task.backfill(push)


@pytest.mark.parametrize(
    "classification, times",
    [("not classified", 5), ("intermittent", 5), ("fixed by commit", 1)],
)
def test_backfill(responses, classification, times, create_task):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)
    decision_task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(
        responses.GET, decision_task_url, status=200, json={"taskId": "a" * 10}
    )

    responses.add(
        responses.GET,
        get_artifact_url(push.decision_task.id, "public/actions.json"),
        status=200,
        json=ACTIONS_ARTIFACT_EXTRACT,
    )

    config._config["taskcluster_firefox_ci"] = {
        "client_id": "a client id",
        "access_token": "an access token",
    }

    task = create_task(label="foobar")

    task.classification = classification

    hookGroupId = ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookGroupId"]
    hookId = ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookId"].replace("/", "%2F")
    hookPayload = copy.deepcopy(ACTIONS_ARTIFACT_EXTRACT["actions"][0]["hookPayload"])
    hookPayload["user"] = {
        "input": {"times": times},
        "taskGroupId": push.decision_task.id,
        "taskId": task.id,
    }
    responses.add(
        responses.POST,
        f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/hooks/v1/hooks/{hookGroupId}/{hookId}/trigger",
        status=200,
        json={"status": {"taskId": "new-backfill-task"}},
        match=[matchers.json_params_matcher(hookPayload)],
    )

    backfill_task_id = task.backfill(push)
    assert backfill_task_id == "new-backfill-task"


def test_to_json():
    kwargs = {
        "id": 1,
        "label": "foobar",
        "result": "pass",
        "duration": 100,
    }
    task = Task.create(**kwargs)
    result = task.to_json()
    json.dumps(result)  # assert doesn't raise

    for k, v in kwargs.items():
        assert k in result
        assert result[k] == v


def test_configuration():
    assert (
        Task.create(
            id=1,
            label="test-windows7-32/debug-reftest-gpu-nofis-1",
            suite="reftest-gpu",
            platform="windows7-32/debug",
            variant={"no-fission": True},
        ).configuration
        == "test-windows7-32/debug-*-nofis"
    )
    assert (
        Task.create(
            id=1,
            label="test-linux1804-64/debug-mochitest-plain-gpu",
            suite="mochitest-plain-gpu",
            platform="linux1804-64/debug",
        ).configuration
        == "test-linux1804-64/debug-*"
    )
    assert (
        Task.create(
            id=1,
            label="test-macosx1014-64-shippable/opt-web-platform-tests-wdspec-headless-nofis-1",
            suite="web-platform-tests-wdspec",
            platform="macosx1014-64-shippable/opt",
            variant={"no-fission": True, "headless": True},
        ).configuration
        == "test-macosx1014-64-shippable/opt-*-headless-nofis"
    )
    assert (
        Task.create(
            id=1,
            label="test-linux1804-64-asan/opt-web-platform-tests-3",
            suite="web-platform-tests",
            platform="linux1804-64-asan/opt",
        ).configuration
        == "test-linux1804-64-asan/opt-*"
    )
    assert (
        Task.create(
            id=1,
            label="test-linux1804-64-qr/debug-web-platform-tests-wdspec-fis-1proc-1",
            suite="web-platform-tests-wdspec",
            platform="linux1804-64-qr/debug",
            variant={"fission": True, "1proc": True},
        ).configuration
        == "test-linux1804-64-qr/debug-*-fis-1proc"
    )
    assert (
        Task.create(
            id=1,
            label="test-windows7-32-shippable/opt-firefox-ui-functional",
            suite="firefox-ui-functional",
            platform="windows7-32-shippable/opt",
        ).configuration
        == "test-windows7-32-shippable/opt-*"
    )


def test_GroupSummary_classifications():
    task1 = Task.create(
        id=1,
        label="test-task1",
        result="failed",
        classification="fixed by commit",
        classification_note="xxx",
    )
    task1._results = [GroupResult("group1", False, duration=42)]
    assert GroupSummary("group1", [task1]).classifications == [
        ("fixed by commit", "xxx")
    ]
    with pytest.raises(AssertionError):
        GroupSummary("group2", [task1])

    task1 = Task.create(
        id=1,
        label="test-task1",
        result="failed",
        classification="fixed by commit",
        classification_note="xxx",
    )
    task1._results = [
        GroupResult("group1", False, duration=42),
        GroupResult("group2", False, duration=42),
    ]
    assert GroupSummary("group1", [task1]).classifications == [
        ("fixed by commit", "xxx")
    ]
    assert GroupSummary("group2", [task1]).classifications == [
        ("fixed by commit", "xxx")
    ]

    task1 = Task.create(
        id=1, label="test-task1", result="failed", classification="intermittent"
    )
    task1._results = [
        GroupResult("group1", False, duration=42),
        GroupResult("group2", False, duration=42),
    ]
    assert GroupSummary("group1", [task1]).classifications == [("intermittent", None)]
    assert GroupSummary("group2", [task1]).classifications == [("intermittent", None)]

    task1 = Task.create(
        id=1,
        label="test-task1",
        result="failed",
        classification="fixed by commit",
        classification_note="xxx",
    )
    task1._results = [
        GroupResult("group1", True, duration=42),
        GroupResult("group2", False, duration=42),
    ]
    assert GroupSummary("group1", [task1]).classifications == []
    assert GroupSummary("group2", [task1]).classifications == [
        ("fixed by commit", "xxx")
    ]

    task1 = Task.create(
        id=1,
        label="test-task1",
        result="failed",
        classification="fixed by commit",
        classification_note="xxx",
    )
    task1._results = [
        GroupResult("group1", True, duration=42),
        GroupResult("group2", False, duration=42),
    ]
    task2 = Task.create(
        id=1, label="test-task1", result="failed", classification="intermittent"
    )
    task2._results = [
        GroupResult("group1", False, duration=42),
        GroupResult("group2", False, duration=42),
    ]
    assert GroupSummary("group1", [task1, task2]).classifications == [
        ("intermittent", None)
    ]
    assert GroupSummary("group2", [task1, task2]).classifications == [
        ("fixed by commit", "xxx"),
        ("intermittent", None),
    ]


def test_results_for_incomplete_task(responses):
    push = FakePush("autoland", "rev")

    for state in ["running", "pending", "unscheduled", "exception"]:
        task = Task.create(
            id=1,
            label="test-task",
            state="running",
        )
        task.retrieve_results(push)
        assert task.results == []

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/1/artifacts",
        json={
            "artifacts": [{"name": "errorsummary.log"}],
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/1/artifacts/errorsummary.log",
        body=r"""
            {"action": "test_groups", "line": 3, "groups": ["layout/base/tests/browser.ini"]}
            {"status": "OK", "duration": 12430, "line": 4465, "group": "layout/base/tests/browser.ini", "action": "group_result"}
        """.strip(),
        status=200,
    )

    task = Task.create(
        id=1,
        label="test-task",
        state="completed",
    )
    task.retrieve_results(push)
    assert task.results == [
        GroupResult(group="layout/base/tests/browser.ini", ok=True, duration=12430),
    ]


@pytest.mark.parametrize(
    "group_summary, expected_result",
    [
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-task1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                ],
            ),
            None,
        ),  # Only one task run and failed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-macosx1015-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-macosx1015-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                ],
            ),
            True,
        ),  # Multiple tasks with different configurations and single run for each
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-task{i}",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            True,
        ),  # All related tasks failed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-task{i}",
                        _results=[
                            GroupResult(
                                group="group1", ok=False if i % 2 else True, duration=42
                            ),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            False,
        ),  # Related tasks both failed and passed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-task{i}",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            False,
        ),  # All related tasks passed
    ],
)
def test_GroupSummary_is_cross_config_failure(group_summary, expected_result):
    assert group_summary.is_cross_config_failure(2) == expected_result


@pytest.mark.parametrize(
    "group_summary, expected_result",
    [
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                ],
            ),
            None,
        ),  # Only one task run and failed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-macosx1015-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-macosx1015-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                ],
            ),
            None,
        ),  # Multiple tasks with different configurations and single run for each
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            True,
        ),  # All related tasks failed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(
                                group="group1", ok=False if i % 2 else True, duration=42
                            ),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            False,
        ),  # Related tasks both failed and passed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            False,
        ),  # All related tasks passed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ]
                + [
                    Task.create(
                        id=i,
                        label=f"test-macosx1015-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-macosx1015-64/opt",
                        _results=[
                            GroupResult(
                                group="group1", ok=False if i % 2 else True, duration=42
                            ),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            True,
        ),  # All related tasks failed on a configuration and related tasks both failed and passed on another
    ],
)
def test_GroupSummary_is_config_consistent_failure(group_summary, expected_result):
    assert group_summary.is_config_consistent_failure(2) == expected_result


@pytest.mark.parametrize(
    "group_summary, expected_result",
    [
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                ],
            ),
            None,
        ),  # passing task, expected status none
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                ],
            ),
            None,
        ),  # failing task, expected status none
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[GroupResult(group="group1", ok=False, duration=42)],
                    ),
                ],
            ),
            True,
        ),  # failing task, failing confirm == verified fail (i.e. True)
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[GroupResult(group="group1", ok=True, duration=42)],
                    ),
                ],
            ),
            False,
        ),  # failing task, passing confirm == intermittent (i.e. False)
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GroupResult(group="group2", ok=False, duration=42),
                            GroupResult(group="group3", ok=True, duration=42),
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                        ],
                    ),
                    Task.create(
                        id=3,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                        ],
                    ),
                ],
            ),
            False,
        ),  # failing task, 2 different failures in group 1 confirms, both true; confirmed = False (i.e. intermittent)
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GroupResult(group="group2", ok=False, duration=42),
                            GroupResult(group="group3", ok=True, duration=42),
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                        ],
                    ),
                    Task.create(
                        id=3,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                        ],
                    ),
                ],
            ),
            True,
        ),  # failing task, 2 different failures in group 1 confirms, one true, one false; confirmed = True (i.e. regression)
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GroupResult(group="group2", ok=False, duration=42),
                            GroupResult(group="group3", ok=True, duration=42),
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                        ],
                    ),
                    Task.create(
                        id=3,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                        ],
                    ),
                ],
            ),
            True,
        ),  # failing task, 2 different failures in group 1 confirms, both false; confirmed = True (i.e. regression)
        (
            GroupSummary(
                "group2",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GroupResult(group="group2", ok=False, duration=42),
                            GroupResult(group="group3", ok=True, duration=42),
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group2", ok=False, duration=42),
                        ],
                    ),
                    Task.create(
                        id=3,
                        label="test-linux1804-64/opt-xpcshell-e10s-1-cf",
                        _results=[
                            GroupResult(group="group2", ok=True, duration=42),
                        ],
                    ),
                ],
            ),
            True,
        ),  # failing task, 2 different failures in group 2 confirms, both false; confirmed = True (i.e. regression)
    ],
)
def test_GroupSummary_is_confirmed_failure(group_summary, expected_result):
    assert group_summary.is_confirmed_failure() == expected_result


def test_GroupSummary_is_config_consistent_failure_single():
    group_summary = GroupSummary(
        "group1",
        [
            Task.create(
                id=1,
                label="test-linux1804-64/opt-xpcshell-e10s-1",
                suite="xpcshell",
                platform="test-linux1804-64/opt",
                _results=[
                    GroupResult(group="group1", ok=False, duration=42),
                    GR_2,
                    GR_3,
                ],
            )
        ],
    )
    assert group_summary.is_config_consistent_failure(1)


@pytest.mark.parametrize(
    "group_summary, expected_result",
    [
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                ],
            ),
            None,
        ),  # Only one task run and failed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-macosx1015-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-macosx1015-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                ],
            ),
            True,
        ),  # Multiple tasks with different configurations and single run for each
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=1,
                        label="test-linux1804-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-macosx1015-64/opt-xpcshell-e10s-1",
                        suite="xpcshell",
                        platform="test-macosx1015-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                ],
            ),
            False,
        ),  # Group fails on a configuration and passes on another
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            True,
        ),  # All related tasks failed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(
                                group="group1", ok=False if i % 2 else True, duration=42
                            ),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            False,
        ),  # Related tasks both failed and passed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=True, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            False,
        ),  # All related tasks passed
        (
            GroupSummary(
                "group1",
                [
                    Task.create(
                        id=i,
                        label=f"test-linux1804-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-linux1804-64/opt",
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ]
                + [
                    Task.create(
                        id=i,
                        label=f"test-macosx1015-64/opt-xpcshell-e10s-{i}",
                        suite="xpcshell",
                        platform="test-macosx1015-64/opt",
                        _results=[
                            GroupResult(
                                group="group1", ok=False if i % 2 else True, duration=42
                            ),
                            GR_2,
                            GR_3,
                        ],
                    )
                    for i in range(1, 11)
                ],
            ),
            True,
        ),  # All related tasks failed on a configuration and related tasks both failed and passed on another
    ],
)
def test_GroupSummary_is_consistent_failure(group_summary, expected_result):
    assert group_summary.is_consistent_failure(2, 2) == expected_result


@pytest.mark.parametrize(
    "autoclassification_config, expected_error, error_mesage",
    [
        ({}, KeyError, "'enabled'"),
        ({"enabled": True}, KeyError, "'failure-types'"),
        (
            {"enabled": True, "failure-types": ["crash"]},
            KeyError,
            "'test-suite-names'",
        ),
        (
            {"enabled": True, "test-suite-names": [], "failure-types": "not a list"},
            AssertionError,
            "Unsupported failure types in configuration",
        ),
        (
            {
                "enabled": True,
                "test-suite-names": [],
                "failure-types": ["unknown type"],
            },
            AssertionError,
            "Unsupported failure types in configuration",
        ),
    ],
)
def test_autoclassify_errors(autoclassification_config, expected_error, error_mesage):
    # Update configuration
    config._config["autoclassification"] = autoclassification_config

    # Assert that errors are properly raised when the configuration isn't well formatted
    task = TestTask.create(
        id="someId", label="test-macosx1015-64/opt-xpcshell-e10s-something"
    )
    task._failure_types = {}
    with pytest.raises(expected_error) as e:
        is_autoclassifiable(task)
    assert str(e.value) == error_mesage


ONE_FAILURE_TYPE_CRASH = {"group1": [("test1.js", FailureType.CRASH)]}
ONE_FAILURE_TYPE_TIMEOUT = {"group1": [("test1.js", FailureType.TIMEOUT)]}
ONE_FAILURE_TYPE_GENERIC = {"group1": [("test1.js", FailureType.GENERIC)]}
TWO_FAILURES_SAME_TEST_TYPE_GENERIC = {
    "group1": [("test1.js", FailureType.GENERIC), ("test1.js", FailureType.GENERIC)]
}
TWO_FAILURES_SAME_TEST_DIFFERENT_TYPE = {
    "group1": [("test1.js", FailureType.GENERIC), ("test1.js", FailureType.CRASH)]
}
MULTIPLE_FAILURE_TYPES = {
    "group1": [("test1.js", FailureType.CRASH), ("test2.js", FailureType.CRASH)],
    "group2": [("test1.js", FailureType.GENERIC), ("test2.js", FailureType.TIMEOUT)],
}


@pytest.mark.parametrize(
    "task_failure_types, enabled, test_suite_names, failure_types, result",
    [
        # Disabled feature
        (ONE_FAILURE_TYPE_CRASH, False, [], [], False),
        (ONE_FAILURE_TYPE_CRASH, False, ["*"], ["crash"], False),
        (ONE_FAILURE_TYPE_CRASH, False, ["test-macosx*/opt-*"], ["crash"], False),
        (
            ONE_FAILURE_TYPE_CRASH,
            False,
            ["test-macosx1015-64/opt-xpcshell-e10s-something"],
            ["crash"],
            False,
        ),
        # Enabled feature
        (ONE_FAILURE_TYPE_CRASH, True, [], ["crash"], False),
        (ONE_FAILURE_TYPE_CRASH, True, ["*"], ["crash"], True),
        (ONE_FAILURE_TYPE_CRASH, True, ["test-macosx*/opt-*"], ["crash"], True),
        (
            ONE_FAILURE_TYPE_CRASH,
            True,
            ["test-macosx1015-64/opt-xpcshell-e10s-something"],
            ["crash"],
            True,
        ),
        (ONE_FAILURE_TYPE_CRASH, True, ["*"], ["crash", "timeout", "generic"], True),
        (ONE_FAILURE_TYPE_TIMEOUT, True, ["*"], ["timeout"], True),
        (ONE_FAILURE_TYPE_TIMEOUT, True, ["*"], ["crash", "timeout", "generic"], True),
        (ONE_FAILURE_TYPE_GENERIC, True, ["*"], ["generic"], True),
        (ONE_FAILURE_TYPE_GENERIC, True, ["*"], ["crash", "timeout", "generic"], True),
        # Multiple names
        (ONE_FAILURE_TYPE_CRASH, True, ["*linux*/*", "test-mac*/*"], ["crash"], True),
        (
            ONE_FAILURE_TYPE_CRASH,
            True,
            ["*linux*/*", "*/opt-xpcshell-e10s-*"],
            ["crash"],
            True,
        ),
        (
            ONE_FAILURE_TYPE_CRASH,
            True,
            ["whatever/*", "test-macosx1015-64/opt-*-e10s-*"],
            ["crash"],
            True,
        ),
        # Invalid names
        (
            ONE_FAILURE_TYPE_CRASH,
            True,
            [
                "test-macosx1015-64/another-*",
                "*-MacOsX-*",
                "test-macosx1234*/*",
                "*/*-suffix",
            ],
            ["crash"],
            False,
        ),
        # Support both wildcard and single character replacement
        (ONE_FAILURE_TYPE_CRASH, True, ["test-macosx1015-?4/opt-*"], ["crash"], True),
        # Invalid combination for failure types
        (ONE_FAILURE_TYPE_CRASH, True, ["*"], ["timeout", "generic"], False),
        (ONE_FAILURE_TYPE_TIMEOUT, True, ["*"], ["crash", "generic"], False),
        (ONE_FAILURE_TYPE_GENERIC, True, ["*"], ["crash", "timeout"], False),
        ({}, True, ["*"], ["crash"], False),
        (MULTIPLE_FAILURE_TYPES, True, ["*"], ["crash"], False),
        # Two generic failures in the same test.
        (TWO_FAILURES_SAME_TEST_TYPE_GENERIC, True, ["*"], ["generic"], True),
        # A generic failure and a crash in the same test.
        (TWO_FAILURES_SAME_TEST_DIFFERENT_TYPE, True, ["*"], ["generic"], False),
        (TWO_FAILURES_SAME_TEST_DIFFERENT_TYPE, True, ["*"], ["crash"], False),
        (
            TWO_FAILURES_SAME_TEST_DIFFERENT_TYPE,
            True,
            ["*"],
            ["generic", "crash"],
            False,
        ),
    ],
)
def test_autoclassify(
    task_failure_types, enabled, test_suite_names, failure_types, result
):
    """Check autoclassification filtering algorithm"""

    # Update configuration
    config._config["autoclassification"]["enabled"] = enabled
    config._config["autoclassification"]["test-suite-names"] = test_suite_names
    config._config["autoclassification"]["failure-types"] = failure_types

    # Configure task with static label
    task = TestTask.create(
        id="someId", label="test-macosx1015-64/opt-xpcshell-e10s-something"
    )
    task._failure_types = task_failure_types
    assert is_autoclassifiable(task) is result


# TODO: mock the variants.yml stuff
@pytest.mark.parametrize(
    "task, suite, platform, variant, configuration",
    [
        (
            Task.create(
                id=1,
                label="test-macosx1015-64/opt-mochitest-plain-e10s-swr-2",
                suite="mochitest-plain",
                platform="macosx1015-64-qr/opt",
                variant={"webrender-sw": True},
                _results=[GR_2],
            ),
            "mochitest-plain",
            "macosx1015-64-qr/opt",
            "swr",
            "test-macosx1015-64-qr/opt-*-swr",
        ),
        (
            Task.create(
                id=1,
                label="test-macosx1015-64/opt-mochitest-plain-e10s-swr-nofis-2",
                suite="mochitest-plain",
                platform="macosx1015-64-qr/opt",
                variant={"no-fission": True, "webrender-sw": True},
                _results=[GR_2],
            ),
            "mochitest-plain",
            "macosx1015-64-qr/opt",
            "swr-nofis",
            "test-macosx1015-64-qr/opt-*-swr-nofis",
        ),
        (  # test out android platform change, as well as cppunit
            Task.create(
                id=1,
                label="test-android-em-7-0-x86_64-qr/debug-geckoview-cppunit-1proc",
                suite="cppunittest",
                platform="android-em-7-0-x86_64-qr/debug",
                variant={"1proc": True},
                _results=[GR_2],
            ),
            "cppunittest",
            "android-em-7-0-x86_64-qr/debug",
            "1proc",
            "test-android-em-7.0-x86_64-qr/debug-geckoview-*-1proc",
        ),
        (  # test out android platform change, as well as cppunit
            Task.create(
                id=1,
                label="test-macosx1015-64/opt-web-platform-tests-privatebrowsing-e10s-swr-2",
                suite="web-platform-tests",
                platform="macosx1015-64/opt",
                variant={"webrender-sw": True},
                _results=[GR_2],
            ),
            "web-platform-tests",
            "macosx1015-64/opt",
            "swr",
            "test-macosx1015-64/opt-*-privatebrowsing-swr",
        ),
        (  # test out android platform change, as well as cppunit
            Task.create(
                id=1,
                label="test-macosx1015-64/opt-xpcshell-msix-2",
                suite="xpcshell",
                platform="macosx1015-64/opt",
                variant={"msix": True},
                _results=[GR_2],
            ),
            "xpcshell",
            "macosx1015-64/opt",
            "msix",
            "test-macosx1015-64/opt-*-msix",
        ),
    ],
)
def test_get_configuration(task, suite, platform, variant, configuration):
    assert task.suite == suite
    assert task.platform == platform
    assert get_test_variant(task.variant, task.label) == variant
    assert task.configuration == configuration
