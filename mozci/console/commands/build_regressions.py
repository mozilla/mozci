# -*- coding: utf-8 -*-

from loguru import logger

from mozci.push import Push
from mozci.task import Task


def is_build_failure(task: Task) -> bool:
    """Returns whether a build task has failed."""
    return task.job_kind == "build" and task.result in (
        "busted",
        "exception",
        "failed",
    )


def should_retrigger_task(task: Task, previous_occurrences: int) -> bool:
    """Specific rules for retriggering build tasks"""
    if task.tier not in (1, 2):
        return False
    # For now only process new build failures
    if previous_occurrences > 0:
        return False
    return True


def check_build_regressions(push: Push) -> list[Task]:
    logger.info(f"Fetched {len(push.tasks)} tasks for push {push.id}.")

    # Try to identify a potential regressions from the failed build
    potential_regressions = push.get_regressions("label", historical_analysis=False)

    # Map labels to tasks again
    build_regressions = [
        (task, past_occurrences)
        for label, past_occurrences in potential_regressions.items()
        if (task := next((t for t in push.tasks if t.label == label), None))
        and is_build_failure(task)
    ]
    if not build_regressions:
        logger.info("No regression detected.")
        return []

    new_regressions = sum(occurrences > 0 for _, occurrences in build_regressions)
    logger.info(
        f"Detected {len(build_regressions)} build tasks that may contain a regression "
        f"({new_regressions} potentially introduced by this push)."
    )

    # Filter tasks by retrigger criteria
    return [
        task for task, count in build_regressions if should_retrigger_task(task, count)
    ]
