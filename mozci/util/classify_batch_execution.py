# -*- coding: utf-8 -*-
import argparse
import csv
import datetime
import itertools
import json
import os
import time
import uuid
from multiprocessing import Pool

from loguru import logger

from mozci.push import MAX_DEPTH, Push, make_push_objects

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
CSV_HEADER = (
    ["run_uuid", "push_uuid"]
    + PARAMETERS_NAMES
    + ["classification", "time_spent", "now"]
)
MAXIMUM_PROCESSES = os.cpu_count()


def retrieve_pushes():
    now = datetime.datetime.today()
    to_date = now.strftime("%Y-%m-%d")
    from_date = (now - datetime.timedelta(days=DAYS_FROM_TODAY)).strftime("%Y-%m-%d")
    pushes = make_push_objects(from_date=from_date, to_date=to_date, branch="autoland")
    return [{"rev": push.rev, "branch": push.branch} for push in pushes]


def prepare_for_analysis(push):
    push = Push(push["rev"], branch=push["branch"])

    all_pushes = set(
        [push]
        + [parent for parent in push._iterate_parents(max_depth=MAX_DEPTH)]
        + [child for child in push._iterate_children(max_depth=MAX_DEPTH)]
    )
    for p in all_pushes:
        # Ignore retriggers and backfills on current push/its parents/its children.
        p.tasks = [
            task for task in p.tasks if not task.is_backfill and not task.is_retrigger
        ]

        # Pretend push was not backed out.
        p.backedoutby = None

        # Pretend push was not finalized yet.
        p._date = datetime.datetime.now().timestamp()

        # Pretend no tasks were classified to run the model without any outside help.
        for task in p.tasks:
            task.classification = "not classified"
            task.classification_note = None


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


def main():
    parser = argparse.ArgumentParser(
        description=f"Run the classification algorithm with various parameters combinations for all submitted pushes within the last {DAYS_FROM_TODAY} days"
    )
    parser.add_argument(
        "--workers",
        help="Number of workers to use in order to parallelise the executions",
        type=int,
        default=MAXIMUM_PROCESSES,
    )
    args = vars(parser.parse_args())

    workers_count = args["workers"]
    if workers_count > MAXIMUM_PROCESSES:
        logger.warning(
            f"Parallelisation over {workers_count} workers was requested but only {MAXIMUM_PROCESSES} CPUs are available, falling back to using only {MAXIMUM_PROCESSES} workers."
        )
        workers_count = MAXIMUM_PROCESSES

    pushes = retrieve_pushes()
    logger.info(
        f"{len(pushes)} pushes will be classified using {len(PARAMETERS_COMBINATIONS)} parameters combinations."
    )

    with Pool(workers_count) as pool:
        # Populate the cache + Clean up potential biases
        pool.map(prepare_for_analysis, pushes)

    if not os.path.exists(BASE_OUTPUT_DIR):
        os.makedirs(BASE_OUTPUT_DIR)

    with open(
        BASE_OUTPUT_DIR + "/all_executions.csv", "w", encoding="UTF8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()

        with Pool(workers_count) as pool:
            # Each time an execution ends (execution = all combinations for a single push),
            # its result will be appended to the CSV
            for csv_rows in pool.imap(run_combinations_for_push, pushes):
                writer.writerows(csv_rows)


if __name__ == "__main__":
    main()
