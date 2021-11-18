# -*- coding: utf-8 -*-

import os
from datetime import datetime

import taskcluster
from cleo import Command

from mozci import data
from mozci.push import Push
from mozci.util.memoize import memoized_property
from mozci.util.taskcluster import get_proxy_queue


class DecisionCommand(Command):
    """
    Taskcluster decision task to generate classification tasks

    decision
        {branch=mozilla-central : Branch the push belongs to (e.g autoland, try, etc).}
        {--dry-run : Do not create tasks on taskcluster, simply output actions.}
    """

    def handle(self):
        branch = self.argument("branch")
        dry_run = self.option("dry-run")

        self.queue = not dry_run and get_proxy_queue() or None

        self.line(f"Process pushes from {branch}")

        # List pushes
        pushes = data.handler.get(
            "pushes",
            branch=branch,
        )

        for push in pushes:

            # TODO: detect if a classification is already available
            # and can be skipped

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
            "created": taskcluster.stringDate(datetime.utcnow()),
            "deadline": taskcluster.stringDate(taskcluster.fromNow("1 hour")),
            "dependencies": [
                self.current_task["id"],
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
                "command": [
                    "push",
                    "classify",
                    push.branch,
                    f"--rev={push.rev}",
                ],
            },
            "provisionerId": self.current_task["provisionerId"],
            "workerType": self.current_task["workerType"],
        }

        self.queue.createTask(task_id, task)

        return task_id
