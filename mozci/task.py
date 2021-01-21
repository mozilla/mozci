# -*- coding: utf-8 -*-
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from inspect import signature
from statistics import median
from typing import Dict, List, Optional

import requests
from loguru import logger

from mozci.errors import ArtifactNotFound, TaskNotFound
from mozci.util.memoize import memoized_property
from mozci.util.taskcluster import find_task_id, get_artifact, list_artifacts


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
def get_configuration_from_label(label: str) -> str:
    # Remove the suite name.
    config = label
    for s in SUITES:
        if f"-{s}-" in config:
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

    @staticmethod
    def create(index=None, **kwargs):
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
                kwargs["id"] = find_task_id(index)
            except requests.exceptions.HTTPError as e:
                label = kwargs.get("label", "unknown label")
                raise TaskNotFound(id=index, label=label) from e

        if kwargs.get("label", "").startswith("test-"):
            return TestTask(**kwargs)
        return Task(**kwargs)

    @property
    def failed(self):
        return self.result in ("failed", "exception")

    @property
    def artifacts(self):
        """List the artifacts that were uploaded by this task."""
        return [artifact["name"] for artifact in list_artifacts(self.id)]

    def get_artifact(self, path):
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
            data = get_artifact(self.id, path)
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


@dataclass
class GroupResult:
    """Contains information relating to a single group failure within a TestTask."""

    group: str
    ok: bool


@dataclass
class TestTask(Task):
    """Subclass containing additional information only relevant to 'test' tasks."""

    _results: Optional[List[GroupResult]] = field(default=None)
    _errors: Optional[List] = field(default=None)

    @property
    def is_wpt(self):
        return any(
            s in self.label
            for s in {"web-platform-tests", "test-verify-wpt", "test-coverage-wpt"}
        )

    def __post_init__(self):
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

        if self._results is None:
            return

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

        # Ensure there are no groups with bad names.
        assert not any(is_bad_group(self.id, result.group) for result in self._results)

    def _load_errorsummary(self) -> None:
        # This may clobber the values that were populated by ActiveData, but
        # since the artifact is already downloaded, parsed and we need to
        # iterate over it anyway. It doesn't really hurt and simplifies some
        # logic. It also ensures we don't attempt to load the errorsummary more
        # than once.
        self._results = []
        self._errors = []

        # Make sure that we don't try to load errorsummary.log for suites which
        # don't support groups.
        assert not is_no_groups_suite(self.label)

        try:
            paths = [a for a in self.artifacts if a.endswith("errorsummary.log")]
        except IndexError:
            return

        groups = set()
        group_results = {}
        # TODO After April 1st 2021, switch to using group_result exclusively.
        old_style_group_results = {}

        lines = (
            json.loads(line)
            for path in paths
            for line in self.get_artifact(path).iter_lines(decode_unicode=True)
            if line
        )

        has_group_result = False
        has_crashed = False

        for line in lines:
            if line["action"] == "test_groups":
                groups |= set(line["groups"]) - {"default"}

            # TODO After April 1st 2021, switch to using group_result exclusively.
            elif not has_group_result and line["action"] == "test_result":
                group = line.get("group")
                if group == "default":
                    continue

                # The "OK" case should never happen given how errorsummary.log works, but
                # better to be safe than sorry.
                if line["expected"] == line["status"]:
                    if group not in old_style_group_results:
                        old_style_group_results[group] = "OK"
                else:
                    old_style_group_results[group] = "ERROR"

            elif line["action"] == "group_result":
                has_group_result = True

                group = line["group"]
                if group not in group_results or line["status"] != "OK":
                    group_results[group] = line["status"]

            elif line["action"] == "log":
                self._errors.append(line["message"])

            elif line["action"] == "crash":
                has_crashed = True

        if not has_group_result:
            group_results = old_style_group_results

        self._results = [
            GroupResult(group, result == "OK")
            for group, result in group_results.items()
            if result != "SKIP"
        ]

        # Assume all groups for which we have no results passed, unless we have 'group_result' lines
        # or the suite crashed.
        # TODO After April 1st 2021, we can remove this assumption altogether, as all errorsummary.log
        # files will have 'group_result' entries.
        if not has_group_result and not has_crashed and len(groups) > 0:
            self._results += [
                GroupResult(group, True)
                for group in groups
                if group not in group_results
            ]

        self.__post_init__()

    @property
    def groups(self):
        if self._results is None:
            self._load_errorsummary()
        return [result.group for result in self.results]

    @property
    def results(self):
        if self._results is None:
            self._load_errorsummary()
        return self._results

    @property
    def errors(self):
        if self._errors is None:
            self._load_errorsummary()
        return self._errors

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
            c == "intermittent" for c, n in self.classifications
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
    tasks: List[Task]
    _durations: Optional[List[float]] = field(default_factory=lambda: [0.0])

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
    def durations(self):
        return self._durations

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
