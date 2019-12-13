import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List
from urllib3.response import HTTPResponse

from adr.util import memoize, memoized_property

from mozci.util.taskcluster import (
    get_artifact,
    list_artifacts,
)


class Status(Enum):
    PASS = 0
    FAIL = 1
    INTERMITTENT = 2


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
class TestResult:
    """Contains information relating to a single test failure within a TestTask."""
    group: str
    test: str
    ok: bool


@dataclass
class TestTask(Task):
    """Subclass containing additional information only relevant to 'test' tasks."""
    _results: List[TestResult] = field(default=None)
    _errors: List = field(default=None)
    _groups: List = field(default=None)

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
                self._results.append(TestResult(
                    test=line['test'],
                    group=line.get('group'),
                    ok=line['status'] == line['expected'],
                ))

            elif line['action'] == 'log':
                self._errors.append(line['message'])

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
class LabelSummary:
    """Summarizes the overall state of a task label (across retriggers)."""
    label: str
    tasks: List[Task]

    def __post_init__(self):
        assert all(t.label == self.label for t in self.tasks)

    @property
    def classifications(self):
        return set(t.classification for t in self.tasks if t.failed)

    @property
    def results(self):
        return set(t.result for t in self.tasks)

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
