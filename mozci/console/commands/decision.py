# -*- coding: utf-8 -*-

import os
from datetime import datetime

import taskcluster
from cleo import Command

from mozci.push import Push, make_push_objects
from mozci.util.memoize import memoized_property
from mozci.util.taskcluster import get_taskcluster_options


class DecisionCommand(Command):
    """
    Taskcluster decision task to generate classification tasks

    decision
        {branch=mozilla-central : Branch the push belongs to (e.g autoland, try, etc).}
        {--nb-pushes=15 : Do not create tasks on taskcluster, simply output actions.}
        {--dry-run : Do not create tasks on taskcluster, simply output actions.}
    """

    def handle(self):
        branch = self.argument("branch")
        dry_run = self.option("dry-run")
        nb_pushes = int(self.option("nb-pushes"))

        self.queue = (
            not dry_run and taskcluster.Queue(get_taskcluster_options()) or None
        )

        self.line(f"Process pushes from {branch}")

        # List most recent pushes
        for push in make_push_objects(nb=nb_pushes, branch=branch):

            if dry_run:
                self.line(f"Would classify {push.branch}@{push.rev}")
                continue

            # Create a child task to classify that push
            task_id = self.create_task(push)
            self.line(f"<info>Created task {task_id}</info>")

    @memoized_property
    def current_task(self):
        """
        Load the current task definition so that the children tasks
        use the same image and workers
        """
        assert self.queue is not None, "Missing taskcluster queue"

        task_id = os.environ.get("TASK_ID")
        if not task_id:
            raise Exception("Not in a Taskcluster environment")

        task = self.queue.task(task_id)
        task["id"] = task_id

        return task

    def create_task(self, push: Push) -> str:
        """
        Create a children task linked to the current task
        that will classify a single push
        """
        task_id = taskcluster.slugId()
        task = {
            "taskGroupId": self.current_task["taskGroupId"],
            "created": taskcluster.stringDate(datetime.utcnow()),
            "deadline": taskcluster.stringDate(taskcluster.fromNow("1 hour")),
            "dependencies": [
                self.current_task["id"],
            ],
            "scopes": [
                "docker-worker:cache:mozci-classifications-testing",
                "secrets:get:project/mozci/testing",
            ],
            "metadata": {
                "name": f"mozci classify {push.branch}@{push.rev}",
                "description": "mozci classification task",
                "owner": "mcastelluccio@mozilla.com",
                "source": "https://github.com/mozilla/mozci",
            },
            "payload": {
                "maxRunTime": 3600,
                "image": self.current_task["payload"]["image"],
                "env": {
                    "TASKCLUSTER_CONFIG_SECRET": "project/mozci/testing",
                },
                "command": [
                    "push",
                    "classify",
                    push.branch,
                    f"--rev={push.rev}",
                    "--output=/tmp",
                ],
                "cache": {
                    "mozci-classifications-testing": "/cache",
                },
                "artifacts": {
                    "public/classification.json": {
                        "expires": taskcluster.stringDate(
                            taskcluster.fromNow("3 months")
                        ),
                        "path": f"/tmp/classify_output_{push.branch}_{push.rev}.json",
                        "type": "file",
                    }
                },
            },
            "routes": [
                f"index.project.mozci.classification.{push.branch}.revision.{push.rev}",
                f"index.project.mozci.classification.{push.branch}.push.{push.id}",
            ],
            "provisionerId": self.current_task["provisionerId"],
            "workerType": self.current_task["workerType"],
        }

        self.queue.createTask(task_id, task)

        return task_id
