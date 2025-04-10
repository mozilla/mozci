# -*- coding: utf-8 -*-

from cleo.commands.command import Command
from cleo.helpers import argument

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

        # List tasks that may lead to a regression
        potential_regressions = [
            task for task in push.tasks if task.is_potential_regression
        ]

        # Debug
        table = self.table()
        table.set_headers(["ID", "Label", "Result"])
        table.set_rows([(r.id, r.label, r.result) for r in potential_regressions])
        table.render()
