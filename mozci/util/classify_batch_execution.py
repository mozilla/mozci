# -*- coding: utf-8 -*-
import csv
import datetime
import itertools
import json
import os
import time
import uuid

from loguru import logger

from mozci.push import make_push_objects

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
CSV_HEADER = (
    ["run_uuid", "push_uuid"]
    + PARAMETERS_NAMES
    + ["classification", "time_spent", "now"]
)


def retrieve_pushes():
    now = datetime.datetime.today()
    to_date = now.strftime("%Y-%m-%d")
    from_date = (now - datetime.timedelta(days=DAYS_FROM_TODAY)).strftime("%Y-%m-%d")
    return make_push_objects(from_date=from_date, to_date=to_date, branch="autoland")


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


def main():
    if not os.path.exists(BASE_OUTPUT_DIR):
        os.makedirs(BASE_OUTPUT_DIR)

    pushes = retrieve_pushes()

    with open(
        BASE_OUTPUT_DIR + "/all_executions.csv", "w", encoding="UTF8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()

        for parameters_values in itertools.product(
            [0.5, 0.7, 0.9],  # intermittent_confidence_threshold
            [0.7, 0.8, 0.9],  # real_confidence_threshold
            [True, False],  # use_possible_regressions
            [True, False],  # unknown_from_regressions
            [True, False],  # consider_children_pushes_configs
            [(2, 2), (2, 3), (2, 5)],  # cross_config_counts
            [(2, 3), (2, 5)],  # consistent_failures_counts
        ):
            parameters = dict(zip(PARAMETERS_NAMES, parameters_values))
            for push in pushes:
                push_dir = f"{BASE_OUTPUT_DIR}/{push.id}"
                if not os.path.exists(push_dir):
                    os.makedirs(push_dir)

                run_id = uuid.uuid4()

                try:
                    start = time.time()
                    classification, regressions = push.classify(**parameters)
                    end = time.time()

                    classification_name = classification.name
                    create_json_file(push, run_id, classification_name, regressions)
                except Exception as e:
                    end = time.time()
                    logger.error(
                        f"An error occurred during the classification of push {push.push_uuid}: {e}"
                    )
                    classification_name = "SYSTEM_ERROR"

                writer.writerows(
                    [
                        {
                            "run_uuid": run_id,
                            "push_uuid": push.push_uuid,
                            **parameters,
                            "classification": classification_name,
                            "time_spent": round(end - start, 3),
                            "now": datetime.datetime.now(),
                        }
                    ]
                )


if __name__ == "__main__":
    main()
