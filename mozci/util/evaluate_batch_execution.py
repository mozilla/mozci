# -*- coding: utf-8 -*-
import argparse
import csv
import json
import os

from loguru import logger

from mozci.push import MAX_DEPTH, Push, PushStatus
from mozci.util.classify_batch_execution import BASE_OUTPUT_DIR, PARAMETERS_NAMES

CSV_HEADER = [
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


def evaluate_groups(
    group_summaries, predicted_groups, sheriff_groups, expected, suffix
):
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
            task.classification for task in group_summaries[group].tasks if task.failed
        )
        if len(classifications_set) != 1 or classifications_set == {"not classified"}:
            # Ignore pending/conflicting classifications
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


def evaluate_push_failures(push_id, run_uuid, push_group_summaries, sheriff_data):
    """
    Evaluate real/intermittent failures on a Push
    """
    with open(f"{BASE_OUTPUT_DIR}/{push_id}/{run_uuid}.json") as f:
        classify_results = json.load(f)
        predicted_reals = classify_results["failures"]["real"].keys()
        predicted_intermittents = classify_results["failures"]["intermittent"].keys()

    evaluation = {}
    evaluation.update(
        # Evaluate real failures that were predicted
        evaluate_groups(
            push_group_summaries,
            predicted_reals,
            sheriff_data["reals"],
            {"fixed by commit"},
            "_real",
        )
    )
    evaluation.update(
        # Evaluate intermittent failures that were predicted
        evaluate_groups(
            push_group_summaries,
            predicted_intermittents,
            sheriff_data["intermittents"],
            {"intermittent"},
            "_intermittent",
        )
    )

    return evaluation


def retrieve_sheriff_data(pushes_group_summaries, push):
    """
    Retrieve annotations from sheriffs for real/intermittent failures on a Push
    """
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

    if push.push_uuid not in pushes_group_summaries:
        pushes_group_summaries[push.push_uuid] = push.group_summaries
    # Compare intermittent failures that were predicted by mozci with the ones classified by Sheriffs
    sheriff_intermittents = set()
    for name, group in pushes_group_summaries[push.push_uuid].items():
        classifications = set([c for c, _ in group.classifications])
        if classifications == {"intermittent"}:
            sheriff_intermittents.add(name)

    return pushes_group_summaries, {
        "reals": sheriff_reals,
        "intermittents": sheriff_intermittents,
    }


def parse_csv(reader):
    """
    Parse the CSV file and evaluate each classify result for a specific configuration and Push
    """
    pushes_group_summaries = {}
    pushes_sheriff_data = {}

    configs = {}
    for i, row in enumerate(reader, start=2):
        logger.debug(f"Evaluating line {i} of the CSV")
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
                (
                    pushes_group_summaries,
                    pushes_sheriff_data[push_uuid],
                ) = retrieve_sheriff_data(pushes_group_summaries, push)

            evaluation = evaluate_push_failures(
                push.id,
                row["run_uuid"],
                pushes_group_summaries[push_uuid],
                pushes_sheriff_data[push_uuid],
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
