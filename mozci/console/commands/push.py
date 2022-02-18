# -*- coding: utf-8 -*-
import csv
import datetime
import json
import os
import re
from typing import List, Optional
from urllib.parse import urlencode

import arrow
import taskcluster
from cleo import Command
from loguru import logger
from tabulate import tabulate
from taskcluster.exceptions import TaskclusterRestFailure

from mozci import config
from mozci.errors import SourcesNotFound, TaskNotFound
from mozci.push import Push, PushStatus, Regressions, make_push_objects
from mozci.task import Task, TestTask
from mozci.util.taskcluster import (
    COMMUNITY_TASKCLUSTER_ROOT_URL,
    get_taskcluster_notify_service,
    get_taskcluster_options,
    notify_email,
    notify_matrix,
)

EMAIL_CLASSIFY_EVAL = """
# classify-eval report generated on the {today}

The report contains statistics about pushes that were classified by Mozci.

## Statistics for the {total} pushes that were evaluated

{error_line}

{stats}
"""

EMAIL_PUSH_EVOLUTION = """
# Push {push.id} evolved from {previous} to {current}

Rev: [{push.rev}](https://treeherder.mozilla.org/jobs?repo={branch}&revision={push.rev})

## Real failures

- {real_failures}

"""


class PushTasksCommand(Command):
    """
    List the tasks that ran on a push.

    tasks
        {rev : Head revision of the push.}
        {branch : Branch the push belongs to (e.g autoland, try, etc).}
    """

    def handle(self):
        push = Push(self.argument("rev"), self.argument("branch"))

        table = []
        for task in sorted(push.tasks, key=lambda t: t.label):
            table.append([task.label, task.result or "running"])

        self.line(tabulate(table, headers=["Label", "Result"]))


def classify_commands_pushes(
    branch: str, from_date: str, to_date: str, rev: str
) -> List[Push]:
    if not (bool(rev) ^ bool(from_date or to_date)):
        raise Exception(
            "You must either provide a single push revision with --rev or define at least --from-date option to classify a range of pushes (note: --to-date will default to current time if not given)."
        )

    if rev:
        pushes = [Push(rev, branch)]
    else:
        if not from_date:
            raise Exception(
                "You must provide at least --from-date to classify a range of pushes (note: --to-date will default to current time if not given)."
            )

        now = datetime.datetime.now()
        if not to_date:
            to_date = datetime.datetime.strftime(now, "%Y-%m-%d")

        arrow_now = arrow.get(now)
        try:
            datetime.datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            try:
                from_date = arrow_now.dehumanize(from_date).format("YYYY-MM-DD")
            except ValueError:
                raise Exception(
                    'Provided --from-date should be a date in yyyy-mm-dd format or a human expression like "1 days ago".'
                )

        try:
            datetime.datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            try:
                to_date = arrow_now.dehumanize(to_date).format("YYYY-MM-DD")
            except ValueError:
                raise Exception(
                    'Provided --to-date should be a date in yyyy-mm-dd format or a human expression like "1 days ago".'
                )

        pushes = make_push_objects(from_date=from_date, to_date=to_date, branch=branch)

    return pushes


