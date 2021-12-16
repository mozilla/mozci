# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import csv
import re
from datetime import datetime

import taskcluster
from loguru import logger

from mozci import config
from mozci.util.taskcluster import get_taskcluster_options

HOOK_GROUP = "project-mozci"
HOOK_ID = "decision-task-testing"

REGEX_ROUTE = re.compile(
    r"^index.project.mozci.classification.([\w\-]+).(revision|push).(\w+)$"
)


def list_groups_from_hook(group_id, hook_id):
    hooks = taskcluster.Hooks(get_taskcluster_options())
    fires = hooks.listLastFires(group_id, hook_id)
    for fire in fires.get("lastFires", []):
        yield fire["taskId"]


def list_classification_tasks(group_id):
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


def date(x):
    return datetime.strptime(x, "%Y-%m-%dT%H:%M:%S.%fZ")


def parse_routes(routes):
    """Find revision from task routes"""

    def _match(route):
        res = REGEX_ROUTE.search(route)
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


def parse_task_status(task_status):
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
    out["branch"], out["revision"], out["push"] = parse_routes(
        task_status["task"]["routes"]
    )
    return out


def main():

    # Aggregate stats for completed tasks processed by the hook
    stats = [
        parse_task_status(task_status)
        for group_id in list_groups_from_hook(HOOK_GROUP, HOOK_ID)
        for task_status in list_classification_tasks(group_id)
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
        writer.writerows(stats)


if __name__ == "__main__":
    main()
