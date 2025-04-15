# -*- coding: utf-8 -*-

from cleo.commands.command import Command
from cleo.helpers import argument
from loguru import logger

from mozci.push import Push


class RegressionCommand(Command):
    name = "regression"
    description = "Identify if a build bustage is a regression from a check-in"
    arguments = [
        argument("rev", description="Head revision of the push."),
    ]

    def handle(self):
        # Initiate push from its head revision, forcing autoland branch
        rev = self.argument("rev")
        push = Push(rev, branch="autoland")

        push = Push(rev, branch="autoland")
        logger.info(f"Fetched {len(push.tasks)} tasks")

        # Try to identify a potential regressions from the failed build
        regressions = push.get_regressions("label", build=True)

        # Debug
        table = self.table()
        table.set_headers(["Label", "Previous occurrences"])
        table.set_rows([(label, str(count)) for label, count in regressions.items()])
        table.render()