class ClassifyCommand(Command):
    """
    Display the classification for a given push (or a range of pushes) as GOOD, BAD or UNKNOWN.

    classify
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
        {--rev= : Head revision of the push.}
        {--from-date= : Lower bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago").}
        {--to-date= : Upper bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago"), defaults to now.}
        {--medium-confidence=0.8 : Medium confidence threshold used to classify the regressions.}
        {--high-confidence=0.9 : High confidence threshold used to classify the regressions.}
        {--output= : Path towards a directory to save a JSON file containing classification and regressions details in.}
        {--show-intermittents : If set, print tasks that should be marked as intermittent.}
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}
    """

    def handle(self) -> None:
        self.branch = self.argument("branch")

        try:
            pushes = classify_commands_pushes(
                self.branch,
                self.option("from-date"),
                self.option("to-date"),
                self.option("rev"),
            )
        except Exception as error:
            self.line(f"<error>{error}</error>")
            return

        try:
            medium_conf = float(self.option("medium-confidence"))
        except ValueError:
            self.line("<error>Provided --medium-confidence should be a float.</error>")
            return
        try:
            high_conf = float(self.option("high-confidence"))
        except ValueError:
            self.line("<error>Provided --high-confidence should be a float.</error>")
            return

        output = self.option("output")
        if output and not os.path.isdir(output):
            os.makedirs(output)
            self.line(
                "<comment>Provided --output pointed to a inexistent directory that is now created.</comment>"
            )

        for push in pushes:
            try:
                classification, regressions = push.classify(
                    intermittent_confidence_threshold=medium_conf,
                    real_confidence_threshold=high_conf,
                )
                self.line(
                    f"Push associated with the head revision {push.rev} on "
                    f"the branch {self.branch} is classified as {classification.name}"
                )
            except Exception as e:
                self.line(
                    f"<error>Couldn't classify push {push.push_uuid}: {e}.</error>"
                )
                continue

            if self.option("show-intermittents"):
                self.line("-" * 50)
                self.line(
                    "Printing tasks that should be marked as intermittent failures:"
                )
                for task in regressions.intermittent:
                    self.line(task)
                self.line("-" * 50)

            if output:
                to_save = {
                    "push": {
                        "id": push.push_uuid,
                        "classification": classification.name,
                    },
                    "failures": {
                        "real": {
                            group: [
                                {"task_id": task.id, "label": task.label}
                                for task in failing_tasks
                            ]
                            for group, failing_tasks in regressions.real.items()
                        },
                        "intermittent": {
                            group: [
                                {"task_id": task.id, "label": task.label}
                                for task in failing_tasks
                            ]
                            for group, failing_tasks in regressions.intermittent.items()
                        },
                        "unknown": {
                            group: [
                                {"task_id": task.id, "label": task.label}
                                for task in failing_tasks
                            ]
                            for group, failing_tasks in regressions.unknown.items()
                        },
                    },
                }

                filename = f"{output}/classify_output_{self.branch}_{push.rev}.json"
                with open(filename, "w") as file:
                    json.dump(to_save, file, indent=2)

                self.line(
                    f"Classification and regressions details for push {push.push_uuid} were saved in {filename} JSON file"
                )

            # Send a notification when some emails are declared in the config
            emails = config.get("emails", {}).get("classifications")
            matrix_room = config.get("matrix-room-id", None)
            if emails or matrix_room:
                # Load previous classification from taskcluster
                try:
                    previous = push.get_existing_classification(
                        self.option("environment")
                    )
                except SourcesNotFound:
                    # We still want to send a notification if the current one is bad
                    previous = None

                self.send_notifications(
                    emails, matrix_room, push, previous, classification, regressions
                )

    def send_notifications(
        self,
        emails: Optional[List[str]],
        matrix_room: Optional[str],
        push: Push,
        previous: Optional[PushStatus],
        current: PushStatus,
        regressions: Regressions,
    ) -> None:
        """
        Send an email and/or a matrix notification when:
        - there is no previous classification and the new classification is BAD;
        - the previous classification was GOOD or UNKNOWN and the new classification is BAD;
        - or the previous classification was BAD and the new classification is GOOD or UNKNOWN.
        """

        def _get_task_url(task: TestTask):
            """Helper to build a treeherder link for a task"""
            assert task.id is not None
            params = {
                "repo": self.branch,
                "revision": push.rev,
                "selectedTaskRun": f"{task.id}-0",
            }

            return f"https://treeherder.mozilla.org/#/jobs?{urlencode(params)}"

        def _get_group_url(group: str):
            """Helper to build a treeherder link for a group"""
            params = {"repo": self.branch, "tochange": push.rev, "test_paths": group}
            return f"https://treeherder.mozilla.org/#/jobs?{urlencode(params)}"

        def _list_tasks(tasks):
            """Helper to build a list of all tasks in a group, with their treeherder url"""
            if not tasks:
                return "No tasks available"

            return ", ".join(
                [f"[{task.label}]({_get_task_url(task)})" for task in tasks]
            )

        if (
            previous in (None, PushStatus.GOOD, PushStatus.UNKNOWN)
            and current == PushStatus.BAD
        ) or (
            previous == PushStatus.BAD
            and current in (PushStatus.GOOD, PushStatus.UNKNOWN)
        ):
            notify = get_taskcluster_notify_service()
            email_content = EMAIL_PUSH_EVOLUTION.format(
                previous=previous.name if previous else "no classification",
                current=current.name,
                push=push,
                branch=self.branch,
                real_failures="\n- ".join(
                    [
                        f"Group [{group}]({_get_group_url(group)}) - Tasks {_list_tasks(tasks)}"
                        for group, tasks in regressions.real.items()
                    ]
                ),
            )
            if emails:
                notify_email(
                    notify_service=notify,
                    emails=emails,
                    subject=f"Push status evolution {push.id} {push.rev[:8]}",
                    content=email_content,
                )
            if matrix_room:
                notify_matrix(
                    notify_service=notify,
                    room=matrix_room,
                    body=email_content,
                )


