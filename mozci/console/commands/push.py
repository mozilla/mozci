# -*- coding: utf-8 -*-

from cleo import Command
from tabulate import tabulate

from mozci.push import Push


class PushTasksCommand(Command):
    """
    List the tasks that ran on a push.

    tasks
        {branch : Branch the push belongs to (e.g autoland, try, etc).}
    """

    def handle(self):
        push = Push(self.argument("rev"), self.argument("branch"))

        table = []
        for task in sorted(push.tasks, key=lambda t: t.label):
            table.append([task.label, task.result or "running"])

        self.line(tabulate(table, headers=["Label", "Result"]))


class ClassifyCommand(Command):
    """
    Display the classification for a given push as GOOD, BAD or UNKNOWN.

    classify
        {branch=mozilla-central : Branch the push belongs to (e.g autoland, try, etc).}
    """

    def handle(self):
        push = Push(self.argument("rev"), self.argument("branch"))
        classification = push.classify()
        self.line(
            f'Push associated with the head revision {self.argument("rev")} on the branch '
            f'{self.argument("branch")} is classified as {classification.name}'
        )


class PushCommands(Command):
    """
    Contains commands that operate on a single push.

    push
        {rev : Head revision of the push.}
    """

    commands = [PushTasksCommand(), ClassifyCommand()]

    def handle(self):
        return self.call("help", self._config.name)
