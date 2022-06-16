# -*- coding: utf-8 -*-
import csv
import datetime
import itertools
import json
import os
import time
import uuid
from multiprocessing import Pool

from cleo import Command
from loguru import logger

from mozci.console.commands.push import (
    parse_and_log_details,
    prepare_for_analysis,
    retrieve_sheriff_intermittents,
    retrieve_sheriff_reals,
)
from mozci.push import Push, PushStatus, make_push_objects
from mozci.util.defs import INTERMITTENT_CLASSES

BASE_OUTPUT_DIR = (
    os.path.dirname(os.path.realpath(__file__)) + "/classify_batch_results"
)
DAYS_FROM_TODAY = 30
PARAMETERS_NAMES = [
    "intermittent_confidence_threshold",
    "real_confidence_threshold",
    "use_possible_regressions",
    "unknown_from_regressions",
    "consider_children_pushes_configs",
    "cross_config_counts",
    "consistent_failures_counts",
]
PARAMETERS_COMBINATIONS = [
    dict(zip(PARAMETERS_NAMES, parameters_values))
    for parameters_values in itertools.product(
        [0.5, 0.7, 0.9],  # intermittent_confidence_threshold
        [0.7, 0.8, 0.9],  # real_confidence_threshold
        [True, False],  # use_possible_regressions
        [True, False],  # unknown_from_regressions
        [True, False],  # consider_children_pushes_configs
        [(2, 2), (2, 3), (2, 5)],  # cross_config_counts
        [(2, 3), (2, 5)],  # consistent_failures_counts
    )
]
MAXIMUM_PROCESSES = os.cpu_count() or 1


def retrieve_push_and_prepare_for_analysis(push):
    push = Push(push["rev"], branch=push["branch"])
    prepare_for_analysis(push)


def _serialize_regressions(regressions):
    return {
        group: [{"task_id": task.id, "label": task.label} for task in failing_tasks]
        for group, failing_tasks in regressions.items()
    }


def create_json_file(push, run_id, classification_name, regressions):
    to_save = {
        "push": {
            "id": push.push_uuid,
            "classification": classification_name,
        },
        "failures": {
            "real": _serialize_regressions(regressions.real),
            "intermittent": _serialize_regressions(regressions.intermittent),
            "unknown": _serialize_regressions(regressions.unknown),
        },
    }

    with open(f"{BASE_OUTPUT_DIR}/{push.id}/{run_id}.json", "w") as file:
        json.dump(to_save, file, indent=2)


def run_combinations_for_push(push):
    push = Push(push["rev"], branch=push["branch"])

    push_dir = f"{BASE_OUTPUT_DIR}/{push.id}"
    if not os.path.exists(push_dir):
        os.makedirs(push_dir)

    csv_rows = []
    for parameters in PARAMETERS_COMBINATIONS:
        run_id = uuid.uuid4()

        start = time.time()
        try:
            classification, regressions = push.classify(**parameters)
            end = time.time()

            # Only save results to a JSON file if the execution was successful
            classification_name = classification.name
            create_json_file(push, run_id, classification_name, regressions)
        except Exception as e:
            end = time.time()
            classification_name = "SYSTEM_ERROR"
            logger.error(
                f"An error occurred during the classification of push {push.push_uuid}: {e}"
            )

        csv_rows.append(
            {
                "run_uuid": run_id,
                "push_uuid": push.push_uuid,
                **parameters,
                "classification": classification_name,
                "time_spent": round(end - start, 3),
                "now": datetime.datetime.now(),
            }
        )

    return csv_rows


class BatchClassificationCommand(Command):
    """
    Run the classification algorithm with various parameters combinations for all submitted pushes within the last 30 days

    classify
        {--workers= : Number of workers to use in order to parallelize the executions.}
    """

    csv_header = (
        ["run_uuid", "push_uuid"]
        + PARAMETERS_NAMES
        + ["classification", "time_spent", "now"]
    )

    def handle(self) -> None:
        # Default value from a constant if nothing is provided
        workers_count = MAXIMUM_PROCESSES

        workers_option = self.option("workers")
        if workers_option:
            try:
                workers_count = int(workers_option)
            except ValueError:
                self.line("<error>Provided --workers should be an int.</error>")
                exit(1)

            if workers_count > MAXIMUM_PROCESSES:
                self.line(
                    f"<comment>Parallelization over {workers_count} workers was requested but only {MAXIMUM_PROCESSES} CPUs are available, falling back to using only {MAXIMUM_PROCESSES} workers.</comment>"
                )
                workers_count = MAXIMUM_PROCESSES

        pushes = self.retrieve_pushes()
        self.line(
            f"<info>{len(pushes)} pushes will be classified using {len(PARAMETERS_COMBINATIONS)} parameters combinations.</info>"
        )

        with Pool(workers_count) as pool:
            # Populate the cache + Clean up potential biases
            pool.map(retrieve_push_and_prepare_for_analysis, pushes)

        if not os.path.exists(BASE_OUTPUT_DIR):
            os.makedirs(BASE_OUTPUT_DIR)

        with open(
            BASE_OUTPUT_DIR + "/all_executions.csv", "w", encoding="UTF8", newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=self.csv_header)
            writer.writeheader()

            with Pool(workers_count) as pool:
                # Each time an execution ends (execution = all combinations for a single push),
                # its result will be appended to the CSV
                for csv_rows in pool.imap(run_combinations_for_push, pushes):
                    writer.writerows(csv_rows)

    def retrieve_pushes(self):
        now = datetime.datetime.today()
        to_date = now.strftime("%Y-%m-%d")
        from_date = (now - datetime.timedelta(days=DAYS_FROM_TODAY)).strftime(
            "%Y-%m-%d"
        )
        pushes = make_push_objects(
            from_date=from_date, to_date=to_date, branch="autoland"
        )
        return [{"rev": push.rev, "branch": push.branch} for push in pushes]


