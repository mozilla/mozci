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
        if kwargs['kind'] == 'test':
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
        if isinstance(data, HTTPResponse):
            return data.read()
        return data


@dataclass
class TestTask(Task):
    groups: List = field(default_factory=list)


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
