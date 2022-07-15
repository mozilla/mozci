# -*- coding: utf-8 -*-
import collections
import csv
import datetime
import fnmatch
import itertools
import json
import os
import re
import traceback
from inspect import signature
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import arrow
import taskcluster
from cleo import Command
from clikit.api.args.exceptions import NoSuchOptionException
from loguru import logger
from tabulate import tabulate
from taskcluster.exceptions import TaskclusterRestFailure

from mozci import config
from mozci.errors import PushNotFound, SourcesNotFound, TaskNotFound
from mozci.push import (
    MAX_DEPTH,
    Push,
    PushStatus,
    Regressions,
    ToRetriggerOrBackfill,
    make_push_objects,
)
from mozci.task import Task, TestTask, is_autoclassifiable
from mozci.util.defs import INTERMITTENT_CLASSES
from mozci.util.hgmo import HgRev
from mozci.util.taskcluster import (
    COMMUNITY_TASKCLUSTER_ROOT_URL,
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

Rev: [{push.rev}](https://treeherder.mozilla.org/jobs?repo={branch}&revision={push.rev})\n
Author: {push.author}\n
Time: {date}

## Real failures

- {real_failures}

"""

TWO_INTS_TUPLE_REGEXP = r"^\((\d+), ?(\d+)\)$"


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


def check_type(parameter_type, hint, value):
    try:
        if parameter_type == bool:
            parameter = value not in [False, 0, "0", "False", "false", "f"]
        elif parameter_type == Optional[Tuple[int, int]]:
            match = re.match(TWO_INTS_TUPLE_REGEXP, value)

            if not match or len(match.groups()) != 2:
                raise ValueError

            parameter = tuple([int(number) for number in match.groups()])
        else:
            parameter = parameter_type(value)
    except ValueError:
        raise Exception(
            f"Provided {hint} should be a {parameter_type.__name__ if hasattr(parameter_type, '__name__') else parameter_type}."
        )

    return parameter


def retrieve_classify_parameters(options):
    default_parameters = []
    for name, parameter in signature(Push.classify).parameters.items():
        if name != "self":
            default_parameters.append(parameter)

    classify_parameters = {}
    for parameter in default_parameters:
        parameter_name = parameter.name
        parameter_type = parameter.annotation
        option_name = parameter_name.replace("_", "-")
        try:
            option = options(option_name)
        except NoSuchOptionException:
            option = None

        if config.get(parameter_name) is not None and option is not None:
            raise Exception(
                f"You should provide either --{option_name} CLI option OR '{parameter_name}' in the config secret not both."
            )

        if config.get(parameter_name) is not None:
            classify_parameters[parameter_name] = check_type(
                parameter_type,
                f"'{parameter_name}' in the config secret",
                config[parameter_name],
            )
        elif option is not None:
            classify_parameters[parameter_name] = check_type(
                parameter_type, f"--{option_name}", option
            )

    return classify_parameters


class ClassifyCommand(Command):
    """
    Display the classification for a given push (or a range of pushes) as GOOD, BAD or UNKNOWN.

    classify
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
        {--rev= : Head revision of the push.}
        {--from-date= : Lower bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago").}
        {--to-date= : Upper bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago"), defaults to now.}
        {--intermittent-confidence-threshold= : Medium confidence threshold used to classify the regressions.}
        {--real-confidence-threshold= : High confidence threshold used to classify the regressions.}
        {--use-possible-regressions= : Use possible regressions while classifying the regressions.}
        {--unknown-from-regressions= : Unknown from regressions while classifying the regressions.}
        {--consider-children-pushes-configs= : Consider children pushes configs while classifying the regressions.}
        {--cross-config-counts= : Cross-config counts used to classify the regressions.}
        {--consistent-failures-counts= : Consistent failures counts used to classify the regressions.}
        {--output= : Path towards a directory to save a JSON file containing classification and regressions details in.}
        {--show-intermittents : If set, print tasks that should be marked as intermittent.}
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}
        {--retrigger-limit=3 : Number of failing groups (missing information) to be retriggered, defaults to 3.}
        {--backfill-limit=3 : Number of failing groups (missing information) to be backfilled, defaults to 3.}
    """

    def handle(self) -> None:
        self.branch = self.argument("branch")

        pushes = classify_commands_pushes(
            self.branch,
            self.option("from-date"),
            self.option("to-date"),
            self.option("rev"),
        )
        classify_parameters = retrieve_classify_parameters(self.option)

        output = self.option("output")
        if output and not os.path.isdir(output):
            os.makedirs(output)
            self.line(
                "<comment>Provided --output pointed to a inexistent directory that is now created.</comment>"
            )

        retriggerable_backfillable_patterns = config.get(
            "retriggerable-backfillable-task-names", []
        )

        try:
            retrigger_limit = int(self.option("retrigger-limit"))
        except ValueError:
            raise Exception("Provided --retrigger-limit should be an int.")

        try:
            backfill_limit = int(self.option("backfill-limit"))
        except ValueError:
            raise Exception("Provided --backfill-limit should be an int.")

        for push in pushes:
            try:
                classification, regressions, to_retrigger_or_backfill = push.classify(
                    **classify_parameters
                )

                self.backfill_and_retrigger_failures(
                    push,
                    retriggerable_backfillable_patterns,
                    classify_parameters,
                    retrigger_limit,
                    backfill_limit,
                    to_retrigger_or_backfill,
                )

                self.line(
                    f"Push associated with the head revision {push.rev} on "
                    f"the branch {self.branch} is classified as {classification.name}"
                )
            except Exception as e:
                self.line(
                    f"<error>Couldn't classify push {push.push_uuid}: {e}.</error>"
                )
                # Print the error stacktrace in red
                self.line(f"<error>{traceback.format_exc()}</error>")
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

                def _serialize_regressions(regressions):
                    return {
                        group: [
                            {
                                "task_id": task.id,
                                "label": task.label,
                                "autoclassify": is_autoclassifiable(task),
                                "tests": [
                                    test_name
                                    for group_failures in task.failure_types.values()
                                    for test_name, _ in group_failures
                                ],
                            }
                            for task in failing_tasks
                        ]
                        for group, failing_tasks in regressions.items()
                    }

                to_save = {
                    "push": {
                        "id": push.push_uuid,
                        "classification": classification.name,
                    },
                    "failures": {
                        "real": _serialize_regressions(regressions.real),
                        "intermittent": _serialize_regressions(
                            regressions.intermittent
                        ),
                        "unknown": _serialize_regressions(regressions.unknown),
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
            matrix_room = config.get("matrix-room-id")
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

    def retrigger_failures(
        self, push, groups, count, allowed_patterns, retrigger_limit
    ):
        groups_with_failures = {}
        for name, failing_tasks in groups.items():
            filtered_failing_tasks = [
                task
                for task in failing_tasks
                if any(
                    fnmatch.fnmatch(task.label, pattern) for pattern in allowed_patterns
                )
            ]
            if filtered_failing_tasks:
                assert all(
                    any(
                        not result.ok and result.group == name
                        for result in task.results
                    )
                    for task in filtered_failing_tasks
                ), f"Some failing tasks on the group {name} (to be retriggered) didn't really fail"
                groups_with_failures[name] = filtered_failing_tasks

        if not groups_with_failures:
            return

        for failing_tasks in itertools.islice(
            groups_with_failures.values(), 0, retrigger_limit
        ):
            # If there is more than one task failing in this group, we should retrigger only one of them
            failing_tasks[0].retrigger(push, count)

    def backfill_and_retrigger_failures(
        self,
        push: Push,
        allowed_patterns: List[str],
        classify_parameters: Dict[str, Any],
        retrigger_limit: int,
        backfill_limit: int,
        to_retrigger_or_backfill: ToRetriggerOrBackfill,
    ) -> None:
        # Retrigger real failures
        # TODO: Potential real failures might be coming from children pushes too, but we should instead
        # only retrigger tasks on the push where they were defined (https://github.com/mozilla/mozci/issues/796).
        self.line("Retriggering failures to ensure they are real")
        self.retrigger_failures(
            push,
            to_retrigger_or_backfill.real_retrigger,
            classify_parameters.get("consistent_failures_counts", (2, 3))[1],
            allowed_patterns,
            retrigger_limit,
        )

        # Retrigger intermittent failures
        self.line("Retriggering failures to ensure they are intermittent")
        self.retrigger_failures(
            push,
            to_retrigger_or_backfill.intermittent_retrigger,
            classify_parameters.get("consistent_failures_counts", (2, 3))[0],
            allowed_patterns,
            retrigger_limit,
        )

        # Backfill some failures
        self.line("Backfilling failures to ensure they are caused by this push")
        groups_to_backfill = {
            name: failing_tasks
            for name, failing_tasks in to_retrigger_or_backfill.backfill.items()
            if failing_tasks
        }
        for failing_tasks in itertools.islice(
            groups_to_backfill.values(), 0, backfill_limit
        ):
            for t in failing_tasks:
                if t.label and any(
                    fnmatch.fnmatch(t.label, pattern) for pattern in allowed_patterns
                ):
                    t.backfill(push)

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

            return "Tasks:\n  - " + "\n  - ".join(
                [f"[{task.label}]({_get_task_url(task)})" for task in tasks]
            )

        if (
            previous in (None, PushStatus.GOOD, PushStatus.UNKNOWN)
            and current == PushStatus.BAD
        ) or (
            previous == PushStatus.BAD
            and current in (PushStatus.GOOD, PushStatus.UNKNOWN)
        ):
            formatted_date = datetime.datetime.fromtimestamp(
                push.date, tz=datetime.timezone.utc
            ).strftime("%H:%M:%S")
            email_content = EMAIL_PUSH_EVOLUTION.format(
                previous=previous.name if previous else "no classification",
                current=current.name,
                push=push,
                date=formatted_date,
                branch=self.branch,
                real_failures="\n- ".join(
                    [
                        f"Group [{group}]({_get_group_url(group)}) - {_list_tasks(tasks)}"
                        for group, tasks in regressions.real.items()
                    ]
                ),
            )
            if emails:
                notify_email(
                    emails=emails,
                    subject=f"Push status evolution {push.id} {push.rev[:8]}",
                    content=email_content,
                )
            if matrix_room:
                notify_matrix(
                    room=matrix_room,
                    body=email_content,
                )


def prepare_for_analysis(push):
    removed_tasks: Dict[str, List[Task]] = {}
    backedoutby: Dict[str, str] = {}
    old_classifications: Dict[str, Dict[str, Dict[str, str]]] = {}

    all_pushes = set(
        [push]
        + [parent for parent in push._iterate_parents(max_depth=MAX_DEPTH)]
        + [child for child in push._iterate_children(max_depth=MAX_DEPTH)]
    )
    for p in all_pushes:
        # Ignore retriggers and backfills on current push/its parents/its children.
        removed_tasks[p.id] = [
            task for task in p.tasks if task.is_backfill or task.is_retrigger
        ]
        p.tasks = [task for task in p.tasks if task not in removed_tasks[p.id]]

        # Pretend push was not backed out.
        backedoutby[p.id] = p.backedoutby
        p.backedoutby = None

        # Pretend push was not finalized yet.
        p._date = datetime.datetime.now().timestamp()

        # Pretend no tasks were classified to run the model without any outside help.
        old_classifications[p.id] = {}
        for task in p.tasks:
            old_classifications[p.id][task.id] = {
                "classification": task.classification,
                "note": task.classification_note,
            }
            task.classification = "not classified"
            task.classification_note = None

    return all_pushes, removed_tasks, backedoutby, old_classifications


def retrieve_sheriff_reals(pushes_group_summaries, push):
    # Compare real failures that were predicted by mozci with the ones classified by Sheriffs
    sheriff_reals = set()
    # Get likely regressions of this push
    likely_regressions = push.get_likely_regressions("group", True)
    # Only consider groups that were classified as "fixed by commit" to exclude likely regressions mozci found via heuristics.
    max_depth = None if push.backedout or push.bustage_fixed_by else MAX_DEPTH
    for other in push._iterate_children(max_depth=max_depth):
        if other.push_uuid not in pushes_group_summaries:
            pushes_group_summaries[other.push_uuid] = other.group_summaries

        for name, group in pushes_group_summaries[other.push_uuid].items():
            classifications = set([c for c, _ in group.classifications])
            if classifications == {"fixed by commit"} and name in likely_regressions:
                sheriff_reals.add(name)

    return pushes_group_summaries, sheriff_reals


def retrieve_sheriff_intermittents(pushes_group_summaries, push):
    if push.push_uuid not in pushes_group_summaries:
        pushes_group_summaries[push.push_uuid] = push.group_summaries

    # Compare intermittent failures that were predicted by mozci with the ones classified by Sheriffs
    sheriff_intermittents = set()
    for name, group in pushes_group_summaries[push.push_uuid].items():
        classifications = set([c for c, _ in group.classifications])
        if classifications <= set(INTERMITTENT_CLASSES):
            sheriff_intermittents.add(name)

    return pushes_group_summaries, sheriff_intermittents


def parse_and_log_details(
    group_summaries,
    sheriff_groups,
    expected,
    push=None,
    failures=None,
    predicted_groups=None,
    ignore_pending_conflicting=False,
    state="",
    suffix="",
):
    to_print = []

    if failures and not predicted_groups:
        predicted_groups = failures[push][state].keys() if failures.get(push) else []

    total = len(predicted_groups)
    if not total:
        if sheriff_groups:
            to_print.append(
                f"{len(sheriff_groups)} groups were classified as {state} by Sheriffs and missed by Mozci, missed groups:"
            )
            to_print.append("  - " + "\n  - ".join(sheriff_groups))

        output = {
            f"total{suffix}": 0,
            f"correct{suffix}": 0,
            f"wrong{suffix}": 0,
            f"missed{suffix}": len(sheriff_groups),
        }
        if not ignore_pending_conflicting:
            output[f"pending{suffix}"] = 0
            output[f"conflicting{suffix}"] = 0

        return output, to_print

    conflicting = []
    differing = []
    pending = []
    for group in predicted_groups:
        classifications_set = set(
            task.classification for task in group_summaries[group].tasks if task.failed
        )
        if len(classifications_set) == 0:
            continue
        if classifications_set == {"not classified"}:
            pending.append(group)
        elif len(classifications_set) != 1:
            conflicting.append(group)
        elif classifications_set.isdisjoint(expected):
            differing.append(group)

    missed = []
    for group in sheriff_groups:
        if group not in predicted_groups:
            missed.append(group)

    correct = total - len(differing)
    if not ignore_pending_conflicting:
        correct -= len(pending) + len(conflicting)

    to_print.append(
        f"{correct} out of {total} {state} groups were also classified as {state} by Sheriffs."
    )
    if differing:
        to_print.append(
            f"{len(differing)} out of {total} {state} groups weren't classified as {state} by Sheriffs, differing groups:"
        )
        to_print.append("  - " + "\n  - ".join(differing))
    if not ignore_pending_conflicting:
        if pending:
            to_print.append(
                f"{len(pending)} out of {total} {state} groups are waiting to be classified by Sheriffs."
            )
        if conflicting:
            to_print.append(
                f"{len(conflicting)} out of {total} {state} groups have conflicting classifications applied by Sheriffs, inconsistent groups:"
            )
            to_print.append("  - " + "\n  - ".join(conflicting))
    if missed:
        to_print.append(
            f"{len(missed)} groups were classified as {state} by Sheriffs and missed (or classified as unknown) by Mozci, missed groups:"
        )
        to_print.append("  - " + "\n  - ".join(missed))

    output = {
        f"total{suffix}": total,
        f"correct{suffix}": correct,
        f"wrong{suffix}": len(differing),
        f"missed{suffix}": len(missed),
    }
    if not ignore_pending_conflicting:
        output[f"pending{suffix}"] = len(pending)
        output[f"conflicting{suffix}"] = len(conflicting)

    return output, to_print


def check_ever_classified_as_cause(push, iterate_on):
    ever_classified_as_cause = False
    for (
        other,
        _,
        candidate_regressions,
        classified_as_cause,
    ) in push._iterate_failures(iterate_on):
        if push.backedoutby in other.revs or push.bustage_fixed_by in other.revs:
            return ever_classified_as_cause

        ever_classified_as_cause = any(
            result is True
            for name in candidate_regressions.keys()
            for result in classified_as_cause[name]
        )
        if ever_classified_as_cause:
            return ever_classified_as_cause


class ClassifyEvalCommand(Command):
    """
    Evaluate the classification results for a given push (or a range of pushes) by comparing them with reality.

    classify-eval
        {branch=autoland : Branch the push belongs to (e.g autoland, try, etc).}
        {--rev= : Head revision of the push.}
        {--from-date= : Lower bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago").}
        {--to-date= : Upper bound of the push range (as a date in yyyy-mm-dd format or a human expression like "1 days ago"), defaults to now.}
        {--intermittent-confidence-threshold= : Medium confidence threshold used to classify the regressions.}
        {--real-confidence-threshold= : High confidence threshold used to classify the regressions.}
        {--use-possible-regressions= : Use possible regressions while classifying the regressions.}
        {--unknown-from-regressions= : Unknown from regressions while classifying the regressions.}
        {--consider-children-pushes-configs= : Consider children pushes configs while classifying the regressions.}
        {--cross-config-counts= : Cross-config counts used to classify the regressions.}
        {--consistent-failures-counts= : Consistent failures counts used to classify the regressions.}
        {--recalculate : If set, recalculate the classification instead of fetching an artifact.}
        {--output= : Path towards a path to save a CSV file with classification states for various pushes.}
        {--send-email : If set, also send the evaluation report by email instead of just logging it.}
        {--detailed-classifications : If set, compare real/intermittent group classifications with Sheriff's ones.}
        {--environment=testing : Environment in which the analysis is running (testing, production, ...)}
    """

    def handle(self) -> None:
        branch = self.argument("branch")

        self.line("<comment>Loading pushes...</comment>")
        self.pushes = classify_commands_pushes(
            branch,
            self.option("from-date"),
            self.option("to-date"),
            self.option("rev"),
        )

        option_names = [
            name.replace("_", "-")
            for name, _ in signature(Push.classify).parameters.items()
            if name != "self"
        ]
        if self.option("recalculate"):
            classify_parameters = retrieve_classify_parameters(self.option)
        elif any(self.option(name) for name in option_names):
            self.line(
                f"<error>--recalculate isn't set, you shouldn't provide --{', --'.join(option_names)} CLI options.</error>"
            )
            return

        # Progress bar will display time stats & messages
        progress = self.progress_bar(len(self.pushes))
        progress.set_format(
            " %current%/%max% [%bar%] %percent:3s%% %elapsed:6s% %message%"
        )

        # Setup specific route prefix for existing tasks, according to environment
        environment = self.option("environment")
        route_prefix = (
            "project.mozci.classification"
            if environment == "production"
            else f"project.mozci.{environment}.classification"
        )

        self.errors = {}
        self.classifications = {}
        self.failures = {}
        for push in self.pushes:
            if self.option("recalculate"):
                progress.set_message(f"Calc. {branch} {push.id}")

                (
                    all_pushes,
                    removed_tasks,
                    backedoutby,
                    old_classifications,
                ) = prepare_for_analysis(push)

                try:
                    self.classifications[push], regressions, _ = push.classify(
                        **classify_parameters
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

                for p in all_pushes:
                    # Once the Mozci algorithm has run, restore Sheriffs classifications to be able to properly compare failures classifications.
                    for task in p.tasks:
                        task.classification = old_classifications[p.id][task.id][
                            "classification"
                        ]
                        task.classification_note = old_classifications[p.id][task.id][
                            "note"
                        ]

                    # Restore backout information.
                    p.backedoutby = backedoutby[p.id]

                    # And also restore tasks marked as a backfill or a retrigger.
                    p.tasks = p.tasks + removed_tasks[p.id]
            else:
                progress.set_message(f"Fetch {branch} {push.id}")
                try:
                    index = f"{route_prefix}.{branch}.revision.{push.rev}"
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

            warnings = []
            # Warn about pushes that are backed-out and where all failures on the push itself and its children are marked as intermittent
            if push.backedout or push.bustage_fixed_by:
                ever_classified_as_cause = check_ever_classified_as_cause(push, "label")

                if not ever_classified_as_cause:
                    ever_classified_as_cause = check_ever_classified_as_cause(
                        push, "group"
                    )

                if not ever_classified_as_cause:
                    warnings.append(
                        {
                            "message": f"Push {push.branch}/{push.rev} was backedout and all of its failures and the ones of its children were marked as intermittent or marked as caused by another push.",
                            "type": "error",
                            "notify": config.get("warnings", {}).get(
                                "ever_classified_as_cause", False
                            ),
                        }
                    )

            for task in push.tasks:
                if task.classification != "fixed by commit":
                    continue

                # Warn if there is a classification that references a revision that does not exist
                fix_hgmo = HgRev.create(
                    task.classification_note[:12], branch=push.branch
                )
                try:
                    fix_hgmo.changesets
                except PushNotFound:
                    warnings.append(
                        {
                            "message": f"Task {task.id} on push {push.branch}/{push.rev} contains a classification that references a non-existent revision: {task.classification_note}.",
                            "type": "error",
                            "notify": config.get("warnings", {}).get(
                                "non_existent_fix", False
                            ),
                        }
                    )
                    continue

                if fix_hgmo.pushid <= push.id:
                    warnings.append(
                        {
                            "message": f"Task {task.label} on push {push.branch}/{push.rev} is classified as fixed by {task.classification_note}, which is older than the push itself.",
                            "type": "error",
                            "notify": config.get("warnings", {}).get(
                                "fix_older_than_push", False
                            ),
                        }
                    )
                    continue

                # Warn when a failure is classified as fixed by a backout of a push that is newer than the failure itself
                all_backedouts = set(
                    backedout
                    for backedouts in fix_hgmo.backouts.values()
                    for backedout in backedouts
                )

                all_bustagefixed = set()
                for child in push._iterate_children():
                    if child.rev == fix_hgmo.node:
                        break

                    for bug in child.bugs:
                        if bug in fix_hgmo.bugs_without_backouts:
                            all_bustagefixed.add(child.rev)

                all_fixed = all_backedouts | all_bustagefixed

                if len(all_fixed) > 0 and all(
                    HgRev.create(backedout, branch=push.branch).pushid > push.id
                    for backedout in all_fixed
                ):
                    warnings.append(
                        {
                            "message": f"Task {task.label} on push {push.branch}/{push.rev} is classified as fixed by a backout/bustage fix ({fix_hgmo.node}) of pushes ({all_fixed}) that come after the failure itself.",
                            "type": "error",
                            "notify": config.get("warnings", {}).get(
                                "backout_of_newer_pushes", False
                            ),
                        }
                    )

            # Warn when there are inconsistent classifications for a given group
            if push.backedout or push.bustage_fixed_by:
                group_classifications: dict[
                    str, dict[tuple[str, str], set[str]]
                ] = collections.defaultdict(lambda: collections.defaultdict(set))
                for other in push._iterate_children():
                    if (
                        push.backedoutby in other.revs
                        or push.bustage_fixed_by in other.revs
                    ):
                        break

                    for name, summary in other.group_summaries.items():
                        for classification in summary.classifications:
                            group_classifications[name][classification].add(other.rev)

                for name, classification_to_revs in group_classifications.items():
                    if len(classification_to_revs) > 1:
                        inconsistent_list = [
                            f"  - {classification} in pushes {', '.join(revs)}"
                            for classification, revs in classification_to_revs.items()
                        ]
                        inconsistent = "\n" + ",\n".join(inconsistent_list)
                        warnings.append(
                            {
                                "message": f"Group {name} has inconsistent classifications: {inconsistent}.",
                                "type": "comment",
                                "notify": config.get("warnings", {}).get(
                                    "inconsistent", False
                                ),
                            }
                        )

            # Output all warnings and also send them to the Matrix room if defined
            matrix_room = config.get("matrix-room-id")
            for warning in warnings:
                warn_type = warning["type"]
                warn_message = warning["message"]
                do_notify = warning["notify"]
                self.line(f"<{warn_type}>{warn_message}</{warn_type}>")
                if matrix_room and do_notify:
                    notify_matrix(room=matrix_room, body=warn_message)

            if not matrix_room and warnings:
                self.line(
                    "<comment>Some warning notifications should have been sent but no matrix room was provided in the secret.</comment>"
                )

            # Advance the overall progress bar
            progress.advance()

        # Conclude the progress bar
        progress.finish()
        print("\n")

        error_line = ""
        if self.errors:
            if self.option("recalculate"):
                error_line = "Failed to recalculate classification"
            else:
                error_line = "Failed to fetch classification"

            error_line += f" for {len(self.errors)} out of {len(self.pushes)} pushes."

            if not self.option("recalculate") and not self.option("send-email"):
                error_line += " Use the '--recalculate' option if you want to generate them yourself."

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

            pushes_group_summaries = {}
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

                if push.push_uuid not in pushes_group_summaries:
                    pushes_group_summaries[push.push_uuid] = push.group_summaries

                # Compare real failures that were predicted by mozci with the ones classified by Sheriffs
                try:
                    pushes_group_summaries, sheriff_reals = retrieve_sheriff_reals(
                        pushes_group_summaries, push
                    )
                except Exception:
                    self.line(
                        "<error>Failed to retrieve Sheriff classifications for the real failures of this push.</error>"
                    )

                try:
                    push_real_stats, to_print = parse_and_log_details(
                        pushes_group_summaries[push.push_uuid],
                        sheriff_reals,
                        {"fixed by commit"},
                        push=push,
                        failures=self.failures,
                        state="real",
                    )

                    for line in to_print:
                        self.line(line)

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
                    (
                        pushes_group_summaries,
                        sheriff_intermittents,
                    ) = retrieve_sheriff_intermittents(pushes_group_summaries, push)
                except Exception:
                    self.line(
                        "<error>Failed to retrieve Sheriff classifications for the intermittent failures of this push.</error>"
                    )

                try:
                    push_intermittent_stats, to_print = parse_and_log_details(
                        pushes_group_summaries[push.push_uuid],
                        sheriff_intermittents,
                        set(INTERMITTENT_CLASSES),
                        push=push,
                        failures=self.failures,
                        state="intermittent",
                    )

                    for line in to_print:
                        self.line(line)

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
                f"{real_stats['correct']} out of {real_stats['total']} failures were correctly classified as real ('fixed by commit' by Sheriffs).",
                f"{real_stats['wrong']} out of {real_stats['total']} failures were wrongly classified as real ('intermittent' by Sheriffs).",
                f"{real_stats['pending']} out of {real_stats['total']} failures classified as real are waiting to be classified by Sheriffs.",
                f"{real_stats['conflicting']} out of {real_stats['total']} failures classified as real have conflicting classifications applied by Sheriffs.",
                f"{real_stats['missed']} real failures were missed or classified as unknown by Mozci.",
                f"{intermittent_stats['correct']} out of {intermittent_stats['total']} failures were correctly classified as intermittent ('intermittent' by Sheriffs).",
                f"{intermittent_stats['wrong']} out of {intermittent_stats['total']} failures were wrongly classified as intermittent ('fixed by commit' by Sheriffs).",
                f"{intermittent_stats['pending']} out of {intermittent_stats['total']} failures classified as intermittent are waiting to be classified by Sheriffs.",
                f"{intermittent_stats['conflicting']} out of {intermittent_stats['total']} failures classified as intermittent have conflicting classifications applied by Sheriffs.",
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

        environment = self.option("environment")
        notify_email(
            emails=config.get("emails", {}).get("monitoring"),
            subject=f"{environment} classify-eval report generated the {today}",
            content=EMAIL_CLASSIFY_EVAL.format(
                today=today,
                total=total,
                error_line=f"**{error_line}**" if error_line else "",
                stats=stats,
            ),
        )


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
