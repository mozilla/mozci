# -*- coding: utf-8 -*-
import json
import os

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
        {--medium-confidence=0.8 : Medium confidence threshold used to classify the regressions.}
        {--high-confidence=0.9 : High confidence threshold used to classify the regressions.}
        {--output= : Path towards a directory to save a JSON file containing classification and regressions details in.}
    """

    def handle(self):
        try:
            medium_conf = float(self.option("medium-confidence"))
        except ValueError:
            self.line("<error>Provided --medium-confidence should be a float.</error>")
            return
        try:
            high_conf = float(self.option("high-confidence"))
        except ValueError:
            self.line("<error>Provided --high-confidence should be a float.</error>")
            return

        output = self.option("output")
        if output and not os.path.isdir(output):
            self.line(
                "<error>Provided --output should be a valid path towards a writable directory.</error>"
            )
            return

        push = Push(self.argument("rev"), self.argument("branch"))
        classification, regressions = push.classify(
            confidence_medium=medium_conf,
            confidence_high=high_conf,
            output_regressions=True if output else False,
        )
        self.line(
            f'Push associated with the head revision {self.argument("rev")} on the branch '
            f'{self.argument("branch")} is classified as {classification.name}'
        )

        if output:
            to_save = {
                "push": {
                    "id": push.push_uuid,
                    "classification": classification.name,
                },
                "failures": {
                    "real": {
                        group: [
                            {"task_id": task.id, "label": task.label}
                            for task in failing_tasks
                        ]
                        for group, failing_tasks in regressions.real.items()
                    },
                    "intermittent": {
                        group: [
                            {"task_id": task.id, "label": task.label}
                            for task in failing_tasks
                        ]
                        for group, failing_tasks in regressions.intermittent.items()
                    },
                    "unknown": {
                        group: [
                            {"task_id": task.id, "label": task.label}
                            for task in failing_tasks
                        ]
                        for group, failing_tasks in regressions.unknown.items()
                    },
                },
            }

            filename = f"{output}/classify_output.json"
            with open(filename, "w") as file:
                json.dump(to_save, file, indent=2)

            self.line(
                f"Classification and regressions details were saved in {filename} JSON file"
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
