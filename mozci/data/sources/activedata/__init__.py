# -*- coding: utf-8 -*-

from argparse import Namespace
from collections import defaultdict
from pathlib import Path

import adr
from loguru import logger

from mozci.data.base import DataSource

here = Path(__file__).parent.resolve()
adr.sources.load_source(here)


class ActiveDataSource(DataSource):
    """Uses 'adr' to query ActiveData."""

    name = "adr"
    supported_contracts = (
        "push_tasks",
        "push_tasks_tags",
        "push_test_groups",
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

            items.append(item)
        return items

    def run_push_tasks(self, **kwargs):
        result = adr.query.run_query("push_tasks_from_treeherder", Namespace(**kwargs))
        tasks = []

        # If we are missing one of these keys, discard the task.
        required_keys = (
            "id",
            "label",
            "result",
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

            if task.get("classification_note"):
                if isinstance(task["classification_note"], list):
                    task["classification_note"] = task["classification_note"][-1]
                    if task["classification_note"] is None:
                        del task["classification_note"]

            tasks.append(task)
        return tasks

    def run_push_tasks_tags(self, **kwargs):
        result = adr.query.run_query("push_tasks_tags_from_task", Namespace(**kwargs))
        tags = defaultdict(dict)
        for item in self.normalize(result):
            if "tags" not in item:
                continue

            for tag in item["tags"]:
                if any(k not in tag for k in ("name", "value")):
                    continue
                tags[item["id"]][tag["name"]] = tag["value"]
        return tags

    def run_push_test_groups(self, **kwargs):
        result = adr.query.run_query(
            "push_test_groups_from_unittest", Namespace(**kwargs)
        )
        required_keys = ("result_group", "result_ok")
        groups = defaultdict(dict)
        for item in self.normalize(result):
            if any(k not in item for k in required_keys):
                continue

            groups[item["id"]][item["result_group"]] = bool(item["result_ok"])

        return groups
