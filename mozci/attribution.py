# -*- coding: utf-8 -*-
"""Attribution of failures to the pushes which caused them.

Sheriffs classify failures as 'fixed by commit', referencing the backout of the push
they consider the culprit. These classifications are sometimes wrong: an isolated
intermittent failure attributed to a nearby backout, or a failure attributed to the
backout of a neighbouring push. An AttributionAnalysis, created for a target push,
gathers the evidence about a failure (past failure rates, the reland of the push,
failure lines, crashes, backout descriptions) and decides whether to retain its
classification, to consider it intermittent, or to attribute it to another push.

Push._iterate_failures applies these decisions, while keeping responsibility for the
traversal of the pushes and the bookkeeping of candidate regressions.
"""

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Set
from typing import Tuple, Union

from loguru import logger
from lru import LRU

from mozci import config, data
from mozci.task import (
    GroupSummary,
    LabelSummary,
    Status,
    Task,
    TestTask,
    wpt_workaround,
)
from mozci.util import test_info
from mozci.util.defs import MAX_DEPTH
from mozci.util.hgmo import HgRev, parse_bugs
from mozci.util.memoize import memoized_property

if TYPE_CHECKING:
    from mozci.push import Push


# Failure lines which appear in many unrelated failures (crash reports, sanitizer
# summaries, infrastructure errors...).
GENERIC_FAILURE_LINES = (
    "PROCESS-CRASH",
    "[taskcluster:error]",
    "SUMMARY: ThreadSanitizer",
    "SUMMARY: AddressSanitizer",
    "application terminated with exit code",
    "application crashed",
    "leakcheck",
    "Assertions.h",
)

# How far after its backout to look for the reland of a push (half of the relands
# land within 120 pushes, more than 90% within 1000), and how many pushes to load
# at once.
RELAND_MAX_DISTANCE = 1000
RELAND_BATCH_SIZE = 100
# Minimum number of job types on which a group must pass on a push for a failure on
# a single other job type to be considered isolated.
MIN_PASSING_JOB_TYPES = 6

# File names, as named in backout descriptions (e.g. "for causing failures at
# browser_foo.js", "for causing build bustages @ nsFoo.cpp").
FILE_NAME_RE = re.compile(
    r"([\w\-.]+\.(?:cpp|h|c|rs|js|mjs|sys\.mjs|html|xhtml|py|toml|ini|css|svg|webidl))\b"
)

# Descriptions of commits which back out others, or merge branches.
BACKOUT_PREFIXES = ("Backed out", "Backout", "Revert", "Merge")


def normalize_failure_line(line: str) -> str:
    """A failure line without the parts which change between occurrences (identifiers,
    addresses, numbers)."""
    line = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}", "<uuid>", line)
    line = re.sub(r"\([0-9a-fA-F:.]+\)", "(<address>)", line)
    return re.sub(r"\d+", "<n>", line)


def test_of_failure_line(line: str) -> Optional[str]:
    """The test named by a failure line (e.g. "TEST-UNEXPECTED-FAIL | dom/test_foo.html
    | ..."), or None."""
    parts = [part.strip() for part in line.split("|")]
    if len(parts) >= 3 and "/" in parts[1] and "." in parts[1].rsplit("/", 1)[-1]:
        return parts[1]
    return None


def is_failure_line_about_group(line: str, group: str) -> bool:
    """Whether a failure line is about a group: it names one of its tests, or no test
    (e.g. a fatal error)."""
    test = test_of_failure_line(line)
    if test is None:
        return True
    # WPT tests are named relative to the WPT root.
    if test.startswith("/"):
        test = wpt_workaround(test)
    directory = (
        group.rsplit("/", 1)[0]
        if group.endswith(test_info.MANIFEST_SUFFIXES)
        else group
    )
    return test.startswith(directory.rstrip("/") + "/")


def group_of(runnable_type: str, name: Any) -> Optional[str]:
    """The group of a runnable (None for labels)."""
    if runnable_type == "group":
        return name
    if runnable_type == "config_group":
        return name[1]
    return None


class Verdict(Enum):
    # The classifications of the failure are kept.
    RETAIN = "retain"
    # Its 'fixed by commit' classifications are considered intermittent.
    INTERMITTENT = "intermittent"
    # The failure is attributed to another push (Decision.culprit).
    ATTRIBUTE = "attribute"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    culprit: Optional[int] = None


