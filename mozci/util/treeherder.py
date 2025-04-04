# -*- coding: utf-8 -*-

# This module is intended to replace the usual mozci API
# calls via contracts interface to ease developments for
# auto detection of regressions.
# https://github.com/mozilla/mozci/issues/1145

from loguru import logger

from mozci.data.sources.treeherder import TreeherderClientSource
from mozci.push import Push
from mozci.task import Task


class MissingJobData(Exception):
    """A push could not be linked to a Treeherder job data"""


def fetch_treeherder_details(push: Push, **params):
    """
    IDs are different between treeherder & mozci (that uses HGMO reference).
    This fetch all treeherder attributes, available as `Push.treherder` dict.
    """
    if push.treeherder is not None:
        return

    client = TreeherderClientSource()
    url = f"{client.base_url}/project/{push.branch}/push/?count=1&revision={push.rev}"
    response = client.session.get(url, params=params)
    response.raise_for_status()
    results = response.json().get("results")
    if not results or not isinstance(results, list):
        raise ValueError(f"Treeherder data could not be fetched for rev {push.rev}.")
    push.treeherder = results[0]


def map_tasks_to_jobs(push: Push, **filters):
    """
    Map tasks from Taskcluster to jobs via the Treeherder API
    """
    if push.treeherder is None:
        fetch_treeherder_details(push)
    if not isinstance(push.treeherder, dict) or "id" not in push.treeherder:
        raise ValueError("Treeherder ID for the push is missing")

    client = TreeherderClientSource()

    jobs: list[dict] = []
    # page_size is set to 2000 by Treeherder, so one hit should be enough
    next_page: str | None = (
        f'{client.base_url}/jobs/?push_id={push.treeherder.get("id")}'
    )
    while next_page:
        url = next_page
        next_page = None
        response = client.session.get(url, params=filters)
        response.raise_for_status()
        data = response.json()
        # Map results to field names
        headers = data["job_property_names"]
        results = [
            {headers[i]: value for i, value in enumerate(job)}
            for job in data["results"]
        ]
        jobs.extend(results)
        next_page = data.get("next")

    errors = []
    for task in push.tasks:
        task.job = next((job for job in jobs if job["task_id"] == task.id), None)
        if task.job is None:
            errors.append(task.id)

    logger.info(
        f"Linked {len(push.tasks) - len(errors)}/{len(push.tasks)} tasks to jobs"
    )
    if errors:
        logger.warning(f"Some tasks could be linked to Treeherder jobs: {errors}")


def list_similar_jobs(task: Task, push: Push, **filters):
    if not getattr(task, "job", None):
        raise MissingJobData("You must fetch related job first")

    similar_jobs: list[dict] = []
    client = TreeherderClientSource()
    url = f"{client.base_url}/project/{push.branch}/jobs/{getattr(task, 'job')['id']}/similar_jobs/"
    page_size = 1000
    while True:
        response = client.session.get(
            url,
            params={
                "count": page_size,
                "offset": len(similar_jobs),
                **filters,
            },
        )
        response.raise_for_status()
        data = response.json()["results"]
        similar_jobs.extend(data)
        if len(data) < page_size:
            break

    return similar_jobs