class ClassifyEvalCommand(Command):
    """
    Evaluate the classification results for a given push (or a range of pushes) by comparing them with reality.

    classify-eval
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
        {--rev= : Head revision of the push.}
        {--from-date= : Lower bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago").}
        {--to-date= : Upper bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago"), defaults to now.}
        {--medium-confidence= : If recalculate parameter is set, medium confidence threshold used to classify the regressions.}
        {--high-confidence= : If recalculate parameter is set, high confidence threshold used to classify the regressions.}
        {--recalculate : If set, recalculate the classification instead of fetching an artifact.}
        {--output= : Path towards a path to save a CSV file with classification states for various pushes.}
        {--send-email : If set, also send the evaluation report by email instead of just logging it.}
        {--detailed-classifications : If set, compare real/intermittent group classifications with Sheriff's ones.}
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}
    """

    def handle(self) -> None:
        branch = self.argument("branch")

        try:
            self.line("<comment>Loading pushes...</comment>")
            self.pushes = classify_commands_pushes(
                branch,
                self.option("from-date"),
                self.option("to-date"),
                self.option("rev"),
            )
        except Exception as error:
            self.line(f"<error>{error}</error>")
            return

        if self.option("recalculate"):
            try:
                medium_conf = (
                    float(self.option("medium-confidence"))
                    if self.option("medium-confidence")
                    else 0.8
                )
            except ValueError:
                self.line(
                    "<error>Provided --medium-confidence should be a float.</error>"
                )
                return
            try:
                high_conf = (
                    float(self.option("high-confidence"))
                    if self.option("high-confidence")
                    else 0.9
                )
            except ValueError:
                self.line(
                    "<error>Provided --high-confidence should be a float.</error>"
                )
                return
        elif self.option("medium-confidence") or self.option("high-confidence"):
            self.line(
                "<error>--recalculate isn't set, you shouldn't provide either --medium-confidence nor --high-confidence attributes.</error>"
            )
            return

        # Progress bar will display time stats & messages
        progress = self.progress_bar(len(self.pushes))
        progress.set_format(
            " %current%/%max% [%bar%] %percent:3s%% %elapsed:6s% %message%"
        )

        self.errors = {}
        self.classifications = {}
        self.failures = {}
        for push in self.pushes:
            if self.option("recalculate"):
                progress.set_message(f"Calc. {branch} {push.id}")

                # Pretend no tasks were classified to run the model without any outside help.
                old_classifications = {}
                for task in push.tasks:
                    old_classifications[task.id] = {
                        "classification": task.classification,
                        "note": task.classification_note,
                    }
                    task.classification = "not classified"
                    task.classification_note = None

                try:
                    self.classifications[push], regressions = push.classify(
                        intermittent_confidence_threshold=medium_conf,
                        real_confidence_threshold=high_conf,
                    )
                    self.failures[push] = {
                        "real": regressions.real,
                        "intermittent": regressions.intermittent,
                        "unknown": regressions.unknown,
                    }
                except Exception as e:
                    self.line(
                        f"<error>Classification failed on {branch} {push.rev}: {e}</error>"
                    )
                    self.errors[push] = e

                # Once the Mozci algorithm has run, restore Sheriffs classifications to be able to properly compare failures classifications.
                for task in push.tasks:
                    task.classification = old_classifications[task.id]["classification"]
                    task.classification_note = old_classifications[task.id]["note"]
            else:
                progress.set_message(f"Fetch {branch} {push.id}")
                try:
                    index = f"project.mozci.classification.{branch}.revision.{push.rev}"
                    task = Task.create(
                        index=index, root_url=COMMUNITY_TASKCLUSTER_ROOT_URL
                    )

                    artifact = task.get_artifact(
                        "public/classification.json",
                        root_url=COMMUNITY_TASKCLUSTER_ROOT_URL,
                    )
                    self.classifications[push] = PushStatus[
                        artifact["push"]["classification"]
                    ]
                    self.failures[push] = artifact["failures"]
                except TaskNotFound as e:
                    self.line(
                        f"<comment>Taskcluster task missing for {branch} {push.rev}</comment>"
                    )
                    self.errors[push] = e

                except Exception as e:
                    self.line(
                        f"<error>Fetch failed on {branch} {push.rev}: {e}</error>"
                    )
                    self.errors[push] = e

            # Advance the overall progress bar
            progress.advance()

        # Conclude the progress bar
        progress.finish()
        print("\n")

        error_line = ""
        if self.errors:
            error_line = f"Failed to fetch or recalculate classification for {len(self.errors)} out of {len(self.pushes)} pushes."
            self.line(f"<error>{error_line}</error>")

        stats = [
            self.log_pushes(PushStatus.BAD, False),
            self.log_pushes(PushStatus.BAD, True),
            self.log_pushes(PushStatus.GOOD, False),
            self.log_pushes(PushStatus.GOOD, True),
            self.log_pushes(PushStatus.UNKNOWN, False),
            self.log_pushes(PushStatus.UNKNOWN, True),
        ]

        if self.option("detailed-classifications"):
            self.line("\n")

            real_stats = intermittent_stats = {
                "total": 0,
                "correct": 0,
                "wrong": 0,
                "pending": 0,
                "conflicting": 0,
                "missed": 0,
            }
            for push in self.pushes:
                self.line(
                    f"<comment>Printing detailed classifications comparison for push {push.branch}/{push.rev}</comment>"
                )

                # Compare real failures that were predicted by mozci with the ones classified by Sheriffs
                try:
                    sheriff_reals = set()
                    # Get likely regressions of this push
                    likely_regressions = push.get_likely_regressions("group", True)
                    # Only consider groups that were classified as "fixed by commit" to exclude likely regressions mozci found via heuristics.
                    for other in push._iterate_children():
                        for name, group in other.group_summaries.items():
                            classifications = set([c for c, _ in group.classifications])
                            if (
                                classifications == {"fixed by commit"}
                                and name in likely_regressions
                            ):
                                sheriff_reals.add(name)
                except Exception:
                    self.line(
                        "<error>Failed to retrieve Sheriff classifications for the real failures of this push.</error>"
                    )

                try:
                    push_real_stats = self.log_details(
                        push,
                        "real",
                        sheriff_reals,
                        {"fixed by commit"},
                    )
                    real_stats = {
                        key: value + push_real_stats[key]
                        for key, value in real_stats.items()
                    }
                except Exception:
                    self.line(
                        "<error>Failed to compare true and predicted real failures of this push.</error>"
                    )

                # Compare intermittent failures that were predicted by mozci with the ones classified by Sheriffs
                try:
                    sheriff_intermittents = set()
                    for name, group in push.group_summaries.items():
                        classifications = set([c for c, _ in group.classifications])
                        if classifications == {"intermittent"}:
                            sheriff_intermittents.add(name)
                except Exception:
                    self.line(
                        "<error>Failed to retrieve Sheriff classifications for the intermittent failures of this push.</error>"
                    )

                try:
                    push_intermittent_stats = self.log_details(
                        push,
                        "intermittent",
                        sheriff_intermittents,
                        {"intermittent"},
                    )
                    intermittent_stats = {
                        key: value + push_intermittent_stats[key]
                        for key, value in intermittent_stats.items()
                    }
                except Exception:
                    self.line(
                        "<error>Failed to compare true and predicted intermittent failures of this push.</error>"
                    )

            self.line(
                f"\n<comment>Printing overall detailed classifications comparison for {len(self.pushes)} pushes</comment>"
            )
            detailed_stats = [
                f"{real_stats['correct']} out of {real_stats['total']} real failures were correctly classified ('fixed by commit' by Sheriffs).",
                f"{real_stats['wrong']} out of {real_stats['total']} real failures were wrongly classified ('intermittent' by Sheriffs).",
                f"{real_stats['pending']} out of {real_stats['total']} real failures are waiting to be classified by Sheriffs.",
                f"{real_stats['conflicting']} out of {real_stats['total']} real failures have conflicting classifications applied by Sheriffs.",
                f"{real_stats['missed']} real failures were missed or classified as unknown by Mozci.",
                f"{intermittent_stats['correct']} out of {intermittent_stats['total']} intermittent failures were correctly classified ('intermittent' by Sheriffs).",
                f"{intermittent_stats['wrong']} out of {intermittent_stats['total']} intermittent failures were wrongly classified ('fixed by commit' by Sheriffs).",
                f"{intermittent_stats['pending']} out of {intermittent_stats['total']} intermittent failures are waiting to be classified by Sheriffs.",
                f"{intermittent_stats['conflicting']} out of {intermittent_stats['total']} intermittent failures have conflicting classifications applied by Sheriffs.",
                f"{intermittent_stats['missed']} intermittent failures were missed or classified as unknown by Mozci.",
            ]
            for line in detailed_stats:
                self.line(line)

            stats += detailed_stats

        if self.option("send-email"):
            self.send_emails(len(self.pushes), stats, error_line)

        output = self.option("output")
        if output:
            # Build stats for CSV
            with open(output, "w") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "revision",
                        "date",
                        "classification",
                        "backedout",
                        "error_type",
                        "error_message",
                    ],
                )
                writer.writeheader()
                writer.writerows([self.build_stats(push) for push in self.pushes])
            self.line(
                f"<info>Written stats for {len(self.pushes)} pushes in {output}</info>"
            )

    def build_stats(self, push):
        """
        Build a dict with statistics relevant for a push
        """
        classification = self.classifications.get(push)
        error = self.errors.get(push)

        return {
            "revision": push.rev,
            "date": push.date,
            "classification": classification or "error",
            "backedout": push.backedout if classification else "",
            "error_type": error.__class__.__name__ if error else "",
            "error_message": str(error) if error else "",
        }

    def log_pushes(self, status, backedout):
        """
        Display stats for all pushes in a given classification state + backout combination
        """
        assert isinstance(status, PushStatus)
        assert isinstance(backedout, bool)

        nb = len(
            [
                push
                for push in self.pushes
                if self.classifications.get(push) == status
                and push.backedout == backedout
            ]
        )
        verb = "were" if backedout else "weren't"
        line = f"{nb} out of {len(self.pushes)} pushes {verb} backed-out by a sheriff and were classified as {status.name}."
        self.line(line)

        return line

    def send_emails(self, total, stats, error_line):

        today = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d")

        stats = "\n".join([f"- {stat}" for stat in stats])

        notify_email(
            emails=config.get("emails", {}).get("monitoring"),
            subject=f"classify-eval report generated the {today}",
            content=EMAIL_CLASSIFY_EVAL.format(
                today=today,
                total=total,
                error_line=f"**{error_line}**" if error_line else "",
                stats=stats,
            ),
        )

    def log_details(self, push, state, sheriff_groups, expected):
        predicted_groups = (
            self.failures[push][state].keys() if self.failures.get(push) else []
        )
        total = len(predicted_groups)

        if not total:
            if sheriff_groups:
                self.line(
                    f"{len(sheriff_groups)} groups were classified as {state} by Sheriffs and missed by Mozci, missed groups:"
                )
                self.line("  - " + "\n  - ".join(sheriff_groups))

            return {
                "total": 0,
                "correct": 0,
                "wrong": 0,
                "pending": 0,
                "conflicting": 0,
                "missed": len(sheriff_groups),
            }

        conflicting = []
        differing = []
        pending = []
        missed = []
        for group in predicted_groups:
            classifications_set = set(
                [c for c, _ in push.group_summaries[group].classifications]
            )
            if classifications_set == {"not classified"}:
                pending.append(group)
            elif len(classifications_set) != 1:
                conflicting.append(group)
            elif classifications_set != expected:
                differing.append(group)

        for group in sheriff_groups:
            if group not in predicted_groups:
                missed.append(group)

        correct = total - len(conflicting) - len(differing) - len(pending)
        self.line(
            f"{correct} out of {total} {state} groups were also classified as {state} by Sheriffs."
        )
        if differing:
            self.line(
                f"{len(differing)} out of {total} {state} groups weren't classified as {state} by Sheriffs, differing groups:"
            )
            self.line("  - " + "\n  - ".join(differing))
        if pending:
            self.line(
                f"{len(pending)} out of {total} {state} groups are waiting to be classified by Sheriffs."
            )
        if conflicting:
            self.line(
                f"{len(conflicting)} out of {total} {state} groups have conflicting classifications applied by Sheriffs, inconsistent groups:"
            )
            self.line("  - " + "\n  - ".join(conflicting))
        if missed:
            self.line(
                f"{len(missed)} groups were classified as {state} by Sheriffs and missed (or classified as unknown) by Mozci, missed groups:"
            )
            self.line("  - " + "\n  - ".join(missed))

        return {
            "total": total,
            "correct": correct,
            "wrong": len(differing),
            "pending": len(pending),
            "conflicting": len(conflicting),
            "missed": len(missed),
        }


