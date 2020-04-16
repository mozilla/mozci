# -*- coding: utf-8 -*-
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from inspect import signature
from typing import Dict, List

import adr
import requests
from adr.util import memoized_property
from loguru import logger
from urllib3.response import HTTPResponse

from mozci.errors import ArtifactNotFound, TaskNotFound
from mozci.util.taskcluster import find_task_id, get_artifact, list_artifacts


class Status(Enum):
    PASS = 0
    FAIL = 1
    INTERMITTENT = 2


NO_GROUPS_SUITES = (
    "raptor",
    "talos",
    "awsy",
    "gtest",
    "cppunit",
    "telemetry-tests",
    "firefox-ui-functional",
    "junit",
)


def is_no_groups_suite(label):
    return any(f"-{s}-" in label for s in NO_GROUPS_SUITES)


# We only want to warn about bad groups once.
bad_group_warned = False


def is_bad_group(task_id, task_label, group):
    global bad_group_warned

    bad_group = group.startswith("file://") or group.startswith("Z:")

    # web-platform-tests manifests are currently absolute.
    if not any(
        sublabel not in task_label
        for sublabel in {"web-platform-tests", "test-verify-wpt"}
    ):
        bad_group |= os.path.isabs(group)

    if not bad_group_warned and (bad_group or "\\" in group):
        bad_group_warned = True
        logger.warning(f"Bad group name in task {task_id}: {group}")

    return bad_group


@dataclass
class Task:
    """Contains information pertaining to a single task."""

    id: str
    label: str = field(default=None)
    kind: str = field(default=None)
    duration: int = field(default=None)
    result: str = field(default=None)
    classification: str = field(default=None)
    classification_note: str = field(default=None)
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
        return self.result in ("busted", "exception", "testfailed")

    @memoized_property
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

        if not isinstance(data, HTTPResponse):
            return data

        output = data.read()
        if isinstance(output, bytes):
            output = output.decode("utf-8")
        return output

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

    _results: List[GroupResult] = field(default=None)
    _errors: List = field(default=None)
    _groups: List = field(default=None)

    def __post_init__(self):
        if is_no_groups_suite(self.label):
            assert self._groups is None, f"{self.label} should have no groups"
            self._groups = []

            assert self._errors is None, f"{self.label} should have no errors"
            self._errors = []

            assert self._results is None, f"{self.label} should have no results"
            self._results = []

        # XXX: A while after bug 1613937 and bug 1613939 have been fixed, we can
        # remove the filtering and slash replacing.

        if self._groups is not None:
            self._groups = [
                group.replace("\\", "/")
                for group in self._groups
                if not is_bad_group(self.id, self.label, group)
            ]

        def update_group(result):
            result.group = result.group.replace("\\", "/")
            return result

        if self._results is not None:
            self._results = [
                update_group(result)
                for result in self._results
                if not is_bad_group(self.id, self.label, result.group)
            ]

    def _load_errorsummary(self):
        # XXX: How or where should we invalidate the data?
        data = adr.config.cache.get(self.id)
        if data:
            self._errors = data["errors"]
            self._groups = data["groups"]
            self._results = data["results"]
            return None
        # This may clobber the values that were populated by ActiveData, but
        # since the artifact is already downloaded, parsed and we need to
        # iterate over it anyway. It doesn't really hurt and simplifies some
        # logic. It also ensures we don't attempt to load the errorsummary more
        # than once.
        self._groups = []
        self._results = []
        self._errors = []

        try:
            path = [a for a in self.artifacts if a.endswith("errorsummary.log")][0]
        except IndexError:
            return

        lines = [json.loads(l) for l in self.get_artifact(path).splitlines()]
        for line in lines:
            if line["action"] == "test_groups":
                self._groups = list(set(line["groups"]) - {"default"})

            elif line["action"] == "test_result":
                self._results.append(
                    GroupResult(
                        group=line.get("group"), ok=line["status"] == line["expected"],
                    )
                )

            elif line["action"] == "log":
                self._errors.append(line["message"])

        self.__post_init__()
        # Only store data if there's something to store
        if self._errors or self._groups or self._results:
            logger.debug("Storing {} in the cache".format(self.id))
            # cachy's put() overwrites the value in the cache; add() would only add if its empty
            adr.config.cache.put(
                self.id,
                {
                    "errors": self._errors,
                    "groups": self._groups,
                    "results": self._results,
                },
                adr.config["cache"]["retention"],
            )

    @property
    def groups(self):
        if self._groups is None:
            self._load_errorsummary()
        return self._groups

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


@dataclass
class RunnableSummary(ABC):
    @property
    def classifications(self):
        return [
            (t.classification, t.classification_note) for t in self.tasks if t.failed
        ]

    @property
    @abstractmethod
    def status(self):
        ...


@dataclass
class GroupSummary(RunnableSummary):
    """Summarizes the overall state of a group (across retriggers)."""

    name: str
    tasks: List[Task]

    def __post_init__(self):
        assert all(self.name in t.groups for t in self.tasks)

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
