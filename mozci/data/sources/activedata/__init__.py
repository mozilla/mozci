# -*- coding: utf-8 -*-

from argparse import Namespace
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import adr
from loguru import logger

from mozci.data.base import DataSource
from mozci.errors import MissingDataError

here = Path(__file__).parent.resolve()
adr.sources.load_source(here)


class ActiveDataSource(DataSource):
    """Uses 'adr' to query ActiveData."""

    name = "adr"
    supported_contracts = (
        "push_tasks",
        "push_tasks_classifications",
        "push_test_groups",
        "push_revisions",
    )

    @classmethod
    def normalize(cls, result):
        if "header" in result:
            result["data"] = [
                {
                    field: value
                    for field, value in zip(result["header"], entry)
                    if value is not None
                }
                for entry in result["data"]
            ]

        items = []
        retries = defaultdict(int)

        for item in result["data"]:
            if "id" not in item:
                logger.trace(f"Skipping {item} because of missing id.")
                continue

            task_id = item["id"]

            # If a task is re-run, use the data from the last run.
            if "retry_id" in item:
                if item["retry_id"] < retries[task_id]:
                    logger.trace(f"Skipping {item} because there is a newer run of it.")
                    continue

                retries[task_id] = item["retry_id"]

                # We don't need to store the retry ID.
                del item["retry_id"]

            # Normalize result
            result_map = {
                "success": "passed",
                "testfailed": "failed",
                "busted": "failed",
                "usercancel": "canceled",
                "retry": "exception",
            }
            if item.get("result") in result_map:
                item["result"] = result_map[item["result"]]

            items.append(item)
        return items

    @lru_cache(maxsize=1)
    def _get_tasks(self, branch, rev):
        try:
            result = adr.query.run_query(
                "push_tasks_from_treeherder", Namespace(branch=branch, rev=rev)
            )
        except adr.MissingDataError as e:
            raise MissingDataError(str(e))

        tasks = {}

        # If we are missing one of these keys, discard the task.
        required_keys = (
            "id",
            "label",
            "result",
            "state",
        )

        for task in self.normalize(result):
            missing = [k for k in required_keys if k not in task]
            taskstr = task.get("label", task["id"])

            if missing:
                logger.trace(
                    f"Skipping task '{taskstr}' because it is missing "
                    f"the following attributes: {', '.join(missing)}"
                )
                continue

            if task.get("tags"):
                task["tags"] = {t["name"]: t["value"] for t in task["tags"]}
            else:
                task["tags"] = {}

            if task.get("classification_note"):
                if isinstance(task["classification_note"], list):
                    task["classification_note"] = task["classification_note"][-1]
                    if task["classification_note"] is None:
                        del task["classification_note"]

            tasks[task["id"]] = task

        # TODO: Figure out why we have some results from the `push_tasks_tags_from_task` query
        # that we don't have from `push_tasks_from_treeherder`.
        try:
            result = adr.query.run_query(
                "push_tasks_tags_from_task", Namespace(branch=branch, rev=rev)
            )
        except adr.MissingDataError as e:
            raise MissingDataError(str(e))

        for item in self.normalize(result):
            if "tags" not in item:
                continue

            for tag in item["tags"]:
                if any(k not in tag for k in ("name", "value")):
                    continue

                if item["id"] in tasks:
                    tasks[item["id"]]["tags"][tag["name"]] = tag["value"]

        return tasks

    def run_push_tasks(self, branch, rev):
        tasks = self._get_tasks(branch, rev)

        return [
            {
                "id": task_data["id"],
                "label": task_data["label"],
                "result": task_data["result"],
                "state": task_data["state"],
                "duration": task_data["duration"],
                "tags": task_data["tags"],
            }
            for task_id, task_data in tasks.items()
        ]

    def run_push_tasks_classifications(self, branch, rev):
        tasks = self._get_tasks(branch, rev)

        result = {}
        for task_id, task_data in tasks.items():
            result[task_id] = {
                "classification": task_data["classification"],
            }

            if task_data.get("classification_note"):
                result[task_id]["classification_note"] = task_data[
                    "classification_note"
                ]

        return result

    def run_push_test_groups(self, **kwargs):
        try:
            result = adr.query.run_query(
                "push_test_groups_from_unittest", Namespace(**kwargs)
            )
        except adr.MissingDataError as e:
            raise MissingDataError(str(e))

        required_keys = ("result_group", "result_ok")
        groups = defaultdict(dict)
        for item in self.normalize(result):
            if any(k not in item for k in required_keys):
                continue

            groups[item["id"]][item["result_group"]] = bool(item["result_ok"])

        return groups

    def run_push_revisions(self, **kwargs):
        try:
            result = adr.query.run_query("push_revisions", Namespace(**kwargs))
        except adr.MissingDataError as e:
            raise MissingDataError(str(e))

        pushes = []

        for push_id, date, revs, parents in result["data"]:
            topmost = list(set(revs) - set(parents))[0]

            pushes.append(
                {
                    "pushid": push_id,
                    "date": date,
                    "revs": [topmost] + [r for r in revs if r != topmost],
                }
            )

        return pushes
