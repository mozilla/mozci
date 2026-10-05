# -*- coding: utf-8 -*-
"""Past failure rates of test groups.

The daily 'source-test-file-metadata-test-info-all' task on mozilla-central
publishes, for the previous 30 days of autoland and mozilla-central, how many
times each group (manifest) ran on each job type, whether the group passed or
failed, and how the job was classified by sheriffs.
"""

import datetime
from typing import Dict, Optional, Tuple

from loguru import logger

from mozci import config
from mozci.task import wpt_workaround
from mozci.util.taskcluster import find_task_id, get_artifact

INDEX = "gecko.v2.mozilla-central.pushdate.{date:%Y.%m.%d}.latest.source.test-info-all"
ARTIFACT = "public/test-run-info.json"


# Treeherder failure classification ids of intermittent failures ("intermittent",
# "autoclassified intermittent", "intermittent needs bugid").
INTERMITTENT_CLASSIFICATIONS = (4, 7, 8)

# How many days back to look for a report, if the one of the requested day is missing.
MAX_REPORT_AGE = 3


def normalize_group(name: str) -> str:
    """Map Treeherder group names to mozci group names (only WPT groups differ)."""
    return wpt_workaround(name) if name.startswith(("/", ":")) else name


def summarize(report: dict) -> Dict[str, Tuple[int, int]]:
    """{group: (intermittent failures, runs)} over all days of a report."""
    stats: Dict[str, list] = {}
    for day in report.values():
        if not isinstance(day, dict):
            continue
        for entry in day.get("manifests", []):
            for name, rows in entry.items():
                counts = stats.setdefault(normalize_group(name), [0, 0])
                for _, result, classification, count in rows:
                    counts[1] += count
                    if (
                        result == "testfailed"
                        and classification in INTERMITTENT_CLASSIFICATIONS
                    ):
                        counts[0] += count
    return {name: (failures, runs) for name, (failures, runs) in stats.items()}


def group_failure_stats(date: datetime.date) -> Optional[Dict[str, Tuple[int, int]]]:
    """Failure statistics of groups over the 30 days before `date` (or None if unavailable)."""
    for age in range(1, MAX_REPORT_AGE + 1):
        day = date - datetime.timedelta(days=age)
        key = f"test_info/group_failure_stats/{day:%Y-%m-%d}"
        stats = config.cache.get(key)
        if stats is not None:
            return stats
        try:
            task_id = find_task_id(INDEX.format(date=day))
            stats = summarize(get_artifact(task_id, ARTIFACT))
        except Exception as e:
            logger.debug(f"Test info report for {day} unavailable: {e}")
            continue
        config.cache.put(key, stats, config["cache"]["retention"])
        return stats
    logger.warning(f"No test info report found for the days before {date}")
    return None


def is_flaky_group(
    stats: Optional[Dict[str, Tuple[int, int]]],
    group: str,
    min_rate: float = 0.005,
) -> bool:
    """Whether a group failed intermittently often enough in the past."""
    if not stats or group not in stats:
        return False
    failures, runs = stats[group]
    return failures > 0 and failures >= min_rate * runs
