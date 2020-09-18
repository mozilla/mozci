# -*- coding: utf-8 -*-

from collections import defaultdict

from loguru import logger

from mozci.data.base import DataSource

try:
    from treeherder.model.models import Job
except ImportError:
    Job = None


class TreeherderSource(DataSource):
    """Uses ORM to query Treeherder."""

    name = "treeherder"
    supported_contracts = (
        "push_tasks",
        "push_tasks_tags",
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

            result = {
                "id": str(task_id),
                "label": job.job_type.name,
                "result": job.result,
                "classification": job.failure_classification.name,
                "classification_note": note,
                "duration": Job.get_duration(
                    job.submit_time, job.start_time, job.end_time
                ),
            }
            items.append(result)
        return items

    def run_push_tasks(self, **kwargs):
        if Job:
            jobs = (
                Job.objects.filter(
                    push__revision=kwargs["rev"], repository__name=kwargs["branch"]
                )
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

            tasks = []

            for task in self.normalize(jobs):
                if task.get("tags"):
                    task["tags"] = {t["name"]: t["value"] for t in task["tags"]}

                tasks.append(task)
            return tasks

        logger.trace(
            "Unable to reach Treeherder as a datasource because the Job model "
            "was not available to import."
        )
        return []

    def run_push_tasks_tags(self, **kwargs):
        # These are not needed for Push Health
        return {}