class ClassifyPerfCommand(Command):
    """
    Generate a CSV file with performance stats for all classification tasks

    perf
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}
        {--output=perfs.csv: Output CSV file path}
    """

    REGEX_ROUTE = re.compile(
        r"^index.project.mozci.classification.([\w\-]+).(revision|push).(\w+)$"
    )

    def handle(self) -> None:
        environment = self.option("environment")
        output = self.option("output")

        # Aggregate stats for completed tasks processed by the hook
        stats = [
            self.parse_task_status(task_status)
            for group_id in self.list_groups_from_hook(
                "project-mozci", f"decision-task-{environment}"
            )
            for task_status in self.list_classification_tasks(group_id)
        ]

        # Dump stats as CSV file
        with open(output, "w") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=[
                    "branch",
                    "push",
                    "revision",
                    "task_id",
                    "created",
                    "time_taken",
                ],
            )
            writer.writeheader()
            writer.writerows(stats)

        self.line(f"<info>Written stats for {len(stats)} tasks in {output}</info>")

    def parse_routes(self, routes):
        """Find revision from task routes"""

        def _match(route):
            res = self.REGEX_ROUTE.search(route)
            if res:
                return res.groups()

        # Extract branch+name+value from the routes
        # and get 3 separated lists to check those values
        branches, keys, values = zip(*filter(None, map(_match, routes)))

        # We should only have one branch
        branches = set(branches)
        assert len(branches) == 1, f"Multiple branches detected: {branches}"

        # Output single branch, revision and push id
        data = dict(zip(keys, values))
        assert "revision" in data, "Missing revision route"
        assert "push" in data, "Missing push route"
        return branches.pop(), data["revision"], int(data["push"])

    def parse_task_status(self, task_status):
        """Extract identification and time spent for each classification task"""

        def date(x):
            return datetime.datetime.strptime(x, "%Y-%m-%dT%H:%M:%S.%fZ")

        out = {
            "task_id": task_status["status"]["taskId"],
            "created": task_status["task"]["created"],
            "time_taken": sum(
                (date(run["resolved"]) - date(run["started"])).total_seconds()
                for run in task_status["status"]["runs"]
                if run["state"] == "completed"
            ),
        }
        out["branch"], out["revision"], out["push"] = self.parse_routes(
            task_status["task"]["routes"]
        )
        return out

    def list_groups_from_hook(self, group_id, hook_id):
        """List all decision tasks from the specified hook"""
        hooks = taskcluster.Hooks(get_taskcluster_options())
        fires = hooks.listLastFires(group_id, hook_id).get("lastFires", [])

        # Setup CLI progress bar
        progress = self.progress_bar(len(fires))
        progress.set_format("verbose")

        # Provide the decision task ID as it's the same value for group ID
        for fire in fires:
            yield fire["taskId"]

            progress.advance()

        # Cleanup progress bar
        progress.finish()

    def list_classification_tasks(self, group_id):

        # Check cache first
        cache_key = f"perf/task_group/{group_id}"
        tasks = config.cache.get(cache_key, [])

        if not tasks:
            queue = taskcluster.Queue(get_taskcluster_options())
            token = False
            try:
                # Support pagination using continuation token
                while token is not None:
                    query = {"continuationToken": token} if token else {}
                    results = queue.listTaskGroup(group_id, query=query)
                    tasks += results.get("tasks")
                    token = results.get("continuationToken")
            except TaskclusterRestFailure as e:
                # Skip expired task groups
                if e.status_code == 404:
                    return

                raise
        else:
            logger.debug("From cache", cache_key)

        for task_status in tasks:
            task_id = task_status["status"]["taskId"]

            # Skip decision task
            if task_id == group_id:
                continue

            # Only provide completed tasks
            if task_status["status"]["state"] != "completed":
                logger.debug(f"Skip not completed task {task_id}")
                continue

            yield task_status

        # Cache all tasks if all completed
        if all(t["status"]["state"] == "completed" for t in tasks):
            config.cache.add(cache_key, tasks, int(config["cache"]["retention"]))


class PushCommands(Command):
    """
    Contains commands that operate on a single push.

    push
    """

    commands = [
        PushTasksCommand(),
        ClassifyCommand(),
        ClassifyEvalCommand(),
        ClassifyPerfCommand(),
    ]

    def handle(self):
        return self.call("help", self._config.name)
