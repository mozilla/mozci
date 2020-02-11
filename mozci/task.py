import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List
from urllib3.response import HTTPResponse

from adr.util import memoize, memoized_property
from loguru import logger

from mozci.util.taskcluster import (
    get_artifact,
    list_artifacts,
)


class Status(Enum):
    PASS = 0
    FAIL = 1
    INTERMITTENT = 2


NO_GROUPS_SUITES = (
    "raptor",
    "talos",
    "awsy",
    "web-platform-tests",
    "gtest",
    "cppunit",
    "telemetry-tests",
    "firefox-ui-functional",
    "junit",
    "crashtest",
    "geckoview-reftest",
)


def is_no_groups_suite(label):
    return any(f'-{s}-' in label for s in NO_GROUPS_SUITES)


# We only want to warn about bad groups once.
bad_group_warned = False


def is_bad_group(task_id, group):
    global bad_group_warned

    bad_group = os.path.isabs(group) or group.startswith("file://") or group.startswith("Z:")

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
    tags: Dict = field(default_factory=dict)

    @staticmethod
    def create(**kwargs):
        if kwargs['label'].startswith('test-'):
            return TestTask(**kwargs)
        return Task(**kwargs)

    @property
    def failed(self):
        return self.result in ('busted', 'exception', 'testfailed')

    @memoized_property
    def artifacts(self):
        """List the artifacts that were uploaded by this task."""
        return [artifact['name'] for artifact in list_artifacts(self.id)]

    @memoize
    def get_artifact(self, path):
        """Downloads and returns the content of an artifact.

        Args:
            path (str): The path component of the artifact URL. This is usually
                        something like `public/file.txt`. The values listed by
                        the `Task.artifacts` property can be passed into this
                        function.

        Returns:
            Contents of the artifact.
        """
        data = get_artifact(self.id, path)
        if not isinstance(data, HTTPResponse):
            return data

        output = data.read()
        if isinstance(output, bytes):
            output = output.decode("utf-8")
        return output


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

        # XXX: Once bug 1613937 and bug 1613939 are fixed, we can remove the filtering
        # and slash replacing, and turn the warning on bad group names into an assertion.

        if self._groups is not None:
            self._groups = [
                group.replace("\\", "/")
                for group in self._groups
                if not is_bad_group(self.id, group)
            ]

        def update_group(result):
            result.group = result.group.replace("\\", "/")
            return result

        if self._results is not None:
            self._results = [
                update_group(result)
                for result in self._results
                if not is_bad_group(self.id, result.group)
            ]

    def _load_errorsummary(self):
        # This may clobber the values that were populated by ActiveData, but
        # since the artifact is already downloaded, parsed and we need to
        # iterate over it anyway.. It doesn't really hurt and simplifies some
        # logic. It also ensures we don't attempt to load the errorsummary more
        # than once.
        self._groups = []
        self._results = []
        self._errors = []

        try:
            path = [a for a in self.artifacts if a.endswith('errorsummary.log')][0]
        except IndexError:
            return

        lines = [json.loads(l) for l in self.get_artifact(path).splitlines()]
        for line in lines:
            if line['action'] == 'test_groups':
                self._groups = line["groups"]

            elif line['action'] == 'test_result':
                self._results.append(GroupResult(
                    group=line.get('group'),
                    ok=line['status'] == line['expected'],
                ))

            elif line['action'] == 'log':
                self._errors.append(line['message'])

        self.__post_init__()

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
    @abstractmethod
    def classifications(self):
        ...

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

    @property
    def classifications(self):
        return set(t.classification for t in self.tasks if t.failed)

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
        return set(t.classification for t in self.tasks if t.failed)

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
