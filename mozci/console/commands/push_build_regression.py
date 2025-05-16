# -*- coding: utf-8 -*-

from loguru import logger

from mozci.console.commands.build_regressions import check_build_regressions
from mozci.console.commands.push import BasePushCommand


class RegressionCommand(BasePushCommand):
    name = "regression"
    description = (
        "Lists tasks with potential regression, that may introduce a build bustage"
    )

    def handle(self):
        for push in self.pushes:
            tasks_to_retrigger = check_build_regressions(push)
            if not tasks_to_retrigger:
                logger.info("No build task detected as potential regression")
                return
            logger.info(
                f"{len(tasks_to_retrigger)} tasks have been detected as potential regressions:"
            )
            for task in tasks_to_retrigger:
                logger.info(f" * {task.label} [{task.id}]")