RETAIN = Decision(Verdict.RETAIN)


class AttributionAnalysis:
    """Evidence about the failures attributed to a push, and decisions about them."""

    # {(branch, push id): groups named by the backout or reland of the push}.
    NAMED_GROUPS_CACHE: Dict[Tuple[str, int], Set[str]] = LRU(1000)

    def __init__(self, push: "Push"):
        self.push = push

    # Evidence.

    @memoized_property
    def group_failure_stats(self):
        """Failure statistics of groups over the 30 days before the push (see
        mozci.util.test_info)."""
        return test_info.group_failure_stats(self.push.push_date)

    @memoized_property
    def test_manifests(self) -> Optional[Dict[str, List[str]]]:
        """The groups of each test, as of the push (see mozci.util.test_info)."""
        return test_info.manifests_of_tests(self.push.push_date)

    @memoized_property
    def failures_until_backout(self) -> Dict[str, int]:
        """Number of failing tasks of each group (on any configuration) on the push
        and its children, until the push was backed out (or up to MAX_DEPTH children
        if it wasn't), as for candidate regressions."""
        push = self.push
        backed_out = push.branch != "try" and push.backedout
        failures: Dict[str, int] = defaultdict(int)
        for other in push._iterate_children(None if backed_out else MAX_DEPTH):
            if backed_out and other != push and push.backedoutby in other.revs:
                break
            for group, summary in other.group_summaries.items():
                if summary.status != Status.PASS:
                    failures[group] += len(summary.classifications)
        return failures

    @memoized_property
    def backout_push_id(self) -> Optional[int]:
        """The id of the push which backed out the push (or None)."""
        push = self.push
        if push.branch == "try" or not push.backedoutby:
            return None
        try:
            return HgRev.create(push.backedoutby, branch=push.branch).pushid
        except Exception as e:
            logger.debug(f"Backout of {push.rev} unavailable: {e}")
            return None

    @memoized_property
    def backout_file_names(self) -> Set[str]:
        """File names in the descriptions of the commits backing out the push (e.g.
        "for causing failures at test_foo.html").

        Only the commits backing out commits of the push are considered, as a push can
        back out several pushes (unless which commits they back out is unknown)."""
        push = self.push
        if self.backout_push_id is None:
            return set()
        try:
            changesets = HgRev.load_json_push(push.branch, self.backout_push_id)[
                "changesets"
            ]
        except Exception as e:
            logger.debug(f"Backout of {push.rev} unavailable: {e}")
            return set()
        backouts = [c for c in changesets if c["desc"].startswith(BACKOUT_PREFIXES)]
        try:
            backed_out = HgRev.create(push.backedoutby, branch=push.branch).backouts
        except Exception as e:
            logger.debug(f"Commits backed out with {push.rev} unavailable: {e}")
            backed_out = {}
        revs = {rev[:12] for rev in push.revs}
        relevant = {
            node[:12]
            for node, nodes in backed_out.items()
            if any(n[:12] in revs for n in nodes)
        }
        if relevant:
            backouts = [c for c in backouts if c["node"][:12] in relevant]
        return {
            name
            for c in backouts
            for name in FILE_NAME_RE.findall(c["desc"].split("\n", 1)[0])
        }

    def _reland(self, backout_id: int) -> List[Dict[str, Any]]:
        """The changesets for the bugs of the push in the first two pushes relanding
        them after the backout (looking at up to RELAND_MAX_DISTANCE pushes)."""
        push = self.push
        bugs = set(map(int, push.bugs))
        relands: List[List[Dict[str, Any]]] = []
        for push_id in range(backout_id + 1, backout_id + 1 + RELAND_MAX_DISTANCE):
            if push_id not in HgRev.JSON_PUSHES_CACHE:
                HgRev.load_json_pushes_between_ids(
                    push.branch, push_id - 1, push_id - 1 + RELAND_BATCH_SIZE
                )
            if push_id not in HgRev.JSON_PUSHES_CACHE:
                break
            changesets = [
                c
                for c in HgRev.JSON_PUSHES_CACHE[push_id]["changesets"]
                if not c["desc"].startswith(BACKOUT_PREFIXES)
                and set(parse_bugs(c["desc"])) & bugs
            ]
            if changesets:
                relands.append(changesets)
                if len(relands) == 2:
                    break
        return [c for changesets in relands for c in changesets]

    @memoized_property
    def reland_files(self) -> Optional[Tuple[Set[str], Set[str]]]:
        """The files modified by the commits of the push, and by their reland after the
        backout, or None if the push wasn't backed out and relanded (or the information
        is unavailable)."""
        push = self.push
        if self.backout_push_id is None or not push.bugs:
            return None
        try:
            original = [
                c
                for c in HgRev.load_json_push(push.branch, push.id)["changesets"]
                if not c["desc"].startswith(BACKOUT_PREFIXES)
            ]
            reland = self._reland(self.backout_push_id)
        except Exception as e:
            logger.debug(f"Reland of {push.rev} unavailable: {e}")
            return None
        if not original or not reland:
            return None
        return (
            {f for c in original for f in c["files"]},
            {f for c in reland for f in c["files"]},
        )

    def _groups_of_files(self, files: Set[str]) -> Optional[Set[str]]:
        manifests = self.test_manifests
        if manifests is None:
            return None
        return set().union(*(test_info.groups_of_file(f, manifests) for f in files))

    @property
    def reland_changed_groups(self) -> Optional[Set[str]]:
        """The groups with tests modified by either the commits of the push or their
        reland after the backout, but not both, or None if the push wasn't backed out
        and relanded (or the information is unavailable).

        Tests modified on both sides might have changed too, but comparing their
        changes would need the patches of the commits, which can be large (see
        reland_touched_groups)."""
        files = self.reland_files
        return None if files is None else self._groups_of_files(files[0] ^ files[1])

    @property
    def reland_touched_groups(self) -> Optional[Set[str]]:
        """The groups with tests modified by the commits of the push or their reland
        after the backout, or None if the push wasn't backed out and relanded (or the
        information is unavailable)."""
        files = self.reland_files
        return None if files is None else self._groups_of_files(files[0] | files[1])

    @property
    def named_groups(self) -> Set[str]:
        """Groups whose tests are named in the description of the backout of the push
        (e.g. "for causing failures at test_foo.html"), or were modified by the push
        or its reland (see reland_touched_groups)."""
        key = (self.push.branch, self.push.id)
        if key not in AttributionAnalysis.NAMED_GROUPS_CACHE:
            groups = set(self.reland_touched_groups or ())
            names = self.backout_file_names
            if names:
                groups |= {
                    group
                    for test, test_groups in (self.test_manifests or {}).items()
                    if test.rsplit("/", 1)[-1] in names
                    for group in test_groups
                }
            AttributionAnalysis.NAMED_GROUPS_CACHE[key] = groups
        return AttributionAnalysis.NAMED_GROUPS_CACHE[key]

    def fixed_after(self, failure_push: "Push") -> bool:
        """Whether the push was backed out or bustage-fixed, after `failure_push`
        landed (bustage fixes are found with the baseline rules, see
        Push.bustage_fixed_by)."""
        push = self.push
        fix = push.backedoutby or push.bustage_fixed_by
        if not fix:
            return False
        try:
            return HgRev.create(fix, branch=push.branch).pushid > failure_push.id
        except Exception:
            return True

    def failure_lines(self, task: Task) -> List[Dict[str, Any]]:
        """The failure lines of a task, with their matching bugs (empty if
        unavailable)."""
        cache: Dict[str, List[Dict[str, Any]]] = self.__dict__.setdefault(
            "_failure_lines", {}
        )
        if task.id not in cache:
            try:
                lines = data.handler.get(
                    "test_task_failure_lines", task=task, branch=self.push.branch
                )
                assert isinstance(lines, list)
                cache[task.id] = lines
            except Exception as e:
                logger.debug(f"Failure lines of {task.id} unavailable: {e}")
                cache[task.id] = []
        return cache[task.id]

    @staticmethod
    def fixed_by_commit_tasks(summary: GroupSummary) -> List[TestTask]:
        """Failed test tasks of a group summary classified as 'fixed by commit'."""
        return [
            task
            for task in summary.tasks
            if task.label and task.failed and task.classification == "fixed by commit"
        ]

    # Decisions.

    def decide(
        self,
        runnable_type: str,
        name: Any,
        summary: Union[GroupSummary, LabelSummary],
        failure_push: "Push",
        passing_job_types: Set[str],
    ) -> Decision:
        """What to do with the classifications of a failure of a runnable on
        `failure_push` (`passing_job_types`: the job types on which the runnable
        passed, from the push to `failure_push`).

        Isolated 'fixed by commit' failures of groups are considered intermittent
        when the evidence says so (see isolated_intermittent). Otherwise, failures of
        configuration groups are attributed to the push whose backout or reland names
        the group, if there is a single one (see named_culprit)."""
        group = group_of(runnable_type, name)
        if group is None:
            return RETAIN
        assert isinstance(summary, GroupSummary)

        reason = self.isolated_intermittent(
            group, summary, failure_push, passing_job_types
        )
        if reason is not None:
            return Decision(Verdict.INTERMITTENT, reason)

        if runnable_type == "config_group" and any(
            c == "fixed by commit" for c, n in summary.classifications
        ):
            culprit = self.named_culprit(name, failure_push)
            if culprit is not None:
                return Decision(
                    Verdict.ATTRIBUTE, "the backout or reland names the group", culprit
                )
        return RETAIN

    def isolated_intermittent(
        self,
        group: str,
        summary: GroupSummary,
        failure_push: "Push",
        passing_job_types: Set[str],
    ) -> Optional[str]:
        """Why 'fixed by commit' classifications of an isolated failure of a group on
        `failure_push` should be considered intermittent (or None): sheriffs sometimes
        attribute isolated failures to a nearby backout.

        This is the case when the group failed at most `flaky_group_max_failures`
        times (on any configuration) until the backout, and the group is flaky, or the
        reland fixed other groups, or the group passed on the failing job types after
        the push or on many other job types (unless the backout names the failure),
        unless the failure is a new one."""
        if self.failures_until_backout.get(group, 0) > config.get(
            "flaky_group_max_failures", 1
        ):
            return None
        failing_job_types = {
            test_info.job_type(task.label or "")
            for task in self.fixed_by_commit_tasks(summary)
        }

        if self.is_flaky_group(summary.name, failing_job_types):
            reason = "the group is flaky on the failing job types"
        elif self.reland_fixed_other_groups(summary.name):
            reason = "the reland fixed other groups"
        else:
            # The failing configurations ran the group with the push applied, and it
            # passed (unless the backout names the failure).
            if failing_job_types & passing_job_types:
                reason = "the group passed on the failing job types"
            elif self.failed_on_one_of_many_job_types(group, failure_push):
                reason = "the group passed on many other job types"
            else:
                return None
            if self.revert_names_failure(summary):
                return None

        # Unless the failure is a new one.
        if self.has_novel_failure(summary, failure_push):
            return None
        return reason

    def is_flaky_group(self, group: str, job_types: Set[str]) -> bool:
        """Whether a group failed intermittently often in the 30 days before the push,
        on all the given job types (groups are often flaky on some platforms only)."""
        return len(job_types) > 0 and all(
            test_info.is_flaky_group(
                self.group_failure_stats,
                group,
                job_type,
                config.get("flaky_group_min_rate", test_info.FLAKY_GROUP_MIN_RATE),
            )
            for job_type in job_types
        )

    def reland_fixed_other_groups(self, group: str) -> bool:
        """Whether the reland of the push changed tests of other groups, and neither
        the push nor its reland modified tests of this one (the tests which were
        broken by the push were fixed, and this group wasn't one of them)."""
        return bool(self.reland_changed_groups) and (
            group not in (self.reland_touched_groups or ())
        )

    @staticmethod
    def failed_on_one_of_many_job_types(group: str, failure_push: "Push") -> bool:
        """Whether a group failed on a single job type on a push, while it passed on at
        least MIN_PASSING_JOB_TYPES other job types on the same push."""
        summary = failure_push.group_summaries.get(group)
        if summary is None:
            return False
        failing: Set[str] = set()
        passing: Set[str] = set()
        for task in summary.tasks:
            if task.label:
                ok = all(r.ok for r in task.results if r.group == group)
                (passing if ok else failing).add(test_info.job_type(task.label))
        return len(failing) == 1 and len(passing - failing) >= MIN_PASSING_JOB_TYPES

    def revert_names_failure(self, summary: GroupSummary) -> bool:
        """Whether the backout of the push names, in its description, a file which
        appears in a failure line of the group in its tasks classified as 'fixed by
        commit' (e.g. "for causing assertion failures @ RegExpObject.cpp")."""
        names = self.backout_file_names
        if not names:
            return False
        return any(
            name in s["search"]
            for task in summary.tasks
            if task.failed and task.classification == "fixed by commit"
            for s in self.failure_lines(task)
            if is_failure_line_about_group(s["search"], summary.name)
            for name in names
        )

    def has_novel_failure(self, summary: GroupSummary, failure_push: "Push") -> bool:
        """Whether a task classified as 'fixed by commit' has a failure line which is
        new in the revision and matches no known bug, according to Treeherder.

        Crash report and Taskcluster error lines are ignored, as they contain unique
        identifiers which make them always look new.

        The failure is also considered new if a failure line of the group which
        matches no bug also appears in another task of the push classified as 'fixed
        by commit' (intermittent failures rarely repeat across tasks).

        When Treeherder has no failure lines for a task (e.g. when its log was too
        large to be parsed), the failure is considered new if the group crashed with
        a signature which also crashed another test on the push (intermittent
        crashes rarely crash several tests), according to the errorsummary of the
        tasks classified as 'fixed by commit', or if that can't be checked.
        """
        for task in self.fixed_by_commit_tasks(summary):
            suggestions = self.failure_lines(task)
            if suggestions:
                novel = any(
                    s.get("failure_new_in_rev")
                    and not s["bugs"].get("open_recent")
                    and not s["bugs"].get("all_others")
                    for s in suggestions
                    if not s["search"].startswith("PROCESS-CRASH")
                    and "[taskcluster:error]" not in s["search"]
                ) or self.line_repeated(task, summary.name, failure_push)
            else:
                try:
                    novel = self.crash_repeated(task, summary.name, failure_push)
                except Exception as e:
                    logger.debug(f"Crashes of {task.id} unavailable: {e}")
                    return True
            if novel:
                return True
        return False

    def line_repeated(self, task: Task, group: str, failure_push: "Push") -> bool:
        """Whether a failure line of the group in the task, matching no bug, also
        appears in another task of the push classified as 'fixed by commit'."""

        def lines(t: Task, unknown_only: bool) -> Set[str]:
            return {
                normalize_failure_line(s["search"])
                for s in self.failure_lines(t)
                if not any(g in s["search"] for g in GENERIC_FAILURE_LINES)
                and (
                    not unknown_only
                    or (
                        is_failure_line_about_group(s["search"], group)
                        and not any(
                            b.get("id")
                            for b in s["bugs"].get("open_recent", [])
                            + s["bugs"].get("all_others", [])
                        )
                    )
                )
            }

        own = lines(task, unknown_only=True)
        if not own:
            return False
        for other in failure_push.tasks:
            if (
                other is not task
                and other.failed
                and other.classification == "fixed by commit"
                and own & lines(other, unknown_only=False)
            ):
                return True
        return False

    @staticmethod
    def crash_repeated(task: TestTask, group: str, failure_push: "Push") -> bool:
        """Whether a crash of the group in the task has a signature which also crashed
        another test in a task of the push classified as 'fixed by commit'."""

        def crashes(t: TestTask) -> Iterator[Tuple[str, str, str]]:
            for g, tests in t.crashes.items():
                for test, signature in tests:
                    # Unknown signatures don't tell crashes apart.
                    if signature and "[Unknown]" not in signature:
                        yield test_info.normalize_group(g), test, signature

        signatures = {s for g, _, s in crashes(task) if g == group}
        if not signatures:
            return False
        tests = defaultdict(set)
        others = (
            t
            for t in failure_push.tasks
            if t is not task
            and isinstance(t, TestTask)
            and t.failed
            and t.classification == "fixed by commit"
        )
        for t in itertools.chain([task], others):
            for _, test, signature in crashes(t):
                if signature in signatures:
                    tests[signature].add(test)
                    if len(tests[signature]) > 1:
                        return True
        return False

    def named_culprit(self, name: Any, failure_push: "Push") -> Optional[int]:
        """The id of the push which most likely caused a configuration-group failure
        on `failure_push`, if a single candidate names the group: among the pushes
        backed out or bustage-fixed after the failure, between the last pass of the
        configuration-group and the failure, the one whose backout names a test of
        the group, or whose reland changed tests of the group."""
        group = name[1]
        named = None
        for push in itertools.islice(failure_push._iterate_parents(), MAX_DEPTH):
            if push != failure_push:
                summary = push.config_group_summaries.get(name)
                if summary is not None and summary.status == Status.PASS:
                    break
            analysis = push.attribution
            if analysis.fixed_after(failure_push) and group in analysis.named_groups:
                if named is not None:
                    # Several candidates name the group.
                    return None
                named = push.id
        return named
