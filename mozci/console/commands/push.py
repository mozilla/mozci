# -*- coding: utf-8 -*-
import csv
import datetime
import json
import os
import re
from typing import List

import taskcluster
from cleo import Command
from loguru import logger
from tabulate import tabulate

from mozci import config
from mozci.push import Push, PushStatus, make_push_objects
from mozci.task import Task
from mozci.util.taskcluster import (
    COMMUNITY_TASKCLUSTER_ROOT_URL,
    get_taskcluster_options,
)


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


def classify_commands_pushes(
    branch: str, from_date: str, to_date: str, rev: str
) -> List[Push]:
    if not (bool(rev) ^ bool(from_date or to_date)):
        raise Exception(
            "You must either provide a single push revision with --rev or define --from-date AND --to-date options to classify a range of pushes."
        )

    if rev:
        pushes = [Push(rev, branch)]
    else:
        if not from_date or not to_date:
            raise Exception(
                "You must provide --from-date AND --to-date options to classify a range of pushes."
            )

        try:
            datetime.datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            raise Exception(
                "Provided --from-date should be a date in yyyy-mm-dd format."
            )

        try:
            datetime.datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            raise Exception("Provided --to-date should be a date in yyyy-mm-dd format.")

        pushes = make_push_objects(from_date=from_date, to_date=to_date, branch=branch)

    return pushes


