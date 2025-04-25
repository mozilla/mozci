# -*- coding: utf-8 -*-

from loguru import logger

from mozci.console.commands.push import BasePushCommand
from mozci.push import Push
from mozci.task import Task


class RegressionCommand(BasePushCommand):
    name = "regression"
    description = "Identify if a build bustage is a regression from a check-in"

    def is_build_failure(self, task: Task) -> bool:
        """Returns whether a build task has failed."""
        return task.job_kind == "build" and task.result in (
            "busted",
            "exception",
            "failed",
        )

    def should_retrigger_task(self, task: Task, previous_occurrences: int) -> bool:
        """Specific rules for retriggering build tasks"""
        if task.tier not in (1, 2):
            return False
        # For now only process new build failures
        if previous_occurrences > 0:
            return False
        return True

    def handle_push(self, push: Push) -> None:
        logger.info(f"Fetched {len(push.tasks)} tasks for push {push.id}.")

        # Try to identify a potential regressions from the failed build
        potential_regressions = push.get_regressions("label")

        # Map labels to tasks again
        build_regressions = [
            (task, past_occurrences)
            for label, past_occurrences in potential_regressions.items()
            if (task := next((t for t in push.tasks if t.label == label), None))
            and self.is_build_failure(task)
        ]
        if not build_regressions:
            logger.info("No regression detected.")
            return

        new_regressions = sum(occurrences > 0 for _, occurrences in build_regressions)
        logger.info(
            f"Detected {len(build_regressions)} build tasks that may contain a regression "
            f"({new_regressions} potentially introduced by this push)."
        )

        # Filter tasks by retrigger criteria
        tasks_to_retrigger = [
            task
            for task, count in build_regressions
            if self.should_retrigger_task(task, count)
        ]
        if tasks_to_retrigger:
            logger.info(f"{len(tasks_to_retrigger)} tasks should be retrigerred:")
            for task in tasks_to_retrigger:
                logger.info(f" * {task.label} [{task.id}]")
                # TODO: Retrigger task and inspect the result

    def handle(self):
        for push in self.pushes:
            self.handle_push(push)
