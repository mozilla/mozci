# -*- coding: utf-8 -*-

import threading
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Dict, List

from lru import LRU

from mozci.data.base import DataSource
from mozci.errors import ContractNotFilled
from mozci.task import Task
from mozci.util.memoize import memoized_property
from mozci.util.req import get_session

try:
    from treeherder.model.models import Job, Push
except ImportError:
    Job = None
    Push = None


class JobUnavailable(Exception):
    """Exception raised when a Treeherder job does not exist or its logs have not been parsed yet"""


class BaseTreeherderSource(DataSource, ABC):
    lock = threading.Lock()
    groups_cache: Dict[str, List[str]] = LRU(7000)

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
            # TODO: Once https://github.com/mozilla/mozci/issues/662 is fixed, we should return the actual duration instead of None.
            return {
                group: (status, None)
                for group, status in self.groups_cache.pop(task.id).items()
            }
        except KeyError:
            raise ContractNotFilled(self.name, "test_task_groups", "groups are missing")


class TreeherderClientSource(BaseTreeherderSource):
    """Uses the public API to query Treeherder."""

    name = "treeherder_client"
    supported_contracts = ("push_tasks_classifications", "test_task_groups", "pushes")
    base_url = "https://treeherder.mozilla.org/api"

    @memoized_property
    def session(self):
        session = get_session()
        session.headers = {"User-Agent": "mozci"}
        return session

    @lru_cache(maxsize=700)
    def _run_query(self, query, params=None):
        query = query.lstrip("/")
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

    def run_pushes(self, branch, nb=15) -> List[Dict]:
        response = self._run_query(f"/project/{branch}/push/?count={nb}")
        return [
            {
                "pushid": p["id"],
                "date": p["push_timestamp"],
                "revs": [r["revision"] for r in p["revisions"]],
            }
            for p in response["results"]
        ]

    def get_job_from_task(self, task: Task) -> dict:
        """Map a task to its Treeherder job, based on the Job list API.
        The endpoint returns a list of jobs, but only 1 result should be present using the `task_id` parameter.
        """
        data = self._run_query(f"/jobs/?task_id={task.id}")
        job = next(iter(data.get("results", [])), None)
        if not job:
            raise JobUnavailable
        if "job_property_names" not in data:
            raise Exception(
                "`job_property_names` is missing from /jobs/ treeherder API response"
            )
        return {key: value for key, value in zip(data["job_property_names"], job)}

    def check_job_ready(self, job_id: int, branch: str = "autoland") -> None:
        """Check if a specific job has been processed in Treeherder already.
        Raises JobUnavailable in case no job log are found or some are still in a pending state.
        """
        data = self._run_query(f"/project/{branch}/job-log-url/?job_id={job_id}")
        if (
            not data
            # Job logs can have final state "parsed", "failed" or "skipped_size"
            or any(job_log_url.get("parse_status") == "pending" for job_log_url in data)
        ):
            raise JobUnavailable

    def get_bug_suggestions(self, job_id: int, branch: str = "autoland") -> list[dict]:
        """List suggestions for a specific job."""
        return self._run_query(f"/project/{branch}/jobs/{job_id}/bug_suggestions/")
