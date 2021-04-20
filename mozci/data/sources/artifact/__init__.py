# -*- coding: utf-8 -*-

import json
from typing import Any, Dict

import requests
from loguru import logger
from lru import LRU

from mozci.data.base import DataSource
from mozci.util.taskcluster import get_artifact, list_artifacts


class ErrorSummarySource(DataSource):
    name = "errorsummary"
    supported_contracts = ("test_task_groups", "test_task_errors")

    TASK_GROUPS: Dict[str, Any] = LRU(2000)
    TASK_ERRORS: Dict[str, Any] = LRU(2000)

    def _load_errorsummary(self, task_id) -> None:
        """Load the task's errorsummary.log.

        We gather all data we can and store it in the TASK_* caches so we don't
        have to load it again for a different contract.
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
                if task_id not in self.TASK_ERRORS:
                    self.TASK_ERRORS[task_id] = []
                self.TASK_ERRORS[task_id].append(line["message"])

        missing_groups = groups - set(group_results)
        if len(missing_groups) > 0:
            logger.error(
                f"Some groups in {task_id} are missing results: {missing_groups}"
            )

        self.TASK_GROUPS[task_id] = {
            group: result == "OK"
            for group, result in group_results.items()
            if result != "SKIP"
        }

    def run_test_task_groups(self, branch, rev, task):
        if task.id not in self.TASK_GROUPS:
            self._load_errorsummary(task.id)
        return self.TASK_GROUPS.pop(task.id, {})

    def run_test_task_errors(self, task):
        if task.id not in self.TASK_ERRORS:
            self._load_errorsummary(task.id)
        return self.TASK_ERRORS.pop(task.id, {})
