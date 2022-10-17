# -*- coding: utf-8 -*-
import os
import re
from collections import namedtuple
from itertools import groupby
from typing import Any, Dict

import requests
from cleo import Command
from loguru import logger

from mozci import config
from mozci.push import make_push_objects
from mozci.util.defs import TASK_FINAL_STATES
from mozci.util.taskcluster import (
    COMMUNITY_TASKCLUSTER_ROOT_URL,
    find_task_id,
    index_current_task,
    list_dependent_tasks,
    list_indexed_tasks,
    notify_matrix,
)

BackfillTask = namedtuple("BackfillTask", ["task_id", "label", "th_symbol", "state"])

NOTIFICATION_BACKFILL_GROUP_COMPLETED = "Backfill tasks associated to the Treeherder symbol {th_symbol} for push [{push.branch}/{push.rev}](https://treeherder.mozilla.org/jobs?group_state=expanded&repo={push.branch}{tochange}{fromchange}{searchstr}) are all in a final state."


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

        to_notify: Dict[str, Dict[str, Any]] = {}
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
                    task_section = child_task.get("task", {})
                    task_action = task_section.get("tags", {}).get("action", "")
                    # We are looking for the Treeherder symbol because Sheriffs are
                    # only interested in backfill-tasks holding the '-bk' suffix in TH
                    th_symbol = (
                        task_section.get("extra", {})
                        .get("treeherder", {})
                        .get("symbol", "")
                    )
                    status = child_task.get("status", {})
                    if task_action == "backfill-task" and th_symbol.endswith("-bk"):
                        assert status.get(
                            "taskId"
                        ), "Missing taskId attribute in backfill task status"
                        label = task_section.get("tags", {}).get(
                            "label"
                        ) or task_section.get("metadata", {}).get("name")
                        assert (
                            label
                        ), "Missing label attribute in backfill task tags or name attribute in backfill task metadata"
                        assert status.get(
                            "state"
                        ), "Missing state attribute in backfill task status"
                        backfill_tasks.append(
                            BackfillTask(
                                status["taskId"], label, th_symbol, status["state"]
                            )
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
            for th_symbol, tasks_iter in groupby(backfill_tasks, group_key):
                if th_symbol not in to_notify:
                    to_notify[th_symbol] = {
                        "newest_push": None,
                        "backfill_tasks": set(),
                    }

                # make_push_objects returns the latest pushes in chronological order from oldest to newest
                # We only need to store the newest Push that appeared for this Treeherder symbol
                to_notify[th_symbol]["newest_push"] = push
                # Storing all backfill tasks for this symbol across multiple pushes
                to_notify[th_symbol]["backfill_tasks"].update(tasks_iter)

        for th_symbol, data in to_notify.items():
            logger.debug("Preparing notification for the Treeherder symbol {th_symbol}")

            all_backfill_tasks = data["backfill_tasks"]
            # Checking that all backfill tasks for this symbol are in a "final" state
            if not all(task.state in TASK_FINAL_STATES for task in all_backfill_tasks):
                logger.debug(
                    f"Not all backfill tasks for the Treeherder symbol {th_symbol} are in a final state, not notifying now."
                )
                continue

            newest_push = data["newest_push"]
            index_path = f"project.mozci.check-backfill.{environment}.{newest_push.branch}.{newest_push.rev}.{th_symbol}"
            try:
                find_task_id(index_path, root_url=COMMUNITY_TASKCLUSTER_ROOT_URL)
            except requests.exceptions.HTTPError:
                pass
            else:
                logger.debug(
                    f"A notification was already sent for the backfill tasks associated to the Treeherder symbol {th_symbol}."
                )
                continue

            try:
                parents = [
                    parent for parent in newest_push._iterate_parents(max_depth=20)
                ]
            except Exception as e:
                logger.debug(
                    f"Failed to load the last twenty parent pushes for push {newest_push.push_uuid}, because: {e}."
                )
                parents = None

            logger.debug("Generating notification text")

            cleaned_label = re.sub(
                r"(-e10s|-1proc)?(-\d+)?$", "", all_backfill_tasks.pop().label
            )
            notification = NOTIFICATION_BACKFILL_GROUP_COMPLETED.format(
                th_symbol=th_symbol,
                push=newest_push,
                tochange=f"&tochange={newest_push.child.rev}",
                fromchange=f"&fromchange={parents[-1].rev}" if parents else "",
                searchstr=f"&searchStr={cleaned_label}",
            )

            if not matrix_room:
                self.line(
                    f"<comment>A notification should be sent for the backfill tasks associated to the Treeherder symbol {th_symbol} but no matrix room was provided in the secret.</comment>"
                )
                logger.debug(f"The notification: {notification}")
                continue

            logger.debug("Sending Matrix notification")

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

            logger.debug("Indexing current task")

            # Populating the index with the current task to prevent sending the notification once again
            index_current_task(
                index_path,
                root_url=COMMUNITY_TASKCLUSTER_ROOT_URL,
            )
