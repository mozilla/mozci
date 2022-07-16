# -*- coding: utf-8 -*-
from __future__ import annotations

import collections
import fnmatch
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from inspect import signature
from statistics import median
from typing import Dict, List, NewType, Optional, Tuple

import jsone
import requests
import taskcluster
from loguru import logger

from mozci import config, data
from mozci.errors import ArtifactNotFound, TaskNotFound
from mozci.util.defs import INTERMITTENT_CLASSES
from mozci.util.memoize import memoized_property
from mozci.util.taskcluster import (
    PRODUCTION_TASKCLUSTER_ROOT_URL,
    find_task_id,
    get_artifact,
    list_artifacts,
)


class Status(Enum):
    PASS = 0
    FAIL = 1
    INTERMITTENT = 2


SUITES = (
    "mochitest-plain-gpu",
    "mochitest-plain",
    "mochitest-chrome-gpu",
    "mochitest-chrome",
    "mochitest-devtools-chrome",
    "mochitest-browser-a11y",
    "mochitest-browser-chrome",
    "web-platform-tests-crashtest",
    "web-platform-tests-reftest",
    "web-platform-tests-wdspec",
    "web-platform-tests-print-reftest",
    "web-platform-tests",
    "mochitest-media",
    "mochitest-webgpu",
    "mochitest-webgl1-ext",
    "mochitest-webgl2-ext",
    "mochitest-webgl1-core",
    "mochitest-webgl2-core",
    "mochitest-remote",
    "mochitest-a11y",
    "xpcshell",
    "crashtest",
    "jsreftest",
    "reftest-no-accel",
    "gtest",
    "telemetry-tests-client",
    "browser-screenshots",
    "marionette-gpu",
    "marionette",
    "cppunit",
    "firefox-ui-functional-remote",
    "firefox-ui-functional-local",
    "reftest",
    "junit",
    "test-verify",
    "test-coverage",
    "jittest",
)


# We can stop relying on parsing the label when https://bugzilla.mozilla.org/show_bug.cgi?id=1632870 is fixed.
def get_suite_from_label(label: str) -> Optional[str]:
    for s in SUITES:
        if f"-{s}-" in label or label.endswith(f"-{s}"):
            return s

    return None


# We can stop relying on parsing the label when https://bugzilla.mozilla.org/show_bug.cgi?id=1632870 is fixed.
def get_configuration_from_label(label: str) -> str:
    # Remove the suite name.
    config = label
    for s in SUITES:
        if f"-{s}-" in config or label.endswith(f"-{s}"):
            config = config.replace(s, "*")

    # Remove the chunk number.
    parts = config.split("-")
    return "-".join(parts[:-1] if parts[-1].isdigit() else parts)


NO_GROUPS_SUITES = (
    "raptor",
    "talos",
    "awsy",
    "gtest",
    "cppunit",
    "telemetry-tests",
    "firefox-ui-functional",
    "junit",  # https://bugzilla.mozilla.org/show_bug.cgi?id=1617632
    "jittest",  # https://bugzilla.mozilla.org/show_bug.cgi?id=1617633
    "marionette",  # https://bugzilla.mozilla.org/show_bug.cgi?id=1636088
)


def is_no_groups_suite(label):
    return any(f"-{s}-" in label for s in NO_GROUPS_SUITES)


slash_group_warned = False


def is_bad_group(task_id: str, group: str) -> bool:
    bad_group = (
        not group.strip()
        or group.startswith("file://")
        or group.startswith("Z:")
        or os.path.isabs(group)
        or "\\" in group
    )

    if bad_group:
        logger.error(f"Bad group name in task {task_id}: '{group}'")

    return bad_group


def is_autoclassifiable(task: TestTask) -> bool:
    """Check a task is enabled for auto-classification
    by applying glob patterns from configuration
    """
    assert task.label, "Missing task label"

    if not config["autoclassification"]["enabled"]:
        return False

    allowed_values = set(failure_type.value for failure_type in FailureType)
    filtered_failure_types = config["autoclassification"]["failure-types"]
    assert isinstance(filtered_failure_types, list) and set(
        filtered_failure_types
    ).issubset(allowed_values), "Unsupported failure types in configuration"

    flat_failure_types = list(
        set(
            test_and_type
            for group in task.failure_types.values()
            for test_and_type in group
        )
    )

    return (
        any(
            fnmatch.fnmatch(task.label, pattern)
            for pattern in config["autoclassification"]["test-suite-names"]
        )
        and len(flat_failure_types) == 1
        and flat_failure_types[0][1].value in filtered_failure_types
    )


