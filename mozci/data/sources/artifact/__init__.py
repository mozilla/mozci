# -*- coding: utf-8 -*-

import json
from typing import Any, Dict, List, Tuple

import requests
from loguru import logger
from lru import LRU

from mozci.data.base import DataSource
from mozci.task import FailureType, GroupName, TestName
from mozci.util.taskcluster import get_artifact, list_artifacts


class ErrorSummarySource(DataSource):
    name = "errorsummary"
    is_try = False
    supported_contracts = (
        "test_task_groups",
        "test_task_errors",
        "test_task_failure_types",
    )

    TASK_GROUPS: Dict[str, Any] = LRU(2000)
    TASK_ERRORS: Dict[str, Any] = LRU(2000)
    TASK_FAILURE_TYPES: Dict[str, Any] = LRU(2000)

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
        test_results: Dict[GroupName, List[Tuple[TestName, FailureType]]] = {}

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
                    group_results[group] = (line["status"], line["duration"])

            elif line["action"] == "log":
                if task_id not in self.TASK_ERRORS:
                    self.TASK_ERRORS[task_id] = []
                self.TASK_ERRORS[task_id].append(line["message"])

            if line.get("test") and line.get("group"):
                if not test_results.get(line["group"]):
                    test_results[line["group"]] = []

                if (
                    line.get("status") != line.get("expected")
                    and line.get("status") == "TIMEOUT"
                ):
                    failure_type = FailureType.TIMEOUT
                elif (
                    line.get("signature") is not None and line.get("action") == "crash"
                ):
                    failure_type = FailureType.CRASH
                else:
                    failure_type = FailureType.GENERIC

                test_results[line["group"]].append((line["test"], failure_type))

        missing_groups = groups - set(group_results)
        if len(missing_groups) > 0:
            log_level = "DEBUG" if self.is_try else "WARNING"
            logger.log(
                log_level,
                f"Some groups in {task_id} are missing results: {missing_groups}",
            )

        self.TASK_GROUPS[task_id] = {
            group: (result == "OK", duration)
            for group, (result, duration) in group_results.items()
            if result != "SKIP"
        }

        self.TASK_FAILURE_TYPES[task_id] = test_results

    def run_test_task_groups(self, branch, rev, task):
        if branch == "try":
            self.is_try = True

        if task.id not in self.TASK_GROUPS:
            self._load_errorsummary(task.id)
        return self.TASK_GROUPS.pop(task.id, {})

    def run_test_task_errors(self, task):
        if task.id not in self.TASK_ERRORS:
            self._load_errorsummary(task.id)
        return self.TASK_ERRORS.pop(task.id, {})

    def run_test_task_failure_types(self, task_id):
        if task_id not in self.TASK_FAILURE_TYPES:
            self._load_errorsummary(task_id)
        return self.TASK_FAILURE_TYPES.pop(task_id, {})
