# -*- coding: utf-8 -*-

from loguru import logger

from mozci.console.commands.push import BasePushCommand
from mozci.errors import ChildPushNotFound
from mozci.push import Push
from mozci.task import Task


class RegressionCommand(BasePushCommand):
    name = "regression"
    description = "Identify if a build bustage is a regression from a check-in"

    def should_retrigger_task(self, task: Task, previous_occurrences: int) -> bool:
        """Specific rules for retriggering build tasks"""
        if task.tier not in (1, 2):
            return False
        # For now only process new build failures
        if previous_occurrences > 0:
            return False
        return True

    def handle_push(self, push: Push) -> None:
        # Initiate push from its head revision, forcing autoland branch
        try:
            push.child
        except ChildPushNotFound:
            pass
        else:
            logger.warning(f"Push {push.id} has a child push, skipping.")
            return

        logger.info(f"Fetched {len(push.tasks)} tasks for push {push.id}.")

        # Try to identify a potential regressions from the failed build
        build_regressions = push.get_regressions("label", build_only=True)

        if not build_regressions:
            logger.info("No regression detected.")
            return

        new_regressions = sum(
            1 for _label, prev_count in build_regressions.items() if prev_count == 0
        )
        logger.info(
            f"Detected {len(build_regressions)} build tasks that may contain a regression. "
            f"({new_regressions} potentially introduced by this push)."
        )

        # Map labels to tasks again and filter by new + retrigger criteria
        tasks_to_retrigger = [
            task
            for label, count in build_regressions.items()
            if self.should_retrigger_task(
                task := next(t for t in push.tasks if t.label == label),
                count,
            )
        ]

        if tasks_to_retrigger:
            logger.info(f"{len(tasks_to_retrigger)} tasks should be retrigerred:")
            for task in tasks_to_retrigger:
                logger.info(f" * {task.label} [{task.id}]")
                # TODO: Retrigger task and inspect the result

    def handle(self):
        for push in self.pushes:
            self.handle_push(push)
