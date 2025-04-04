# -*- coding: utf-8 -*-

from cleo.commands.command import Command
from cleo.helpers import argument, option
from loguru import logger

from mozci.push import Push
from mozci.task import Task
from mozci.util.treeherder import MissingJobData, list_similar_jobs, map_tasks_to_jobs


class RegressionCommand(Command):
    name = "regression"
    description = "Identify if a build bustage is a regression from a check-in"
    arguments = [
        argument("rev", description="Head revision of the push."),
    ]
    options = [
        option(
            "max-results",
            flag=False,
            default=None,
            description="Maximum number of tasks to analyse.",
        ),
    ]

    def identify_regression(self, push: Push, task: Task):
        """
        Look for previous occurrences of a similar error based on Treeherder API
        """
        try:
            # Look for a similar job on previous pushes, until we found one that ran successfully
            jobs = list_similar_jobs(task, push)
        except MissingJobData:
            return []
        # TODO: Identify the last successful run of the same job type, then count pushes difference
        return jobs

    def identify_regression_mozci(self, push: Push, task: Task):
        """
        Look for previous occurrences of a similar error based on HGMO API
        """
        # TODO
        return []

    def handle(self):
        # Initiate push from its head revision, forcing autoland branch
        rev = self.argument("rev")
        max_results = self.option("max-results")

        push = Push(rev, branch="autoland")
        logger.info(f"Fetched {len(push.tasks)} tasks")

        # First link tasks to jobs via Treeherder
        map_tasks_to_jobs(push)
        # Filter out tasks that are missing a job
        push.tasks = [task for task in push.tasks if getattr(task, "job", None)]
        # TODO Exclude tasks that are not a candidate
        # push.tasks = [
        #    task
        #    for task in push.tasks
        #    if task.is_potential_regression
        # ]
        if max_results:
            if not max_results.isdigit():
                raise ValueError("--max-results must contain only digits")
            push.tasks = push.tasks[: int(max_results)]
        logger.info(f"Kept {len(push.tasks)} tasks that are potential regressions")

        # Try to identify a potential regressions from the failed build
        regressions = [
            (
                task,
                len(self.identify_regression(push, task)),
                len(self.identify_regression_mozci(push, task)),
            )
            for task in push.tasks
        ]

        # Debug
        table = self.table()
        table.set_headers(
            ["ID", "Label", "Similar count (treeherder)", "Similar count (mozci)"]
        )
        table.set_rows(
            [
                (task.id, task.label, str(treeherder_count), str(mozci_count))
                for task, treeherder_count, mozci_count in regressions
            ]
        )
        table.render()