class BatchEvaluationCommand(Command):
    """
    Evaluate and aggregate the results produced by the classify_batch_execution script

    evaluate
    """

    csv_header = [
        "configuration",
        "total_pushes",
        "classify_errors",
        "evaluate_errors",
        "correct_good",
        "wrong_good",
        "correct_bad",
        "wrong_bad",
        "total_real",
        "correct_real",
        "wrong_real",
        "missed_real",
        "total_intermittent",
        "correct_intermittent",
        "wrong_intermittent",
        "missed_intermittent",
    ]

    def handle(self) -> None:
        results_path = BASE_OUTPUT_DIR + "/all_executions.csv"
        assert os.path.exists(results_path) and os.path.isfile(
            results_path
        ), "The CSV containing results from all classify executions doesn't exist"

        with open(results_path, newline="") as f:
            reader = csv.DictReader(f)
            configs = self.parse_csv(reader)

        # Write evaluation results per config in a new CSV file
        with open(
            BASE_OUTPUT_DIR + "/evaluation_of_all_executions.csv",
            "w",
            encoding="UTF8",
            newline="",
        ) as f:
            writer = csv.DictWriter(f, fieldnames=self.csv_header)
            writer.writeheader()

            csv_rows = []
            for config, results in configs.items():
                results.update({"configuration": config})
                csv_rows.append(results)

            writer.writerows(csv_rows)

    def evaluate_push_failures(
        self, push_id, run_uuid, push_group_summaries, sheriff_data
    ):
        """
        Evaluate real/intermittent failures on a Push
        """
        with open(f"{BASE_OUTPUT_DIR}/{push_id}/{run_uuid}.json") as f:
            classify_results = json.load(f)
            predicted_reals = classify_results["failures"]["real"].keys()
            predicted_intermittents = classify_results["failures"][
                "intermittent"
            ].keys()

        evaluation = {}
        evaluation.update(
            # Evaluate real failures that were predicted
            parse_and_log_details(
                push_group_summaries,
                sheriff_data["reals"],
                {"fixed by commit"},
                predicted_groups=predicted_reals,
                ignore_pending_conflicting=True,
                suffix="_real",
            )[0]
        )
        evaluation.update(
            # Evaluate intermittent failures that were predicted
            parse_and_log_details(
                push_group_summaries,
                sheriff_data["intermittents"],
                set(INTERMITTENT_CLASSES),
                predicted_groups=predicted_intermittents,
                ignore_pending_conflicting=True,
                suffix="_intermittent",
            )[0]
        )

        return evaluation

    def parse_csv(self, reader):
        """
        Parse the CSV file and evaluate each classify result for a specific configuration and Push
        """
        pushes_group_summaries = {}
        pushes_sheriff_data = {}

        configs = {}
        for i, row in enumerate(reader, start=2):
            self.line(f"Evaluating line {i} of the CSV")
            config = ",".join(
                ["=".join([param, row[param]]) for param in PARAMETERS_NAMES]
            )

            if config not in configs:
                # Initialize all counts at 0
                configs[config] = {key: 0 for key in self.csv_header[1:]}

            configs[config]["total_pushes"] += 1

            if row["classification"] == "SYSTEM_ERROR":
                # No need to evaluate since an error happened during Push classification
                configs[config]["classify_errors"] += 1
                continue

            push_uuid = row["push_uuid"]
            try:
                branch, rev = push_uuid.split("/")
                push = Push(rev, branch=branch)

                if row["classification"] == PushStatus.GOOD.name:
                    if push.backedout:
                        configs[config]["wrong_good"] += 1
                    else:
                        configs[config]["correct_good"] += 1
                elif row["classification"] == PushStatus.BAD.name:
                    if push.backedout:
                        configs[config]["correct_bad"] += 1
                    else:
                        configs[config]["wrong_bad"] += 1

                if push_uuid not in pushes_group_summaries:
                    pushes_group_summaries[push_uuid] = push.group_summaries

                if push_uuid not in pushes_sheriff_data:
                    # By storing sheriffs annotations here, we will only have to run
                    # retrieve_sheriff_data once per push, since it can take a long
                    # time to fetch everything, this helps speed up the evaluation
                    pushes_group_summaries, sheriff_reals = retrieve_sheriff_reals(
                        pushes_group_summaries, push
                    )
                    (
                        pushes_group_summaries,
                        sheriff_intermittents,
                    ) = retrieve_sheriff_intermittents(pushes_group_summaries, push)
                    pushes_sheriff_data[push_uuid] = {
                        "reals": sheriff_reals,
                        "intermittents": sheriff_intermittents,
                    }

                evaluation = self.evaluate_push_failures(
                    push.id,
                    row["run_uuid"],
                    pushes_group_summaries[push_uuid],
                    pushes_sheriff_data[push_uuid],
                )
                for key, value in evaluation.items():
                    configs[config][key] += value

            except Exception as e:
                configs[config]["evaluate_errors"] += 1
                self.line(
                    f"<error>An error occurred during the evaluation of the classify execution with run_uuid {row['run_uuid']}: {e}</error>"
                )

        return configs


class BatchExecutionCommands(Command):
    """
    Contains commands that operate on lots of pushes using lots of classification algorithm configurations.

    batch-execution
    """

    commands = [
        BatchClassificationCommand(),
        BatchEvaluationCommand(),
    ]

    def handle(self):
        return self.call("help", self._config.name)
