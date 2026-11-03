# -*- coding: utf-8 -*-
"""Attribution of failures to the pushes which caused them.

Sheriffs classify failures as 'fixed by commit', referencing the backout of the push
they consider the culprit. These classifications are sometimes wrong: an isolated
intermittent failure attributed to a nearby backout, or a failure attributed to the
backout of a neighbouring push. An AttributionAnalysis, created for a target push,
gathers the evidence about a failure and decides whether to retain its
classification or to consider it intermittent.

Push._iterate_failures applies these decisions, while keeping responsibility for the
traversal of the pushes and the bookkeeping of candidate regressions.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from loguru import logger

from mozci import data
from mozci.task import GroupSummary, LabelSummary, Task

if TYPE_CHECKING:
    from mozci.push import Push


def group_of(runnable_type: str, name: Any) -> Optional[str]:
    """The group of a runnable (None for labels)."""
    if runnable_type == "group":
        return name
    if runnable_type == "config_group":
        return name[1]
    return None


class Verdict(Enum):
    # The classifications of the failure are kept.
    RETAIN = "retain"
    # Its 'fixed by commit' classifications are considered intermittent.
    INTERMITTENT = "intermittent"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str = ""


RETAIN = Decision(Verdict.RETAIN)


class AttributionAnalysis:
    """Evidence about the failures attributed to a push, and decisions about them."""

    def __init__(self, push: "Push"):
        self.push = push

    # Evidence.

    def failure_lines(self, task: Task) -> List[Dict[str, Any]]:
        """The failure lines of a task, with their matching bugs (empty if
        unavailable)."""
        cache: Dict[str, List[Dict[str, Any]]] = self.__dict__.setdefault(
            "_failure_lines", {}
        )
        if task.id not in cache:
            try:
                lines = data.handler.get(
                    "test_task_failure_lines", task=task, branch=self.push.branch
                )
                assert isinstance(lines, list)
                cache[task.id] = lines
            except Exception as e:
                logger.debug(f"Failure lines of {task.id} unavailable: {e}")
                cache[task.id] = []
        return cache[task.id]

    # Decisions.

    def decide(
        self,
        runnable_type: str,
        name: Any,
        summary: Union[GroupSummary, LabelSummary],
        failure_push: "Push",
    ) -> Decision:
        """What to do with the classifications of a failure of a runnable on
        `failure_push` (no rule yet: they are retained)."""
        return RETAIN
