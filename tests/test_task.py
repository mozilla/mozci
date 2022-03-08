# -*- coding: utf-8 -*-

import json
import re

import pytest

from mozci import config
from mozci.errors import ArtifactNotFound, TaskNotFound
from mozci.task import GroupResult, GroupSummary, Task, is_autoclassifiable
from mozci.util.taskcluster import get_artifact_url, get_index_url

GR_2 = GroupResult(group="group2", ok=True, duration=42)
GR_3 = GroupResult(group="group2", ok=True, duration=42)


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

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/0",
        json={"payload": {}, "tags": {"retrigger": "true", "label": "test_retrigger"}},
        status=200,
    )

    create_new_task_url_matcher = re.compile(
        r"https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/*"
    )

    responses.add(responses.PUT, create_new_task_url_matcher, status=200)

    task = create_task(label="foobar")
    task.retrigger()

    # verify last call was to create a new task
    assert responses.calls[-1].request.method == "PUT"
    assert create_new_task_url_matcher.match(responses.calls[-1].request.url)


def test_retrigger_should_not_retrigger(responses, create_task):

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/0",
        json={
            "payload": {},
            "tags": {"retrigger": "false", "label": "test_dont_retrigger"},
        },
        status=200,
    )

    task = create_task(label="foobar")
    task.retrigger()

    # verify last call was not to create a new task
    assert not responses.calls[-1].request.method == "PUT"


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
            id=1, label="test-windows7-32/debug-reftest-gpu-e10s-1"
        ).configuration
        == "test-windows7-32/debug-*-gpu-e10s"
    )
    assert (
        Task.create(
            id=1, label="test-linux1804-64/debug-mochitest-plain-gpu-e10s"
        ).configuration
        == "test-linux1804-64/debug-*-e10s"
    )
    assert (
        Task.create(
            id=1,
            label="test-macosx1014-64-shippable/opt-web-platform-tests-wdspec-headless-e10s-1",
        ).configuration
        == "test-macosx1014-64-shippable/opt-*-headless-e10s"
    )
    assert (
        Task.create(
            id=1, label="test-linux1804-64-asan/opt-web-platform-tests-e10s-3"
        ).configuration
        == "test-linux1804-64-asan/opt-*-e10s"
    )
    assert (
        Task.create(
            id=1,
            label="test-linux1804-64-qr/debug-web-platform-tests-wdspec-fis-e10s-1",
        ).configuration
        == "test-linux1804-64-qr/debug-*-fis-e10s"
    )
    assert (
        Task.create(
            id=1,
            label="test-windows7-32-shippable/opt-firefox-ui-functional-remote-e10s",
        ).configuration
        == "test-windows7-32-shippable/opt-*-e10s"
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
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-macosx1015-64/opt-xpcshell-e10s-1",
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
                        _results=[
                            GroupResult(group="group1", ok=False, duration=42),
                            GR_2,
                            GR_3,
                        ],
                    ),
                    Task.create(
                        id=2,
                        label="test-macosx1015-64/opt-xpcshell-e10s-1",
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
    "enabled, filters, result",
    [
        # Disabled feature
        (False, [], False),
        (False, ["*"], False),
        (False, ["test-macosx*/opt-*"], False),
        (False, ["test-macosx1015-64/opt-xpcshell-e10s-something"], False),
        # Enabled feature
        (True, [], False),
        (True, ["*"], True),
        (True, ["test-macosx*/opt-*"], True),
        (True, ["test-macosx1015-64/opt-xpcshell-e10s-something"], True),
        # Multiple filters
        (True, ["*linux*/*", "test-mac*/*"], True),
        (True, ["*linux*/*", "*/opt-xpcshell-e10s-*"], True),
        (True, ["whatever/*", "test-macosx1015-64/opt-*-e10s-*"], True),
        # Invalid filters
        (
            True,
            [
                "test-macosx1015-64/another-*",
                "*-MacOsX-*",
                "test-macosx1234*/*",
                "*/*-suffix",
            ],
            False,
        ),
        # Support both wildcard and single character replacement
        (True, ["test-macosx1015-?4/opt-*"], True),
    ],
)
def test_autoclassify(enabled, filters, result):
    """Check autoclassification filtering algorithm"""

    # Update configuration
    config._config["autoclassification"]["enabled"] = enabled
    config._config["autoclassification"]["test-suite-names"] = filters

    # Configure task with static label
    task = Task.create(
        id="someId", label="test-macosx1015-64/opt-xpcshell-e10s-something"
    )
    assert is_autoclassifiable(task) is result
