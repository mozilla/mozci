# -*- coding: utf-8 -*-

from loguru import logger

from mozci.console.commands.push import BasePushCommand
from mozci.errors import ChildPushNotFound
from mozci.push import Push


class RegressionCommand(BasePushCommand):
    name = "regression"
    description = "Identify if a build bustage is a regression from a check-in"

    def handle_push(self, push: Push) -> None:
        # Initiate push from its head revision, forcing autoland branch
        rev = self.argument("rev")
        push = Push(rev, branch="autoland")

        try:
            push.child
        except ChildPushNotFound:
            pass
        else:
            logger.warning("Push {push.id} has a child push, skipping.")

        logger.info(f"Fetched {len(push.tasks)} tasks for push {push.id}.")

        # Try to identify a potential regressions from the failed build
        regressions = push.get_regressions("label", build=True)

        if not regressions:
            logger.info("No regression detected.")
            return

        logger.info("Detected {len(regressions)} tasks that can be regressions.")
        new_regressions = [
            label for label, prev_count in regressions.items() if prev_count == 0
        ]
        if new_regressions:
            logger.info("Tasks that looks like new regressions:")
            for label in new_regressions:
                logger.info(f" * {label}")

    def handle(self):
        for push in self.pushes:
            self.handle_push(push)
