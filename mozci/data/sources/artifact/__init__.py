# -*- coding: utf-8 -*-

import json
from collections import defaultdict
from typing import Any, Dict

import requests

from mozci.data.base import DataSource
from mozci.util.taskcluster import get_artifact, list_artifacts


class ErrorSummarySource(DataSource):
    name = "errorsummary"
    supported_contracts = ("test_task_groups", "test_task_errors")

    TASK_CACHE: Dict[str, Any] = defaultdict(
        lambda: {
            "errors": [],
            "groups": {},
        }
    )

    def _load_errorsummary(self, task_id) -> None:
        """Load the task's errorsummary.log.

        We gather all data we can and store it in the TASK_CACHE so we don't have to load
        it again for a different contract.
        """
        try:
            artifacts = [a["name"] for a in list_artifacts(task_id)]
            paths = [a for a in artifacts if a.endswith("errorsummary.log")]
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return
            raise
        except IndexError:
            return

        groups = set()
        group_results = {}

        lines = (
            json.loads(line)
            for path in paths
            for line in get_artifact(task_id, path).iter_lines(decode_unicode=True)
            if line
        )

        for line in lines:
            if line["action"] == "test_groups":
                groups |= set(line["groups"]) - {"default"}

            elif line["action"] == "group_result":

                group = line["group"]
                if group not in group_results or line["status"] != "OK":
                    group_results[group] = line["status"]

            elif line["action"] == "log":
                self.TASK_CACHE[task_id]["errors"].append(line["message"])

        self.TASK_CACHE[task_id]["groups"] = {
            group: result == "OK"
            for group, result in group_results.items()
            if result != "SKIP"
        }

    def run_test_task_groups(self, task):
        if task.id not in self.TASK_CACHE:
            self._load_errorsummary(task.id)
        return self.TASK_CACHE[task.id]["groups"]

    def run_test_task_errors(self, task):
        if task.id not in self.TASK_CACHE:
            self._load_errorsummary(task.id)
        return self.TASK_CACHE[task.id]["errors"]
