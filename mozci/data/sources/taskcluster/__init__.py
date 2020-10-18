# -*- coding: utf-8 -*-

from mozci.data.base import DataSource
from mozci.util import taskcluster


class TaskclusterSource(DataSource):
    """Queries Taskcluster for data about tasks."""

    name = "taskcluster"
    supported_contracts = ("push_tasks",)

    def run_push_tasks(self, branch, rev):
        decision_task_id = taskcluster.find_task_id(
            f"gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
        )

        task_data = taskcluster.get_task(decision_task_id)

        results = taskcluster.get_tasks_in_group(task_data["taskGroupId"])

        tasks = []
        for result in results:
            # Skip tier 3 tasks.
            if result["task"]["extra"]["treeherder"].get("tier") == 3:
                continue

            # Skip the decision task.
            if result["status"]["taskId"] == decision_task_id:
                continue

            # Skip "Action" tasks.
            if result["task"]["metadata"]["name"].startswith("Action"):
                continue

            tasks.append(
                {
                    "id": result["status"]["taskId"],
                    "label": result["task"]["metadata"]["name"],
                    "tags": result["task"]["tags"],
                }
            )

        return tasks