# Transform WPT group names to a full relative path in mozilla-central.
def wpt_workaround(group: str) -> str:
    # No need to transform empty groups (also, they will be filtered out
    # in a following step).
    if not group.strip():
        return group

    assert group.startswith("/"), f"Group {group} doesn't start with /"
    if group.startswith("/_mozilla/"):
        return "/".join(
            ["testing/web-platform/mozilla/tests", group[len("/_mozilla/") :]]
        )
    else:
        return "/".join(["testing/web-platform/tests", group[1:]])


@dataclass
class Task:
    """Contains information pertaining to a single task."""

    id: str
    label: Optional[str] = field(default=None)
    duration: Optional[int] = field(default=None)
    result: Optional[str] = field(default=None)
    state: Optional[str] = field(default=None)
    classification: Optional[str] = field(default="not classified")
    classification_note: Optional[str] = field(default=None)
    tags: Dict = field(default_factory=dict)
    tier: Optional[int] = field(default=None)

    @staticmethod
    def create(index=None, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL, **kwargs):
        """Factory method to create a new Task instance.

        One of ``index`` or ``id`` must be specified.

        Args:
            index (str): Taskcluster index path used to find the task id (optional).
            kwargs (dict): Arguments to forward to the :class:`~mozci.task.Task` constructor.

        Raises:
            :class:`~mozci.errors.TaskNotFound`: when the task identified by
                specified index or task id could not be found.
        """
        if index and "id" not in kwargs:
            try:
                kwargs["id"] = find_task_id(index, root_url=root_url)
            except requests.exceptions.HTTPError as e:
                label = kwargs.get("label", "unknown label")
                raise TaskNotFound(id=index, label=label) from e

        if kwargs.get("label", "").startswith("test-"):
            return TestTask(**kwargs)
        return Task(**kwargs)

    @property
    def is_backfill(self) -> bool:
        return self.tags.get("action", "") == "backfill-task"

    @property
    def is_retrigger(self) -> bool:
        return self.tags.get("action", "").startswith("retrigger-")

    @property
    def is_tests_grouped(self) -> bool:
        return self.tags.get("tests_grouped", "") == "1"

    @property
    def failed(self):
        return self.result in ("failed", "exception")

    @property
    def artifacts(self):
        """List the artifacts that were uploaded by this task."""
        return [artifact["name"] for artifact in list_artifacts(self.id)]

    def get_artifact(self, path, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
        """Downloads and returns the content of an artifact.

        Args:
            path (str): The path component of the artifact URL. This is usually
                        something like `public/file.txt`. The values listed by
                        the `Task.artifacts` property can be passed into this
                        function.

        Returns:
            Contents of the artifact.

        Raises:
            :class:`~mozci.errors.ArtifactNotFound`: When the requested
                artifact does not exist.
        """
        try:
            data = get_artifact(self.id, path, root_url=root_url)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise ArtifactNotFound(path, self.id, self.label) from e
            raise

        return data

    def to_json(self):
        """A JSON compatible representation of this Task in dictionary form.

        Only values passed in to the constructor will be included.

        Returns:
            dict: A JSON-compatible representation of the task.
        """
        sig = signature(self.__init__)
        return {k: v for k, v in self.__dict__.items() if k in sig.parameters}

    def _get_action(self, decision_task, action_name):
        actions = decision_task.get_artifact("public/actions.json")
        action = next(
            action for action in actions["actions"] if action["name"] == action_name
        )
        assert action["kind"] == "hook"
        return action

    def _trigger_action(self, action, payload):
        tc_firefox_ci_credentials = config.get("taskcluster_firefox_ci", {})
        client_id = tc_firefox_ci_credentials.get("client_id")
        access_token = tc_firefox_ci_credentials.get("access_token")
        assert (
            client_id and access_token
        ), "Missing Taskcluster Firefox CI credentials in mozci config secret"

        options = taskcluster.optionsFromEnvironment()
        options["rootUrl"] = PRODUCTION_TASKCLUSTER_ROOT_URL
        options["credentials"] = {
            "clientId": client_id,
            "accessToken": access_token,
        }
        hooks = taskcluster.Hooks(options)

        result = hooks.triggerHook(action["hookGroupId"], action["hookId"], payload)
        return result["status"]["taskId"]

    def retrigger(self, push, times=3):
        """This function implements ability to perform retriggers on tasks"""
        if self._should_retrigger() == "false":
            logger.info(
                "Not retriggering task '{}', task should not be retriggered".format(
                    self.tags.get("label")
                )
            )
            return None

        decision_task = push.decision_task
        retrigger_action = self._get_action(decision_task, "retrigger")

        hook_payload = jsone.render(
            retrigger_action["hookPayload"],
            context={
                "taskId": self.id,
                "taskGroupId": decision_task.id,
                "input": {"times": times},
            },
        )

        logger.info("Retriggering task '{}'".format(self.tags.get("label", "")))
        return self._trigger_action(retrigger_action, hook_payload)

    def _should_retrigger(self):
        """Return whether this task should be retriggered."""
        return self.tags.get("retrigger", "false")

    def backfill(self, push):
        """This function implements ability to perform backfills on tasks"""
        decision_task = push.decision_task
        backfill_action = self._get_action(decision_task, "backfill")

        hook_payload = jsone.render(
            backfill_action["hookPayload"],
            context={
                "taskId": self.id,
                "taskGroupId": decision_task.id,
                "input": {
                    "times": 5
                    if self.classification == "not classified"
                    or self.classification in INTERMITTENT_CLASSES
                    else 1
                },
            },
        )

        logger.info("Backfilling task '{}'".format(self.tags.get("label", "")))
        return self._trigger_action(backfill_action, hook_payload)


@dataclass
class GroupResult:
    """Contains information relating to a single group failure within a TestTask."""

    group: str
    ok: bool
    # TODO: 'Optional' can be removed once https://github.com/mozilla/mozci/issues/662 is fixed.
    duration: Optional[int]


class FailureType(Enum):
    TIMEOUT = "timeout"
    CRASH = "crash"
    GENERIC = "generic"


TestName = NewType("TestName", str)
GroupName = NewType("GroupName", str)


@dataclass
class TestTask(Task):
    """Subclass containing additional information only relevant to 'test' tasks."""

    _results: Optional[List[GroupResult]] = field(default=None)
    _errors: Optional[List] = field(default=None)
    _failure_types: Optional[
        Dict[GroupName, List[Tuple[TestName, FailureType]]]
    ] = field(default=None)

    @property
    def is_wpt(self):
        return any(
            s in self.label
            for s in {"web-platform-tests", "test-verify-wpt", "test-coverage-wpt"}
        )

    def retrieve_results(self, push):
        global slash_group_warned

        if is_no_groups_suite(self.label):
            assert (
                self._errors is None
            ), f"{self.id} : {self.label} should have no errors"
            self._errors = []

            assert (
                self._results is None
            ), f"{self.id} : {self.label} should have no results"
            self._results = []

            return

        if self.state == "completed":
            self._results = [
                GroupResult(group, result, duration)
                for group, (result, duration) in data.handler.get(
                    "test_task_groups", branch=push.branch, rev=push.rev, task=self
                ).items()
            ]
        else:
            self._results = []

        # Apply WPT workaround, needed at least until bug 1632546 is fixed.
        if self.is_wpt:
            # TODO: It can be removed a year after https://bugzilla.mozilla.org/show_bug.cgi?id=1688043 is fixed.
            # Filter out "/" groups.
            if not slash_group_warned and any(
                result.group == "/" for result in self._results
            ):
                slash_group_warned = True
                logger.warning(f"'/' group name in task {self.id}")

            self._results = [result for result in self._results if result.group != "/"]

            for result in self._results:
                result.group = wpt_workaround(result.group)

        # Filter out groups with bad names.
        # TODO: Figure out why we still have some groups with bad names.
        self._results = [
            result
            for result in self._results
            if not is_bad_group(self.id, result.group)
        ]

    @property
    def groups(self):
        return [result.group for result in self.results]

    @property
    def results(self):
        assert self._results is not None
        return self._results

    @property
    def errors(self):
        if self._errors is None:
            self._errors = data.handler.get("test_task_errors", task=self)
        return self._errors

    @property
    def failure_types(self):
        """
        Returns a dict mapping each failing group on this TestTask
        to a list of its failing test names and their FailureType.

        e.g:
        {"group/failing/on-this-task.ini": [
            ("group/failing/test-file-1.js", "timeout"),
            ("group/failing/test-file-2.js", "crash"),
        ]}
        """
        if self._failure_types is None:
            self._failure_types = data.handler.get(
                "test_task_failure_types", task_id=self.id
            )
        return self._failure_types

    @property
    def configuration(self) -> str:
        assert self.label is not None
        return get_configuration_from_label(self.label)


# Don't perform type checking because of https://github.com/python/mypy/issues/5374.
@dataclass  # type: ignore
class RunnableSummary(ABC):
    @property
    def is_intermittent(self):
        return self.status == Status.INTERMITTENT or any(
            c in INTERMITTENT_CLASSES for c, n in self.classifications
        )

    @property
    @abstractmethod
    def classifications(self):
        ...

    @property
    @abstractmethod
    def status(self):
        ...

    @property
    @abstractmethod
    def durations(self):
        ...

    @property
    @abstractmethod
    def total_duration(self):
        ...

    @property
    @abstractmethod
    def median_duration(self):
        ...


@dataclass
class GroupSummary(RunnableSummary):
    """Summarizes the overall state of a group (across retriggers)."""

    name: str
    tasks: List[TestTask]

    def __post_init__(self):
        # WPT names are not normalized relative to topsrcdir, so subsequent check
        # will fail unless normalized.
        if self.name.startswith("/"):
            self.name = wpt_workaround(self.name)
        assert all(self.name in t.groups for t in self.tasks)

    @property
    def classifications(self):
        return [
            (t.classification, t.classification_note)
            for t in self.tasks
            if t.failed
            and any(result.group == self.name and not result.ok for result in t.results)
        ]

    @property
    def durations(self) -> List[int]:
        data = []
        for task in self.tasks:
            for result in task.results:
                if result.group == self.name:
                    data.append(result.duration)
        return data

    @property
    def total_duration(self):
        return sum(self.durations)

    @property
    def median_duration(self):
        return median(self.durations)

    @memoized_property
    def status(self):
        overall_status_by_label = {}
        for task in self.tasks:
            for result in task.results:
                if result.group != self.name:
                    continue

                if not result.ok:
                    status = Status.FAIL
                else:
                    status = Status.PASS

                if task.label not in overall_status_by_label:
                    overall_status_by_label[task.label] = status
                elif status != overall_status_by_label[task.label]:
                    overall_status_by_label[task.label] = Status.INTERMITTENT

        # If the manifest failed intermittently at least in one task, we
        # consider it to be intermittent.
        if any(
            status == Status.INTERMITTENT for status in overall_status_by_label.values()
        ):
            return Status.INTERMITTENT

        # Otherwise, if the manifest failed at least once in any of the tasks,
        # we consider it as a failure.
        if any(status == Status.FAIL for status in overall_status_by_label.values()):
            return Status.FAIL

        # Otherwise, the manifest passed in all tasks, so we consider it a pass.
        return Status.PASS

    @memoized_property
    def failing_tasks(self):
        # List all tasks with some test results failing for that group
        return [
            task
            for task in self.tasks
            if any(
                not result.ok and result.group == self.name for result in task.results
            )
        ]

    def is_config_consistent_failure(self, minimum_count: int = 3) -> Optional[bool]:
        config_to_results = collections.defaultdict(list)
        for task in self.tasks:
            for result in task.results:
                if result.group == self.name:
                    config_to_results[task.configuration].append(result.ok)

        # If there is no config for which we have at least 'minimum_count' runs, return None (that is, unknown).
        if all(len(results) < minimum_count for results in config_to_results.values()):
            return None

        # Return True if there is at least one configuration for which we have only failures, False otherwise.
        return any(
            len(results) >= minimum_count and not any(results)
            for results in config_to_results.values()
        )

    def is_cross_config_failure(self, minimum_count: int = 2) -> Optional[bool]:
        states = [
            result.ok
            for task in self.tasks
            for result in task.results
            if result.group == self.name
        ]

        nb = len(states)
        nb_passed = sum(states)  # Number of True booleans in the states list
        nb_failed = nb - nb_passed

        # If the group run on fewer than 'minimum_count' tasks, we don't have enough information to tell.
        if nb < minimum_count:
            return None

        # A group is a cross config failure when it is failing in all tasks and not
        # only in some.
        return nb_failed > 0 and nb_passed == 0


@dataclass
class LabelSummary(RunnableSummary):
    """Summarizes the overall state of a task label (across retriggers)."""

    label: str
    tasks: List[Task]

    def __post_init__(self):
        assert all(t.label == self.label for t in self.tasks)

    @property
    def classifications(self):
        return [
            (t.classification, t.classification_note) for t in self.tasks if t.failed
        ]

    @property
    def durations(self):
        return [t.duration for t in self.tasks]

    @property
    def total_duration(self):
        return sum(self.durations)

    @property
    def median_duration(self):
        return median(self.durations)

    @memoized_property
    def status(self):
        overall_status = None
        for task in self.tasks:
            if task.failed:
                status = Status.FAIL
            else:
                status = Status.PASS

            if overall_status is None:
                overall_status = status
            elif status != overall_status:
                overall_status = Status.INTERMITTENT

        return overall_status
