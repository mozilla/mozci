# -*- coding: utf-8 -*-
import os
from collections import namedtuple
from itertools import groupby

import requests
from cleo import Command
from loguru import logger

from mozci import config
from mozci.push import make_push_objects
from mozci.util.taskcluster import (
    COMMUNITY_TASKCLUSTER_ROOT_URL,
    find_task_id,
    index_current_task,
    list_dependent_tasks,
    list_indexed_tasks,
    notify_matrix,
)

BackfillTask = namedtuple("BackfillTask", ["task_id", "th_symbol", "state"])

NOTIFICATION_BACKFILL_GROUP_COMPLETED = "Backfill tasks associated to the Treeherder symbol {th_symbol} for push {push.branch}/{push.rev} are all completed."


class CheckBackfillsCommand(Command):
    """
    Check if backfills on last pushes are finished and notify Sheriffs when they are.

    check-backfills
        {--branch=autoland : Branch the pushes belongs to (e.g autoland, try, etc).}
        {--nb-pushes=40 : Number of recent pushes to retrieve for the check.}
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}

    The command will execute the following workflow:
      1. Retrieve the last <--nb-pushes> Pushes on branch <--branch>
      => Then for each Push:
      2. Check if it has any associated actions triggered by Treeherder, using Taskcluster indexation
      3. Find potential backfill tasks
      4. Group them by backfill groups
      => For each backfill group on the Push:
      5. Check if all backfill tasks in this group are completed
      6. If so (and if the notification wasn't already sent), send a notification on Matrix alerting that this backfill group is completed
      7. Add the current task in a dedicated index to avoid sending multiple times the same notification
    """

    def handle(self) -> None:
        branch = self.option("branch")
        environment = self.option("environment")
        matrix_room = config.get("matrix-room-id")
        current_task_id = os.environ.get("TASK_ID")

        try:
            nb_pushes = int(self.option("nb-pushes"))
        except ValueError:
            self.line("<error>Provided --nb-pushes should be an int.</error>")
            exit(1)

        self.line("<comment>Loading pushes...</comment>")
        self.pushes = make_push_objects(nb=nb_pushes, branch=branch)
        nb_pushes = len(self.pushes)

        for index, push in enumerate(self.pushes, start=1):
            self.line(
                f"<comment>Processing push {index}/{nb_pushes}: {push.push_uuid}</comment>"
            )
            backfill_tasks = []

            try:
                indexed_tasks = list_indexed_tasks(
                    f"gecko.v2.{push.branch}.revision.{push.rev}.taskgraph.actions"
                )
            except requests.exceptions.HTTPError as e:
                self.line(
                    f"<error>Couldn't fetch indexed tasks on push {push.push_uuid}: {e}</error>"
                )
                continue

            for indexed_task in indexed_tasks:
                task_id = indexed_task["taskId"]
                try:
                    children_tasks = list_dependent_tasks(task_id)
                except requests.exceptions.HTTPError as e:
                    self.line(
                        f"<error>Couldn't fetch dependent tasks of indexed task {task_id} on push {push.push_uuid}: {e}</error>"
                    )
                    continue

                for child_task in children_tasks:
                    task_action = (
                        child_task.get("task", {}).get("tags", {}).get("action", "")
                    )
                    # We are looking for the Treeherder symbol because Sheriffs are
                    # only interested in backfill-tasks holding the '-bk' suffix in TH
                    th_symbol = (
                        child_task.get("task", {})
                        .get("extra", {})
                        .get("treeherder", {})
                        .get("symbol", "")
                    )
                    status = child_task.get("status", {})
                    if task_action == "backfill-task" and th_symbol.endswith("-bk"):
                        assert status.get(
                            "taskId"
                        ), "Missing taskId attribute in backfill task status"
                        assert status.get(
                            "state"
                        ), "Missing state attribute in backfill task status"
                        backfill_tasks.append(
                            BackfillTask(status["taskId"], th_symbol, status["state"])
                        )
                    else:
                        logger.debug(
                            f"Skipping non-backfill task {status.get('taskId')}"
                        )

            def group_key(task):
                return task.th_symbol

            # Sorting backfill tasks by their Treeherder symbol
            backfill_tasks = sorted(backfill_tasks, key=group_key)
            # Grouping ordered backfill tasks by their associated Treeherder symbol
            for th_symbol, value in groupby(backfill_tasks, group_key):
                tasks = list(value)
                if all(task.state == "completed" for task in tasks):
                    index_path = f"project.mozci.check-backfill.{environment}.{push.branch}.{push.rev}.{th_symbol}"
                    try:
                        find_task_id(
                            index_path, root_url=COMMUNITY_TASKCLUSTER_ROOT_URL
                        )
                    except requests.exceptions.HTTPError:
                        pass
                    else:
                        logger.debug(
                            f"A notification was already sent for the backfill tasks associated to the Treeherder symbol {th_symbol}."
                        )
                        continue

                    notification = NOTIFICATION_BACKFILL_GROUP_COMPLETED.format(
                        th_symbol=th_symbol,
                        push=push,
                    )

                    if not matrix_room:
                        self.line(
                            f"<comment>A notification should be sent for the backfill tasks associated to the Treeherder symbol {th_symbol} but no matrix room was provided in the secret.</comment>"
                        )
                        logger.debug(f"The notification: {notification}")
                        continue

                    # Sending a notification to the Matrix channel defined in secret
                    notify_matrix(
                        room=matrix_room,
                        body=notification,
                    )

                    if not current_task_id:
                        self.line(
                            f"<comment>The current task should be indexed in {index_path} but TASK_ID environment variable isn't set.</comment>"
                        )
                        continue

                    # Populating the index with the current task to prevent sending the notification once again
                    index_current_task(
                        index_path,
                        root_url=COMMUNITY_TASKCLUSTER_ROOT_URL,
                    )
