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
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
        {--nb-pushes=15 : Do not create tasks on taskcluster, simply output actions.}
        {--dry-run : Do not create tasks on taskcluster, simply output actions.}
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}
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
        environment = self.option("environment")

        # Expose non-production environment in sub routes
        route_prefix = (
            "index.project.mozci.classification"
            if environment == "production"
            else f"index.project.mozci.{environment}.classification"
        )

        task_id = taskcluster.slugId()
        task = {
            "taskGroupId": self.current_task["taskGroupId"],
            "created": taskcluster.stringDate(datetime.utcnow()),
            "deadline": taskcluster.stringDate(taskcluster.fromNow("1 hour")),
            "dependencies": [
                self.current_task["id"],
            ],
            "scopes": [
                f"docker-worker:cache:mozci-classifications-{environment}",
                f"secrets:get:project/mozci/{environment}",
                "queue:route:notify.email.release-mgmt-analysis@mozilla.com.on-failed",
                "notify:email:*",
                "notify:matrix-room:!vNAdpBnFtfGfispLtR:mozilla.org",
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
                    "TASKCLUSTER_CONFIG_SECRET": f"project/mozci/{environment}",
                },
                "features": {
                    "taskclusterProxy": True,
                },
                "command": [
                    "push",
                    "classify",
                    push.branch,
                    f"--rev={push.rev}",
                    "--output=/tmp",
                    f"--environment={environment}",
                ],
                "cache": {
                    f"mozci-classifications-{environment}": "/cache",
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
                f"{route_prefix}.{push.branch}.revision.{push.rev}",
                f"{route_prefix}.{push.branch}.push.{push.id}",
                "notify.email.release-mgmt-analysis@mozilla.com.on-failed",
            ],
            "provisionerId": self.current_task["provisionerId"],
            "workerType": self.current_task["workerType"],
        }

        self.queue.createTask(task_id, task)

        return task_id
