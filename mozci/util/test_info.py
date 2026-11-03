# -*- coding: utf-8 -*-
"""Past failure rates of test groups.

The daily 'source-test-file-metadata-test-info-all' task on mozilla-central
publishes, for the previous 30 days of autoland and mozilla-central, how many
times each group (manifest) ran on each job type, whether the group passed or
failed, and how the job was classified by sheriffs. Groups are often flaky on
some platforms only, so failure rates are kept per job type.
"""

import datetime
import re
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

# File name suffixes of manifests (groups which aren't directories).
MANIFEST_SUFFIXES = (".toml", ".ini", ".list")

# Minimum rate of intermittent failures over runs for a group to be considered flaky.
FLAKY_GROUP_MIN_RATE = 0.005

# How many days back to look for a report, if the one of the requested day is missing.
MAX_REPORT_AGE = 3


def normalize_group(name: str) -> str:
    """Map Treeherder group names to mozci group names (only WPT groups differ)."""
    return wpt_workaround(name) if name.startswith(("/", ":")) else name


def summarize(report: dict) -> Dict[str, Dict[str, Tuple[int, int]]]:
    """{group: {job type: (intermittent failures, runs)}} over all days of a report."""
    stats: Dict[str, Dict[str, list]] = {}
    for day in report.values():
        if not isinstance(day, dict):
            continue
        job_types = day.get("job_type_names", [])
        for entry in day.get("manifests", []):
            for name, rows in entry.items():
                group_stats = stats.setdefault(normalize_group(name), {})
                for job_type, result, classification, count in rows:
                    counts = group_stats.setdefault(job_types[job_type], [0, 0])
                    counts[1] += count
                    if (
                        result == "testfailed"
                        and classification in INTERMITTENT_CLASSIFICATIONS
                    ):
                        counts[0] += count
    return {
        group: {job_type: (failures, runs) for job_type, (failures, runs) in s.items()}
        for group, s in stats.items()
    }


def group_failure_stats(
    date: datetime.date,
) -> Optional[Dict[str, Dict[str, Tuple[int, int]]]]:
    """Failure statistics of groups over the 30 days before `date` (or None if unavailable)."""
    for age in range(1, MAX_REPORT_AGE + 1):
        day = date - datetime.timedelta(days=age)
        key = f"test_info/group_failure_stats_by_job_type/{day:%Y-%m-%d}"
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


def job_type(label: str) -> str:
    """The job type of a task, as named in the reports (its label without chunk number)."""
    return re.sub(r"-\d+$", "", label)


def is_flaky_group(
    stats: Optional[Dict[str, Dict[str, Tuple[int, int]]]],
    group: str,
    job_type: str,
    min_rate: float = FLAKY_GROUP_MIN_RATE,
) -> bool:
    """Whether a group failed intermittently often enough in the past on a job type."""
    if not stats or job_type not in stats.get(group, {}):
        return False
    failures, runs = stats[group][job_type]
    return failures > 0 and failures >= min_rate * runs