class ClassifyCommand(Command):
    """
    Display the classification for a given push (or a range of pushes) as GOOD, BAD or UNKNOWN.

    classify
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
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

        try:
            pushes = classify_commands_pushes(
                branch,
                self.option("from-date"),
                self.option("to-date"),
                self.option("rev"),
            )
        except Exception as error:
            self.line(f"<error>{error}</error>")
            return

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


class ClassifyEvalCommand(Command):
    """
    Evaluate the classification results for a given push (or a range of pushes) by comparing them with reality.

    classify-eval
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
        {--rev= : Head revision of the push.}
        {--from-date= : Lower bound of the push range (as a date in yyyy-mm-dd format).}
        {--to-date= : Upper bound of the push range (as a date in yyyy-mm-dd format).}
        {--medium-confidence= : If recalculate parameter is set, medium confidence threshold used to classify the regressions.}
        {--high-confidence= : If recalculate parameter is set, high confidence threshold used to classify the regressions.}
        {--recalculate : If set, recalculate the classification instead of fetching an artifact.}
    """

    def handle(self):
        branch = self.argument("branch")

        try:
            pushes = classify_commands_pushes(
                branch,
                self.option("from-date"),
                self.option("to-date"),
                self.option("rev"),
            )
        except Exception as error:
            self.line(f"<error>{error}</error>")
            return

        if self.option("recalculate"):
            try:
                medium_conf = (
                    float(self.option("medium-confidence"))
                    if self.option("medium-confidence")
                    else 0.8
                )
            except ValueError:
                self.line(
                    "<error>Provided --medium-confidence should be a float.</error>"
                )
                return
            try:
                high_conf = (
                    float(self.option("high-confidence"))
                    if self.option("high-confidence")
                    else 0.9
                )
            except ValueError:
                self.line(
                    "<error>Provided --high-confidence should be a float.</error>"
                )
                return
        elif self.option("medium-confidence") or self.option("high-confidence"):
            self.line(
                "<error>--recalculate isn't set, you shouldn't provide either --medium-confidence nor --high-confidence attributes.</error>"
            )
            return

        classification_failed = []
        bad_backedout_pushes = []
        bad_non_backedout_pushes = []
        good_backedout_pushes = []
        good_non_backedout_pushes = []
        unknown_backedout_pushes = []
        unknown_non_backedout_pushes = []
        for push in pushes:
            classification = None
            if self.option("recalculate"):
                try:
                    classification, _ = push.classify(
                        confidence_medium=medium_conf, confidence_high=high_conf
                    )
                except Exception:
                    classification_failed.append(push)
                    continue
            else:
                try:
                    index = f"project.mozci.classification.{branch}.revision.{push.rev}"
                    task = Task.create(
                        index=index, root_url=COMMUNITY_TASKCLUSTER_ROOT_URL
                    )

                    artifact = task.get_artifact(
                        "public/classification.json",
                        root_url=COMMUNITY_TASKCLUSTER_ROOT_URL,
                    )
                    classification = artifact["push"]["classification"]
                except Exception:
                    classification_failed.append(push)
                    continue

            if classification == PushStatus.BAD:
                if push.backedout:
                    bad_backedout_pushes.append(push)
                else:
                    bad_non_backedout_pushes.append(push)
            elif classification == PushStatus.GOOD:
                if push.backedout:
                    good_backedout_pushes.append(push)
                else:
                    good_non_backedout_pushes.append(push)
            else:
                if push.backedout:
                    unknown_backedout_pushes.append(push)
                else:
                    unknown_non_backedout_pushes.append(push)

        if classification_failed:
            self.line(
                f"<error>Failed to fetch or recalculate classification for {len(classification_failed)} out of {len(pushes)} pushes.</error>"
            )
        self.line(
            f"{len(bad_backedout_pushes)} out of {len(pushes)} pushes were backed-out by a sheriff and were classified as BAD."
        )
        self.line(
            f"{len(bad_non_backedout_pushes)} out of {len(pushes)} pushes weren't backed-out by a sheriff and were classified as BAD."
        )
        self.line(
            f"{len(good_backedout_pushes)} out of {len(pushes)} pushes were backed-out by a sheriff and were classified as GOOD."
        )
        self.line(
            f"{len(good_non_backedout_pushes)} out of {len(pushes)} pushes weren't backed-out by a sheriff and were classified as GOOD."
        )
        self.line(
            f"{len(unknown_backedout_pushes)} out of {len(pushes)} pushes were backed-out by a sheriff and were classified as UNKNOWN."
        )
        self.line(
            f"{len(unknown_non_backedout_pushes)} out of {len(pushes)} pushes weren't backed-out by a sheriff and were classified as UNKNOWN."
        )


class ClassifyPerfCommand(Command):
    """
    Generate a CSV file with performance stats for all classification tasks

    perf
        {--environment=testing : Environment to analyze (testing, production, ...)}
    """

    REGEX_ROUTE = re.compile(
        r"^index.project.mozci.classification.([\w\-]+).(revision|push).(\w+)$"
    )

    def handle(self):
        environment = self.option("environment")

        # Aggregate stats for completed tasks processed by the hook
        stats = [
            self.parse_task_status(task_status)
            for group_id in self.list_groups_from_hook(
                "project-mozci", f"decision-task-{environment}"
            )
            for task_status in self.list_classification_tasks(group_id)
        ]

        # Dump stats as CSV file
        with open("perfs.csv", "w") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=[
                    "branch",
                    "push",
                    "revision",
                    "task_id",
                    "created",
                    "time_taken",
                ],
            )
            writer.writeheader()
            writer.writerows(stats)

    def parse_routes(self, routes):
        """Find revision from task routes"""

        def _match(route):
            res = self.REGEX_ROUTE.search(route)
            if res:
                return res.groups()

        # Extract branch+name+value from the routes
        # and get 3 separated lists to check those values
        branches, keys, values = zip(*filter(None, map(_match, routes)))

        # We should only have one branch
        branches = set(branches)
        assert len(branches) == 1, f"Multiple branches detected: {branches}"

        # Output single branch, revision and push id
        data = dict(zip(keys, values))
        assert "revision" in data, "Missing revision route"
        assert "push" in data, "Missing push route"
        return branches.pop(), data["revision"], int(data["push"])

    def parse_task_status(self, task_status):
        def date(x):
            return datetime.datetime.strptime(x, "%Y-%m-%dT%H:%M:%S.%fZ")

        # Extract identification and time spent for each classification task
        out = {
            "task_id": task_status["status"]["taskId"],
            "created": task_status["task"]["created"],
            "time_taken": sum(
                (date(run["resolved"]) - date(run["started"])).total_seconds()
                for run in task_status["status"]["runs"]
                if run["state"] == "completed"
            ),
        }
        out["branch"], out["revision"], out["push"] = self.parse_routes(
            task_status["task"]["routes"]
        )
        return out

    def list_groups_from_hook(self, group_id, hook_id):
        hooks = taskcluster.Hooks(get_taskcluster_options())
        fires = hooks.listLastFires(group_id, hook_id)
        for fire in fires.get("lastFires", []):
            yield fire["taskId"]

    def list_classification_tasks(self, group_id):
        cache_key = f"perf/task_group/{group_id}"

        # Check cache
        tasks = config.cache.get(cache_key)
        if tasks is None:
            queue = taskcluster.Queue(get_taskcluster_options())
            tasks = queue.listTaskGroup(group_id).get("tasks", [])
        else:
            logger.debug("From cache", cache_key)

        for task_status in tasks:
            task_id = task_status["status"]["taskId"]

            # Skip decision task
            if task_id == group_id:
                continue

            # Only provide completed tasks
            if task_status["status"]["state"] != "completed":
                logger.debug(f"Skip not completed task {task_id}")
                continue

            yield task_status

        # Cache all tasks if all completed
        if all(t["status"]["state"] == "completed" for t in tasks):
            config.cache.add(cache_key, tasks, int(config["cache"]["retention"]))


class PushCommands(Command):
    """
    Contains commands that operate on a single push.

    push
    """

    commands = [
        PushTasksCommand(),
        ClassifyCommand(),
        ClassifyEvalCommand(),
        ClassifyPerfCommand(),
    ]

    def handle(self):
        return self.call("help", self._config.name)
