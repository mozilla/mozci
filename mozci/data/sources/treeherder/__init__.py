# -*- coding: utf-8 -*-

import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from functools import lru_cache
from typing import Dict, List

from loguru import logger
from lru import LRU

from mozci.data.base import DataSource
from mozci.errors import ContractNotFilled
from mozci.util.memoize import memoized_property
from mozci.util.req import get_session

try:
    from treeherder.log_parser.failureline import get_group_results
    from treeherder.model.models import Job, Push
except ImportError:
    Job = None
    Push = None


class BaseTreeherderSource(DataSource, ABC):
    lock = threading.Lock()
    groups_cache: Dict[str, List[str]] = LRU(5000)

    @abstractmethod
    def get_push_test_groups(self, branch: str, rev: str) -> Dict[str, List[str]]:
        ...

    def run_test_task_groups(self, branch, rev, task):
        # Use a lock since push.py invokes this across many threads (which is
        # useful for the 'errorsummary' data source, but not here). This ensures
        # we don't make more than one request to Treeherder.
        with self.lock:
            if task.id not in self.groups_cache:
                self.groups_cache.update(self.get_push_test_groups(branch, rev))

        try:
            return self.groups_cache.pop(task.id)
        except KeyError:
            raise ContractNotFilled(self.name, "test_task_groups", "groups are missing")


class TreeherderClientSource(BaseTreeherderSource):
    """Uses the public API to query Treeherder."""

    name = "treeherder_client"
    supported_contracts = ("push_tasks_classifications", "test_task_groups")
    base_url = "https://treeherder.mozilla.org/api"

    @memoized_property
    def session(self):
        session = get_session()
        session.headers = {"User-Agent": "mozci"}
        return session

    @lru_cache(maxsize=50)
    def _run_query(self, query, params=None):
        query = query.strip("/")
        url = f"{self.base_url}/{query}"

        params = params or {}
        params.setdefault("format", "json")

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def run_push_tasks_classifications(self, branch, rev):
        data = self._run_query(f"/project/{branch}/note/push_notes/?revision={rev}")

        classifications = {}
        for item in data:
            job = item["job"]
            classifications[job["task_id"]] = {
                "classification": item["failure_classification_name"]
            }
            if item["text"]:
                classifications[job["task_id"]]["classification_note"] = item["text"]
        return classifications

    def get_push_test_groups(self, branch, rev) -> Dict[str, List[str]]:
        data = self._run_query(f"/project/{branch}/push/group_results/?revision={rev}")
        return {k: v for k, v in data.items() if v if k not in ("", "default")}


class TreeherderDBSource(BaseTreeherderSource):
    """Uses the ORM to query Treeherder."""

    name = "treeherder_db"
    supported_contracts = (
        "push_tasks",
        "push_tasks_classifications",
        "test_task_groups",
    )

    @classmethod
    def normalize(cls, jobs):
        retries = defaultdict(int)
        items = []

        for job in jobs:
            task_id = job.taskcluster_metadata.task_id
            retry_id = job.taskcluster_metadata.retry_id

            # If a task is re-run, use the data from the last run.
            if retry_id < retries[task_id]:
                logger.trace(f"Skipping {job} because there is a newer run of it.")
                continue

            retries[task_id] = retry_id

            note = ""
            notes = job.jobnote_set.all()
            if len(notes):
                note = str(notes[0].text)

            item = {
                "id": str(task_id),
                "label": job.job_type.name,
                "result": job.result,
                "state": job.state,
                "classification": job.failure_classification.name,
                "classification_note": note,
                "duration": Job.get_duration(
                    job.submit_time, job.start_time, job.end_time
                ),
            }

            result_map = {
                "success": "passed",
                "testfailed": "failed",
                "busted": "failed",
                "usercancel": "canceled",
                "retry": "exception",
            }
            if item["result"] in result_map:
                item["result"] = result_map[item["result"]]

            items.append(item)
        return items

    @lru_cache(maxsize=1)
    def _get_tasks(self, branch, rev):
        jobs = (
            Job.objects.filter(push__revision=rev, repository__name=branch)
            .exclude(
                tier=3,
                result="retry",
                job_type__name="Gecko Decision Task",
                job_type__name__startswith="Action",
            )
            .select_related(
                "push",
                "job_type",
                "taskcluster_metadata",
                "failure_classification",
                "repository",
                "repository__repository_group",
            )
            .prefetch_related("jobnote_set")
        )

        tasks = {}

        for task in self.normalize(jobs):
            # TODO: Add support for tags.
            task["tags"] = {}

            tasks[task["id"]] = task
        return tasks

    def run_push_tasks(self, branch, rev):
        keys = ("id", "label", "result", "duration", "tags", "state")
        if not Job:
            raise ContractNotFilled(
                self.name, "push_tasks", "could not import Job model"
            )

        tasks = self._get_tasks(branch, rev)

        return [
            {
                key: task_data[key]
                for key in keys
                if not (key == "result" and task_data[key] == "unknown")
            }
            for task_id, task_data in tasks.items()
        ]

    def run_push_tasks_classifications(self, branch, rev):
        if not Job:
            raise ContractNotFilled(
                self.name, "push_tasks_classifications", "could not import Job model"
            )

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

    def get_push_test_groups(self, branch, rev) -> Dict[str, List[str]]:
        if not Push:
            raise ContractNotFilled(
                self.name, "push_test_groups", "could not import Push model"
            )

        push = Push.objects.get(repository__name=branch, revision=rev)
        return get_group_results(push)
