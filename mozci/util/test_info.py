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
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger

from mozci import config
from mozci.task import wpt_workaround
from mozci.util.taskcluster import find_task_id, get_artifact

INDEX = "gecko.v2.mozilla-central.pushdate.{date:%Y.%m.%d}.latest.source.test-info-all"
ARTIFACT = "public/test-run-info.json"
TESTS_ARTIFACT = "public/test-info-all-tests.json"


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


def _from_reports(date: datetime.date, name: str, artifact: str, summarize_fn):
    """Summary of an artifact of the report of the days before `date` (or None if
    unavailable)."""
    for age in range(1, MAX_REPORT_AGE + 1):
        day = date - datetime.timedelta(days=age)
        key = f"test_info/{name}/{day:%Y-%m-%d}"
        result = config.cache.get(key)
        if result is not None:
            return result
        try:
            task_id = find_task_id(INDEX.format(date=day))
            result = summarize_fn(get_artifact(task_id, artifact))
        except Exception as e:
            logger.debug(f"Test info report for {day} unavailable: {e}")
            continue
        config.cache.put(key, result, config["cache"]["retention"])
        return result
    logger.warning(f"No test info report found for the days before {date}")
    return None


def group_failure_stats(
    date: datetime.date,
) -> Optional[Dict[str, Dict[str, Tuple[int, int]]]]:
    """Failure statistics of groups over the 30 days before `date` (or None if unavailable)."""
    return _from_reports(date, "group_failure_stats_by_job_type", ARTIFACT, summarize)


def summarize_tests(report: dict) -> Dict[str, List[str]]:
    """{test path: [groups]} from a test-info-all-tests report."""
    manifests: Dict[str, Set[str]] = {}
    for entries in report.get("tests", {}).values():
        for entry in entries:
            manifests.setdefault(entry["test"], set()).update(
                normalize_group(m) for m in entry.get("manifest") or []
            )
    return {test: sorted(groups) for test, groups in manifests.items()}


def manifests_of_tests(date: datetime.date) -> Optional[Dict[str, List[str]]]:
    """The groups of each test, as of the days before `date` (or None if unavailable)."""
    return _from_reports(date, "test_manifests", TESTS_ARTIFACT, summarize_tests)


# The directories of the WPT expectations, with the prefix of the names of their
# tests.
WPT_METADATA = (
    ("testing/web-platform/meta/", "/"),
    ("testing/web-platform/mozilla/meta/", "/_mozilla/"),
)
WPT_ROOTS = tuple(wpt_workaround(prefix) for _, prefix in WPT_METADATA)


def groups_of_file(path: str, manifests: Dict[str, List[str]]) -> Set[str]:
    """The groups a file of the tree belongs to: the manifests listing it (for tests),
    itself (for manifests), and the directories containing it (for WPT tests and
    their expectations)."""
    for metadata, prefix in WPT_METADATA:
        if path.startswith(metadata):
            path = wpt_workaround(prefix + path[len(metadata) :].removesuffix(".ini"))
    groups = set(manifests.get(path, ()))
    if path.endswith(MANIFEST_SUFFIXES):
        groups.add(path)
    if path.startswith(WPT_ROOTS):
        parts = path.split("/")
        groups.update("/".join(parts[:k]) for k in range(4, len(parts)))
    return groups


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
