from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from adr.util.memoize import memoized_property


class Status(Enum):
    PASS = 0
    FAIL = 1
    INTERMITTENT = 2


@dataclass
class Task:
    """Contains information pertaining to a single task."""
    id: str
    label: str
    kind: str
    duration: int
    result: str
    classification: str
    tags: Dict = field(default_factory=dict)

    @staticmethod
    def create(**kwargs):
        if kwargs['kind'] == 'test':
            return TestTask(**kwargs)
        return Task(**kwargs)

    @property
    def failed(self):
        return self.result in ('busted', 'exception', 'testfailed')


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
