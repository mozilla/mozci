# -*- coding: utf-8 -*-

from datetime import datetime

import requests
from loguru import logger

from mozci.data.base import DataSource
from mozci.util import taskcluster


class TaskclusterSource(DataSource):
    """Queries Taskcluster for data about tasks."""

    name = "taskcluster"
    supported_contracts = ("push_tasks",)

    def to_ms(self, datestring, fmt="%Y-%m-%dT%H:%M:%S.%fZ"):
        dt = datetime.strptime(datestring, fmt)
        return int(dt.timestamp() * 1000)

    def run_push_tasks(self, branch, rev):
        try:
            decision_task_id = taskcluster.find_task_id(
                f"gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
            )
        except requests.exceptions.HTTPError as e:
            # If the decision task was not indexed, it means it was broken. So we can
            # assume we didn't run any task for this push.
            if e.response.status_code == 404:
                logger.warning(f"Decision task broken in {rev} on {branch}")
                return []

            raise

        task_data = taskcluster.get_task(decision_task_id)

        results = taskcluster.get_tasks_in_group(task_data["taskGroupId"])

        tasks = []
        for result in results:
            # Skip tier 3 tasks.
            if result["task"]["extra"].get("treeherder", {}).get("tier") == 3:
                continue

            # Skip the decision task.
            if result["status"]["taskId"] == decision_task_id:
                continue

            # Skip "Action" tasks.
            if result["task"]["metadata"]["name"].startswith("Action"):
                continue

            task = {
                "id": result["status"]["taskId"],
                "label": result["task"]["metadata"]["name"],
                "tags": result["task"]["tags"],
                "state": result["status"]["state"],
            }

            # Use the latest run (earlier ones likely had exceptions that
            # caused an automatic retry).
            if task["state"] != "unscheduled":
                run = result["status"]["runs"][-1]

                # Normalize the state to match treeherder's values.
                if task["state"] in ("failed", "exception"):
                    task["state"] = "completed"

                # Derive a result from the reasonResolved.
                reason = run.get("reasonResolved")
                if reason == "completed":
                    task["result"] = "passed"
                elif reason in ("canceled", "superseded", "failed"):
                    task["result"] = reason
                elif reason:
                    task["result"] = "exception"
                else:
                    # Task is not finished, so there is no result yet.
                    assert task["state"] in ("pending", "running")

                # Compute duration.
                if "started" in run and "resolved" in run:
                    task["duration"] = self.to_ms(run["resolved"]) - self.to_ms(
                        run["started"]
                    )

            tasks.append(task)

        return tasks
