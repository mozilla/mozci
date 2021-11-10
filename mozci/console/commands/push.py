# -*- coding: utf-8 -*-
import datetime
import json
import os

from cleo import Command
from tabulate import tabulate

from mozci.push import Push, make_push_objects


class PushTasksCommand(Command):
    """
    List the tasks that ran on a push.

    tasks
        {rev : Head revision of the push.}
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
    Display the classification for a given push (or a range of pushes) as GOOD, BAD or UNKNOWN.

    classify
        {branch=mozilla-central : Branch the push belongs to (e.g autoland, try, etc).}
        {--rev= : Head revision of the push.}
        {--from-date= : Lower bound of the push range (as a date in yyyy-mm-dd format).}
        {--to-date= : Upper bound of the push range (as a date in yyyy-mm-dd format).}
        {--medium-confidence=0.8 : Medium confidence threshold used to classify the regressions.}
        {--high-confidence=0.9 : High confidence threshold used to classify the regressions.}
        {--output= : Path towards a directory to save a JSON file containing classification and regressions details in.}
        {--show-intermittents : If set, print tasks that should be marked as intermittent.}
    """

    def handle(self):
        branch = self.argument("branch")
        from_date = self.option("from-date")
        to_date = self.option("to-date")

        if not (bool(self.option("rev")) ^ bool(from_date or to_date)):
            self.line(
                "<error>You must either provide a single push revision with --rev or define --from-date AND --to-date options to classify a range of pushes.</error>"
            )
            return

        if self.option("rev"):
            pushes = [Push(self.option("rev"), branch)]
        else:
            if not from_date or not to_date:
                self.line(
                    "<error>You must provide --from-date AND --to-date options to classify a range of pushes.</error>"
                )
                return

            try:
                datetime.datetime.strptime(from_date, "%Y-%m-%d")
            except ValueError:
                self.line(
                    "<error>Provided --from-date should be a date in yyyy-mm-dd format.</error>"
                )
                return

            try:
                datetime.datetime.strptime(to_date, "%Y-%m-%d")
            except ValueError:
                self.line(
                    "<error>Provided --to-date should be a date in yyyy-mm-dd format.</error>"
                )
                return

            pushes = make_push_objects(
                from_date=from_date, to_date=to_date, branch=branch
            )

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
            os.makedirs(output)
            self.line(
                "<comment>Provided --output pointed to a inexistent directory that is now created.</comment>"
            )

        for push in pushes:
            try:
                classification, regressions = push.classify(
                    confidence_medium=medium_conf, confidence_high=high_conf
                )
                self.line(
                    f"Push associated with the head revision {push.rev} on "
                    f"the branch {branch} is classified as {classification.name}"
                )
            except Exception as e:
                self.line(
                    f"<error>Couldn't classify push {push.push_uuid}: {e}.</error>"
                )
                continue

            if self.option("show-intermittents"):
                self.line("-" * 50)
                self.line(
                    "Printing tasks that should be marked as intermittent failures:"
                )
                for task in regressions.intermittent:
                    self.line(task)
                self.line("-" * 50)

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

                filename = f"{output}/classify_output_{branch}_{push.rev}.json"
                with open(filename, "w") as file:
                    json.dump(to_save, file, indent=2)

                self.line(
                    f"Classification and regressions details for push {push.push_uuid} were saved in {filename} JSON file"
                )


class PushCommands(Command):
    """
    Contains commands that operate on a single push.

    push
    """

    commands = [PushTasksCommand(), ClassifyCommand()]

    def handle(self):
        return self.call("help", self._config.name)
