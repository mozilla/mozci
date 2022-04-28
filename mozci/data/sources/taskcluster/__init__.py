# -*- coding: utf-8 -*-

from datetime import datetime

import requests
from loguru import logger
from taskcluster import Index
from taskcluster.exceptions import TaskclusterRestFailure

from mozci.data.base import DataSource
from mozci.errors import ContractNotFilled
from mozci.util import taskcluster


class TaskclusterSource(DataSource):
    """Queries Taskcluster for data about tasks."""

    name = "taskcluster"
    supported_contracts = (
        "push_tasks",
        "push_test_selection_data",
        "push_existing_classification",
    )

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
            tier = result["task"]["extra"].get("treeherder", {}).get("tier")
            if tier:
                task["tier"] = tier

            # Use the latest run (earlier ones likely had exceptions that
            # caused an automatic retry).
            if task["state"] != "unscheduled":
                run = result["status"]["runs"][-1]

                # Normalize the state to match treeherder's values.
                if task["state"] == "failed":
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
                    assert task["state"] in ("pending", "running", "exception")

                # Compute duration.
                if "started" in run and "resolved" in run:
                    task["duration"] = self.to_ms(run["resolved"]) - self.to_ms(
                        run["started"]
                    )

            tasks.append(task)

        return tasks

    def run_push_test_selection_data(self, branch, rev):
        task_name = f"gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
        try:
            decision_task_id = taskcluster.find_task_id(task_name)
        except requests.exceptions.HTTPError as e:
            # If the decision task was not indexed, it means it was broken. So we can
            # assume we didn't run any task for this push.
            if e.response.status_code == 404:
                logger.warning(f"Decision task broken in {rev} on {branch}")

            raise ContractNotFilled(
                self.name,
                "push_test_selection_data",
                f"could not retrieve decision task '{task_name}'",
            )

        try:
            results = taskcluster.get_artifact(
                decision_task_id, "public/bugbug-push-schedules.json"
            )
        except requests.exceptions.HTTPError:
            raise ContractNotFilled(
                self.name,
                "push_test_selection_data",
                "could not retrieve schedules from cache",
            )

        return results

    def run_push_existing_classification(self, branch, rev, environment):
        # Non-production environments are exposed in sub routes
        route_prefix = (
            "project.mozci.classification"
            if environment == "production"
            else f"project.mozci.{environment}.classification"
        )

        # We use buildUrl and manual requests.get instead of directly findArtifactFromTask from the taskcluster library
        # because the taskcluster library fails with redirects (https://github.com/taskcluster/taskcluster/issues/4998).
        try:
            # Proxy authentication does not seem to work here
            index = Index({"rootUrl": taskcluster.COMMUNITY_TASKCLUSTER_ROOT_URL})
            url = index.buildUrl(
                "findArtifactFromTask",
                f"{route_prefix}.{branch}.revision.{rev}",
                "public/classification.json",
            )
        except TaskclusterRestFailure as e:
            raise ContractNotFilled(
                self.name,
                "push_existing_classification",
                f"Failed to load existing classification for {branch} {rev}: {e}",
            )

        try:
            r = requests.get(url, allow_redirects=True)
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            raise ContractNotFilled(
                self.name,
                "push_existing_classification",
                f"Failed to load existing classification for {branch} {rev}: {e}",
            )

        try:
            return r.json()["push"]["classification"]
        except KeyError:
            raise ContractNotFilled(
                self.name, "push_existing_classification", "Invalid classification data"
            )
