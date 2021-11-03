# -*- coding: utf-8 -*-

from cleo import Command
from tabulate import tabulate

from mozci.push import Push


class PushTasksCommand(Command):
    """
    List the tasks that ran on a push.

    tasks
    """

    def handle(self):
        push = Push(self.argument("rev"), self.argument("branch"))

        table = []
        for task in sorted(push.tasks, key=lambda t: t.label):
            table.append([task.label, task.result or "running"])

        self.line(tabulate(table, headers=["Label", "Result"]))


class PushCommands(Command):
    """
    Contains commands that operate on a single push.

    push
        {branch : Branch the push belongs to (e.g autoland, try, etc).}
        {rev : Head revision of the push.}
    """

    commands = [PushTasksCommand()]

    def handle(self):
        return self.call("help", self._config.name)
