# -*- coding: utf-8 -*-
import argparse
import csv
import json
import os

from loguru import logger

from mozci.push import Push
from mozci.util.classify_batch_execution import BASE_OUTPUT_DIR, PARAMETERS_NAMES

CSV_HEADER = [
    "configuration",
    "total_pushes",
    "classify_errors",
    "evaluate_errors",
    "total_real",
    "correct_real",
    "wrong_real",
    "missed_real",
    "total_intermittent",
    "correct_intermittent",
    "wrong_intermittent",
    "missed_intermittent",
]


def evaluate_groups(push, predicted_groups, sheriff_groups, expected, suffix):
    """
    Compare annotated groups with predicted ones to output an evaluation with total
    (predicted)/correctly (predicted)/wrongly (predicted)/missed (annotated) counts
    """
    total = len(predicted_groups)
    if not total:
        return {
            f"total{suffix}": 0,
            f"correct{suffix}": 0,
            f"wrong{suffix}": 0,
            f"missed{suffix}": len(sheriff_groups),
        }

    differing = 0
    for group in predicted_groups:
        classifications_set = set(
            task.classification
            for task in push.group_summaries[group].tasks
            if task.failed
        )
        if len(classifications_set) == 0:
            continue

        if classifications_set != expected:
            differing += 1

    missed = 0
    for group in sheriff_groups:
        if group not in predicted_groups:
            missed += 1

    return {
        f"total{suffix}": total,
        f"correct{suffix}": total - differing,
        f"wrong{suffix}": differing,
        f"missed{suffix}": missed,
    }


def evaluate_push(push, run_uuid, sheriff_data):
    """
    Evaluate real/intermittent failures on a Push
    """
    with open(f"{BASE_OUTPUT_DIR}/{push.id}/{run_uuid}.json") as f:
        classify_results = json.load(f)
        predicted_reals = classify_results["failures"]["real"].keys()
        predicted_intermittents = classify_results["failures"]["intermittent"].keys()

    evaluation = {}
    evaluation.update(
        # Evaluate real failures that were predicted
        evaluate_groups(
            push,
            predicted_reals,
            sheriff_data["reals"],
            {"fixed by commit"},
            "_real",
        )
    )
    evaluation.update(
        # Evaluate intermittent failures that were predicted
        evaluate_groups(
            push,
            predicted_intermittents,
            sheriff_data["intermittents"],
            {"intermittent"},
            "_intermittent",
        )
    )

    return evaluation


def retrieve_sheriff_data(push):
    """
    Retrieve annotations from sheriffs for real/intermittent failures on a Push
    """
    # Compare real failures that were predicted by mozci with the ones classified by Sheriffs
    sheriff_reals = set()
    # Get likely regressions of this push
    likely_regressions = push.get_likely_regressions("group", True)
    # Only consider groups that were classified as "fixed by commit" to exclude likely regressions mozci found via heuristics.
    for other in push._iterate_children():
        for name, group in other.group_summaries.items():
            classifications = set([c for c, _ in group.classifications])
            if classifications == {"fixed by commit"} and name in likely_regressions:
                sheriff_reals.add(name)

    # Compare intermittent failures that were predicted by mozci with the ones classified by Sheriffs
    sheriff_intermittents = set()
    for name, group in push.group_summaries.items():
        classifications = set([c for c, _ in group.classifications])
        if classifications == {"intermittent"}:
            sheriff_intermittents.add(name)

    return {
        "reals": sheriff_reals,
        "intermittents": sheriff_intermittents,
    }


def parse_csv(reader):
    """
    Parse the CSV file and evaluate each classify result for a specific configuration and Push
    """
    pushes_sheriff_data = {}

    configs = {}
    for row in reader:
        config = ",".join(["=".join([param, row[param]]) for param in PARAMETERS_NAMES])

        if config not in configs:
            # Initialize all counts at 0
            configs[config] = {key: 0 for key in CSV_HEADER[1:]}

        configs[config]["total_pushes"] += 1

        if row["classification"] == "SYSTEM_ERROR":
            # No need to evaluate since an error happened during Push classification
            configs[config]["classify_errors"] += 1
            continue

        push_uuid = row["push_uuid"]
        try:
            branch, rev = push_uuid.split("/")
            push = Push(rev, branch=branch)

            if push_uuid not in pushes_sheriff_data:
                # By storing sheriffs annotations here, we will only have to run
                # retrieve_sheriff_data once per push, since it can take a long
                # time to fetch everything, this helps speed up the evaluation
                pushes_sheriff_data[push_uuid] = retrieve_sheriff_data(push)

            evaluation = evaluate_push(
                push, row["run_uuid"], pushes_sheriff_data[push_uuid]
            )
            for key, value in evaluation.items():
                configs[config][key] += value

        except Exception as e:
            configs[config]["evaluate_errors"] += 1
            logger.error(
                f"An error occurred during the evaluation of the classify execution with run_uuid {row['run_uuid']}: {e}"
            )

    return configs


def main():
    argparse.ArgumentParser(
        description="Evaluate and aggregate the results produced by the classify_batch_execution script"
    )

    results_path = BASE_OUTPUT_DIR + "/all_executions.csv"
    assert os.path.exists(results_path) and os.path.isfile(
        results_path
    ), "The CSV containing results from all classify executions doesn't exist"

    with open(results_path, newline="") as f:
        reader = csv.DictReader(f)
        configs = parse_csv(reader)

    # Write evaluation results per config in a new CSV file
    with open(
        BASE_OUTPUT_DIR + "/evaluation_of_all_executions.csv",
        "w",
        encoding="UTF8",
        newline="",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()

        csv_rows = []
        for config, results in configs.items():
            results.update({"configuration": config})
            csv_rows.append(results)

        writer.writerows(csv_rows)


if __name__ == "__main__":
    main()
