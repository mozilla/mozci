# -*- coding: utf-8 -*-
import concurrent.futures
import copy
import itertools
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union

from loguru import logger

from mozci import config, data
from mozci.errors import (
    ChildPushNotFound,
    MissingDataError,
    ParentPushNotFound,
    PushNotFound,
    SourcesNotFound,
)
from mozci.task import (
    GroupSummary,
    LabelSummary,
    RunnableSummary,
    Status,
    Task,
    TestTask,
    get_configuration_from_label,
    get_suite_from_label,
)
from mozci.util.defs import FAILURE_CLASSES, TASK_FINAL_STATES
from mozci.util.hgmo import HgRev, parse_bugs
from mozci.util.memoize import memoize, memoized_property
from mozci.util.taskcluster import get_task

BASE_INDEX = "gecko.v2.{branch}.revision.{rev}"

MAX_DEPTH = config.get("maxdepth", 20)
"""The maximum number of parents or children to look for previous/next task runs,
when the task did not run on the currently considered push.
"""


class PushStatus(Enum):
    GOOD = 0
    BAD = 1
    UNKNOWN = 2


@dataclass
class Regressions:
    # These 3 attributes are dicts of list of tasks
    # each item being a single group, with its failing tasks
    real: Dict[str, List[TestTask]]
    intermittent: Dict[str, List[TestTask]]
    unknown: Dict[str, List[TestTask]]


@dataclass
class ToRetriggerOrBackfill:
    # These 3 attributes are dicts of list of tasks
    # each item being a single group, with its failing tasks
    real_retrigger: Dict[str, List[TestTask]]
    intermittent_retrigger: Dict[str, List[TestTask]]
    backfill: Dict[str, List[TestTask]]


def build_group_summaries(tasks) -> Dict[str, GroupSummary]:
    groups = defaultdict(list)

    for task in tasks:
        if not isinstance(task, TestTask):
            continue

        for group in task.groups:
            groups[group].append(task)

    return {group: GroupSummary(group, tasks) for group, tasks in groups.items()}


class Push:
    """A representation of a single push.

    Args:
        revs (list): List of revisions of commits in the push (top-most is the first element).
        branch (str): Branch to look on (default: autoland).
    """

    # static thread pool, to avoid spawning threads too often.
    THREAD_POOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, revs, branch="autoland"):
        if isinstance(revs, str):
            # Direct usage of a single revision reference
            self._revs = None
            head_revision = revs
            self._bugs = None
        elif isinstance(revs, list) and len(revs) > 0:
            if all(map(lambda r: isinstance(r, dict), revs)):
                # We should get detailed revision objects here
                # and get the list of Bugzilla Bug Ids from the description
                self._bugs = set(
                    itertools.chain(*[parse_bugs(rev.get("desc", "")) for rev in revs])
                )

                self._revs = [r["node"] for r in revs]
            else:
                # Support list of changeset IDs
                self._bugs = None
                self._revs = revs

            head_revision = self._revs[0]
        else:
            raise NotImplementedError(f"Cannot process revisions: {revs}")

        self.branch = branch
        self._hgmo = HgRev.create(head_revision, branch=self.branch)

        self._id = None
        self._date = None
        self._author = None

        # Need to use full hash in the index.
        if len(head_revision) == 40:
            self.rev = head_revision
        else:
            self.rev = self._hgmo.node

        self.index = BASE_INDEX.format(branch=self.branch, rev=self.rev)
        # Unique identifier for a Push across branches
        self.push_uuid = "{}/{}".format(self.branch, self.rev)

    @property
    def revs(self):
        if not self._revs:
            self._revs = [c["node"] for c in self._hgmo.changesets]
        return self._revs

    @memoized_property
    def backedoutby(self):
        """The revision of the commit which backs out this one or None.

        Returns:
            str or None: The commit revision which backs this push out (or None).
        """
        return self._hgmo.backedoutby

    @property
    def backedout(self):
        """Whether the push was backed out or not.

        Returns:
            bool: True if this push was backed out.
        """
        return bool(self.backedoutby)

    @property
    def bugs(self):
        """The bugs associated with the commits of this push.

        Returns:
            set: A set of bug IDs.
        """
        if self._bugs:
            return self._bugs

        self._bugs = self._hgmo.bugs
        return self._bugs

    @property
    def date(self):
        """The push date.

        Returns:
            int: The push date in ms since the epoch.
        """
        if self._date:
            return self._date

        self._date = self._hgmo.pushdate
        return self._date

    @property
    def id(self):
        """The push id.

        Returns:
            int: The push id.
        """
        if self._id:
            return self._id

        self._id = self._hgmo.pushid
        return self._id

    @property
    def author(self):
        """The push author.

        Returns:
            str: The push author.
        """
        if self._author:
            return self._author

        self._author = self._hgmo.pushauthor
        return self._author

    @property
    def is_finalized(self):
        """The push is finished or not.

        Returns:
            bool: True if the push is considered finalized (> 1 day old), else False.
        """
        yesterday = (datetime.now() - timedelta(days=1)).timestamp()
        return self.date < yesterday

    def create_push(self, push_id):
        result = HgRev.load_json_push(self.branch, push_id)

        push = Push(result["changesets"][::-1], branch=self.branch)
        # avoids the need to query hgmo to find this info
        push._id = push_id
        push._date = result["date"]

        return push

    @memoized_property
    def parent(self):
        """Returns the parent push of this push.

        Returns:
            Push: A `Push` instance representing the parent push.

        Raises:
            :class:`~mozci.errors.ParentPushNotFound`: When no suitable parent
                push can be detected.
        """
        # Mozilla-unified and try allow multiple heads, so we can't rely on
        # `self.id - 1` to be the parent.
        if self.branch not in ("mozilla-unified", "try"):
            return self.create_push(self.id - 1)

        changesets = [c for c in self._hgmo.changesets if c.get("phase") == "draft"]
        if not changesets:
            # Supports mozilla-unified as well as older automationrelevance
            # files that don't contain the phase.
            changesets = self._hgmo.changesets

        parents = changesets[0]["parents"]
        if len(parents) > 1:
            raise ParentPushNotFound(
                "merge commits are unsupported", rev=self.rev, branch=self.branch
            )

        # Search for this revision in the following repositories. We search
        # autoland last as it would run the fewest tasks, so a push from one of
        # the other repositories would be preferable.
        branches = ("mozilla-central", "mozilla-beta", "mozilla-release", "autoland")
        found_on = []
        parent_rev = parents[0]
        for branch in branches:
            try:
                hgmo = HgRev.create(parent_rev, branch=branch)
                head = hgmo.pushhead
            except PushNotFound:
                continue

            found_on.append(branch)

            # Revision exists in repo but is not the 'pushhead', so keep searching.
            if head != parent_rev:
                continue

            return Push(parent_rev, branch=branch)

        if found_on:
            branches = found_on
            reason = "was not a push head"
        else:
            # This should be extremely rare (if not impossible).
            reason = "was not found"

        branches = [
            b[len("mozilla-") :] if b.startswith("mozilla-") else b for b in branches
        ]
        msg = f"parent revision '{parent_rev[:12]}' {reason} on any of {', '.join(branches)}"
        raise ParentPushNotFound(msg, rev=self.rev, branch=self.branch)

    @memoized_property
    def child(self):
        """Returns the child push of this push.

        Returns:
            Push: A `Push` instance representing the child push.

        Raises:
            :class:`~mozci.errors.ChildPushNotFound`: When no suitable child
                push can be detected.
        """
        if self.branch not in ("mozilla-unified", "try"):
            try:
                return self.create_push(self.id + 1)
            except PushNotFound as e:
                raise ChildPushNotFound(
                    "child push does not exist", rev=self.rev, branch=self.branch
                ) from e

        raise ChildPushNotFound(
            f"finding child pushes not supported on {self.branch}",
            rev=self.rev,
            branch=self.branch,
        )

    @memoized_property
    def decision_task(self):
        """A representation of the decision task.

        Returns:
            Task: A `Task` instance representing the decision task.
        """
        index = self.index + ".taskgraph.decision"
        return Task.create(index=index)

    @memoized_property
    def tasks(self):
        """All tasks that ran on the push, including retriggers and backfills.

        Returns:
            list: A list of `Task` objects.
        """
        cached_tasks = config.cache.get(f"{self.push_uuid}/tasks")
        # Push is supposedly finalized, if a cache exists we can return it as tasks should've finished running
        if self.is_finalized and cached_tasks is not None:
            return cached_tasks

        logger.debug(f"Retrieving all tasks and groups which run on {self.rev}...")

        logger.debug(f"Gathering data about tasks that run on {self.rev}...")

        # Gather data about tasks that ran on a given push.
        try:
            # TODO: Skip tasks with `retry` as result
            tasks = data.handler.get("push_tasks", branch=self.branch, rev=self.rev)
        except MissingDataError:
            return []

        # Update gathered tasks with data retrieved from the cache
        completed_cached_tasks = {}
        if cached_tasks:
            completed_cached_tasks = {
                t.id: vars(t) for t in cached_tasks if t.state in TASK_FINAL_STATES
            }
            tasks = [{**t, **completed_cached_tasks.get(t["id"], {})} for t in tasks]

        logger.debug(f"Gathering task classifications for {self.rev}...")

        # Gather task classifications.
        try:
            classifications = data.handler.get(
                "push_tasks_classifications", branch=self.branch, rev=self.rev
            )
            for task in tasks:
                if task["id"] in classifications:
                    task.update(classifications[task["id"]])
        except MissingDataError:
            pass

        tasks = [Task.create(**task) for task in tasks]

        # Gather group data.
        logger.debug(f"Gathering test groups for {self.rev}...")
        done, _ = concurrent.futures.wait(
            [
                Push.THREAD_POOL_EXECUTOR.submit(
                    lambda task: task.retrieve_results(self), task
                )
                for task in tasks
                # No need to gather group data for a completed task that was already cached
                if task.id not in completed_cached_tasks and isinstance(task, TestTask)
            ],
            return_when=concurrent.futures.FIRST_EXCEPTION,
        )
        failed = set()
        for f in done:
            try:
                f.result()
            except SourcesNotFound as e:
                task = e.context["task"]
                failed.add(f"{task.id} - {task.label}")

        if failed:
            failed_str = "  \n".join(sorted(failed))
            logger.warning(
                f"Failed to get test groups from the following tasks:\n  {failed_str}"
            )

        logger.debug(f"Retrieved all tasks and groups which run on {self.rev}.")

        # Skip tier tasks greater than the tier passed in config
        tasks = [task for task in tasks if not task.tier or task.tier <= config.tier]

        # cachy's put() overwrites the value in the cache; add() would only add if its empty
        config.cache.put(
            f"{self.push_uuid}/tasks",
            tasks,
            config["cache"]["retention"],
        )

        logger.debug(f"Cached all tasks and groups which run on {self.rev}.")

        return tasks

    @property
    def task_labels(self):
        """The set of task labels that ran on this push.

        Returns:
            set: A set of task labels (str).
        """
        return set(t.label for t in self.tasks)

    @memoized_property
    def is_manifest_level(self):
        """Whether a non-default manifest loader was used for this push.

        Returns:
            bool: True if a non-default manifest loader was used.
        """
        return (
            self.decision_task.get_artifact("public/parameters.yml")[
                "test_manifest_loader"
            ]
            != "default"
        )

    @memoized_property
    def target_task_labels(self):
        """The set of all task labels that could possibly run on this push.

        Returns:
            set: A set of task labels.
        """
        return set(self.decision_task.get_artifact("public/target-tasks.json"))

    @memoized_property
    def scheduled_task_labels(self):
        """The set of task labels that were originally scheduled to run on this push.

        This excludes backfills and Add New Jobs.

        Returns:
            set: A set of task labels (str).
        """
        tasks = self.decision_task.get_artifact("public/task-graph.json").values()
        return {t["label"] for t in tasks}

    @property
    def unscheduled_task_labels(self):
        """The set of task labels from tasks that were not originally scheduled on
        the push (i.e they were scheduled via backfill or Add New Jobs).

        Returns:
            set: A set of task labels (str).
        """
        return self.task_labels - self.scheduled_task_labels

    @memoized_property
    def config_group_summaries(self):
        """All group summaries, on given configurations, combining retriggers.

        Returns:
            dict: A dictionary of the form {(<configuration>, <group>): [<GroupSummary>]}.
        """
        config_groups = defaultdict(list)

        for task in self.tasks:
            if not isinstance(task, TestTask):
                continue

            for group in task.groups:
                config_groups[(task.configuration, group)].append(task)

        return {
            config_group: GroupSummary(config_group[1], tasks)
            for config_group, tasks in config_groups.items()
        }

    @memoized_property
    def group_summaries(self):
        """All group summaries combining retriggers.

        Returns:
            dict: A dictionary of the form {<group>: [<GroupSummary>]}.
        """
        return build_group_summaries(self.tasks)

    @memoized_property
    def label_summaries(self) -> Dict[str, LabelSummary]:
        """All label summaries combining retriggers.

        Returns:
            dict: A dictionary of the form {<label>: [<LabelSummary>]}.
        """
        labels = defaultdict(list)
        for task in self.tasks:
            # We can't consider tasks that were chunked in the taskgraph for finding label-level regressions
            # because tasks with the same name on different pushes might contain totally different tests.
            if task.is_tests_grouped:
                continue

            labels[task.label].append(task)
        return {label: LabelSummary(label, tasks) for label, tasks in labels.items()}

    @memoized_property
    def duration(self):
        """The total duration of all tasks that ran on the push.

        Returns:
            int: Runtime in hours.
        """
        return int(sum(t.duration for t in self.tasks) / 3600)

    @memoized_property
    def scheduled_duration(self):
        """The total runtime of tasks excluding retriggers and backfills.

        Returns:
            int: Runtime in hours.
        """
        seen = set()
        duration = 0
        for task in self.tasks:
            if task.label not in self.scheduled_task_labels:
                continue

            if task.label in seen:
                continue

            seen.add(task.label)
            duration += task.duration

        return int(duration / 3600)

    def is_group_running(self, group):
        """Checks if the provided group is still running on this push.

        Returns:
            bool: True, if the group is still running.
                  False, if the group is completed.
        """
        running_tasks = [
            task for task in self.tasks if task.state not in TASK_FINAL_STATES
        ]

        group_types = set()
        for task in group.tasks:
            suite = get_suite_from_label(task.label)
            assert (
                suite is not None
            ), f"Couldn't parse suite for {task.label} ({task.id})"
            group_types.add(suite)

        if all(task.is_tests_grouped for task in group.tasks):
            for task in running_tasks:
                if get_suite_from_label(task.label) not in group_types:
                    continue

                task_def = get_task(task.id)
                test_paths = json.loads(
                    task_def["payload"]
                    .get("env", {})
                    .get("MOZHARNESS_TEST_PATHS", "{}")
                )
                if group.name in {
                    name for names in test_paths.values() for name in names
                }:
                    return True
            return False

        running_types = {get_suite_from_label(task.label) for task in running_tasks}
        return not group_types.isdisjoint(running_types)

    def _is_classified_as_cause(self, first_appearance_push, classifications):
        """Checks a 'fixed by commit' classification to figure out what push it references.

        Returns:
            bool or None: True, if the classification references this push.
                          False, if the classification references another push.
                          None, if it is not clear what the classification references.
        """
        fixed_by_commit_classification_notes = set(
            n[:12]
            for c, n in classifications
            if c == "fixed by commit"
            if n is not None
        )

        if len(fixed_by_commit_classification_notes) == 0:
            return None

        # If the failure was classified as fixed by commit, and the fixing commit
        # is a backout of the current push, it is definitely a regression of the
        # current push.
        # If the failure was classified as fixed by commit, and the fixing commit
        # is a backout of another push, it is definitely not a regression of the
        # current push.
        # Unless some condition holds which makes us doubt about the correctness of the
        # classification.
        # - the backout commit also backs out one of the commits of this push;
        # - the other push backed-out by the commit which is mentioned in the classification
        #   is landed after the push where the failure occurs (so, it can't have caused it);
        # - the backout push also contains a commit backing out one of the commits of this push.
        for classification_note in fixed_by_commit_classification_notes:
            fix_hgmo = HgRev.create(classification_note, branch=self.branch)
            try:
                fix_hgmo.backouts
            except PushNotFound:
                logger.warning(
                    f"Classification note ({classification_note}) references a revision which does not exist on push {first_appearance_push.rev}"
                )
                return None

            self_fix = None
            other_fixes = set()

            # If the backout commit also backs out one of the commits of this push, then
            # we can consider it as a regression of this push.
            # NOTE: this should never happen in practice because of current development
            # practices.
            for backout, backedouts in fix_hgmo.backouts.items():
                if backout[:12] != classification_note[:12]:
                    continue

                if any(
                    rev[:12] in {backedout[:12] for backedout in backedouts}
                    for rev in self.revs
                ):
                    self_fix = backout[:12]
                    break

            # Otherwise, if the backout push also contains the backout commit of this push,
            # we can consider it as a regression of this push.
            if self.backedout:
                for backout in fix_hgmo.backouts:
                    if backout[:12] == self.backedoutby[:12]:
                        self_fix = backout[:12]
                        break

            # If one of the commits in the backout push is a bustage fix, then we could
            # consider it as a regression of this push.
            if self_fix is None:
                for bug in self.bugs:
                    if bug in fix_hgmo.bugs_without_backouts:
                        self_fix = fix_hgmo.bugs_without_backouts[bug][:12]
                        break

            # Otherwise, as long as the commit which was backed-out was landed **before**
            # the appearance of this failure, we can be sure it was its cause and so
            # the current push is not at fault.
            # TODO: We should actually check if the failure was already happening in the parents
            # and compare the backout push ID with the the ID of first parent where it failed.
            for backout, backedouts in fix_hgmo.backouts.items():
                if self.backedout and backout[:12] == self.backedoutby[:12]:
                    continue

                if any(
                    HgRev.create(backedout, branch=self.branch).pushid
                    <= first_appearance_push.id
                    for backedout in backedouts
                ):
                    other_fixes.add(backout[:12])

            # If the backout push contains a bustage fix of another push, then we could
            # consider it as a regression of another push.
            if len(fix_hgmo.bugs_without_backouts) > 0:
                other_parent = first_appearance_push
                for other_parent in other_parent._iterate_parents(MAX_DEPTH):
                    if other_parent != self:
                        for bug in other_parent.bugs:
                            if bug in fix_hgmo.bugs_without_backouts:
                                other_fixes.add(
                                    fix_hgmo.bugs_without_backouts[bug][:12]
                                )

            if self_fix and other_fixes:
                # If the classification points to a commit in the middle of the backout push and not the backout push head,
                # we can consider the classification to be correct.
                if (
                    self_fix != fix_hgmo.pushhead[:12]
                    and classification_note[:12] == self_fix
                    and classification_note[:12] not in other_fixes
                ):
                    return True
                elif any(
                    other_fix != fix_hgmo.pushhead[:12]
                    and classification_note[:12] == other_fix
                    and classification_note[:12] != self_fix
                    for other_fix in other_fixes
                ):
                    return False

                return None

            if self_fix:
                return True

            if other_fixes:
                return False

        return None

    def _iterate_children(self, max_depth=None):
        other = self
        for i in itertools.count():
            yield other

            # Optimization to load child json-pushes data in a single query (up
            # to MAX_DEPTH at a time).
            next_id = other.id + 1
            if next_id not in HgRev.JSON_PUSHES_CACHE:
                depth = max_depth or MAX_DEPTH
                HgRev.load_json_pushes_between_ids(
                    self.branch, other.id, next_id + depth - i
                )

            try:
                other = other.child
            except ChildPushNotFound:
                break

            if max_depth is not None and i == max_depth:
                break

    def _iterate_parents(self, max_depth=None):
        other = self
        for i in itertools.count():
            yield other

            # Optimization to load parent json-pushes data in a single query (up
            # to max_depth at a time).
            prev_id = other.id - 1
            if prev_id not in HgRev.JSON_PUSHES_CACHE:
                depth = max_depth or MAX_DEPTH
                HgRev.load_json_pushes_between_ids(
                    self.branch, max(prev_id - 1 - depth + i, 0), prev_id
                )

            try:
                other = other.parent
            except ParentPushNotFound:
                break

            if max_depth is not None and i == max_depth:
                break

    def _iterate_failures(
        self, runnable_type: str, max_depth: Optional[int] = None
    ) -> Iterator[
        Tuple[
            "Push",
            Dict[str, Tuple[float, RunnableSummary]],
            Dict[str, Tuple[float, RunnableSummary]],
            Dict[str, List[Optional[bool]]],
        ]
    ]:
        ever_passing_runnables = set()
        passing_runnables = set()
        candidate_regressions = {}

        first_appearance = {}

        classified_as_cause: Dict[str, List[Optional[bool]]] = defaultdict(list)

        count = 0
        for other in self._iterate_children(max_depth):
            for name, summary in getattr(other, f"{runnable_type}_summaries").items():
                # test-verify is special, we don't want to look at children pushes.
                if (
                    self != other
                    and runnable_type == "label"
                    and ("test-verify" in name or "test-coverage" in name)
                ):
                    break

                if summary.status == Status.PASS:
                    ever_passing_runnables.add(name)
                    if name not in candidate_regressions:
                        passing_runnables.add(name)
                    continue

                if all(c not in FAILURE_CLASSES for c, n in summary.classifications):
                    classified_as_cause[name].append(None)
                    if name not in candidate_regressions:
                        passing_runnables.add(name)
                    continue

                if name not in first_appearance:
                    first_appearance[name] = other

                is_classified_as_cause = self._is_classified_as_cause(
                    first_appearance[name], summary.classifications
                )
                if is_classified_as_cause is True:
                    classified_as_cause[name].append(True)
                elif is_classified_as_cause is False:
                    classified_as_cause[name].append(False)
                    continue

                if name in candidate_regressions:
                    # It failed in one of the pushes between the current and its
                    # children, we don't want to increase the previous distance.
                    continue

                candidate_regressions[name] = (float(count), summary)

            adjusted_candidate_regressions = copy.deepcopy(candidate_regressions)

            for name in candidate_regressions.keys():
                # If the classifications are all either 'intermittent' or 'fixed by commit' pointing
                # to this push, and the last classification is 'fixed by commit', then consider it a
                # sure regression. We are assuming sheriff's information might be wrong at first and
                # adjusted later.
                if (
                    len(classified_as_cause[name]) > 0
                    and all(
                        result is True or result is None
                        for result in classified_as_cause[name]
                    )
                    and classified_as_cause[name][-1] is True
                ):
                    adjusted_candidate_regressions[name] = (
                        -math.inf,
                        candidate_regressions[name][1],
                    )

                # If there is at least one classification that points to another push and no classification
                # that points to this push, remove the regerssion from the candidate list.
                elif any(
                    result is False for result in classified_as_cause[name]
                ) and not any(result is True for result in classified_as_cause[name]):
                    del adjusted_candidate_regressions[name]

                # If the runnable passed first and failed in a child push and there is no classification pointing
                # to this push or there is at least one pointing to another push, remove the regression from the
                # candidate list.
                elif name in passing_runnables and (
                    not any(result is True for result in classified_as_cause[name])
                    or any(result is False for result in classified_as_cause[name])
                ):
                    del adjusted_candidate_regressions[name]

                # If the runnable passed in any child push and the classification for the last seen failure is
                # 'intermittent', remove the regression from the candidate list.
                elif (
                    len(classified_as_cause[name]) > 0
                    and name in ever_passing_runnables
                    and classified_as_cause[name][-1] is None
                ):
                    del adjusted_candidate_regressions[name]

                # If all classifications are 'intermittent', remove the regression from the candidate list.
                elif len(classified_as_cause[name]) > 0 and all(
                    result is None for result in classified_as_cause[name]
                ):
                    del adjusted_candidate_regressions[name]

            yield other, adjusted_candidate_regressions, candidate_regressions, classified_as_cause
            count += 1

    def get_candidate_regressions(
        self, runnable_type: str
    ) -> Dict[str, Tuple[float, RunnableSummary]]:
        """Retrieve the set of "runnables" that are regression candidates for this push.

        A "runnable" can be any group of tests, e.g. a label, a manifest across platforms,
        a manifest on a given platform.

        A candidate regression is any runnable for which at least one
        associated task failed (therefore including intermittents), and which
        is either not classified or fixed by commit.

        Returns:
            set: Set of runnable names (str).
        """
        logger.debug(f"Retrieving candidate regressions for {self.rev}...")

        max_depth = None if self.backedout or self.bustage_fixed_by else MAX_DEPTH

        for other, candidate_regressions, _, _ in self._iterate_failures(
            runnable_type, max_depth
        ):
            # Break early if we reached the backout of this push, since any failure
            # after that won't be blamed on this push.
            try:
                next_child = other.child
            except ChildPushNotFound:
                break

            if self.branch != "try" and (
                self.backedoutby in next_child.revs
                or self.bustage_fixed_by in next_child.revs
            ):
                logger.debug(
                    f"Reached a backout/bustage fix of {self.rev}, stop looking for failures in children."
                )

                # Runnables that still fail after the backout, can't be considered
                # regressions of the push.
                # NOTE: There could be another push in between the push of interest and its
                # backout that causes another failure in the same runnable, but it is very
                # unlikely (especially for finer granularities, such as "group").
                for name, summary in getattr(
                    next_child, f"{runnable_type}_summaries"
                ).items():
                    if (
                        name in candidate_regressions
                        and summary.status != Status.PASS
                        and all(
                            c in FAILURE_CLASSES for c, n in summary.classifications
                        )
                    ):
                        del candidate_regressions[name]

                break

        return candidate_regressions

    @memoized_property
    def bustage_fixed_by(self) -> Optional[str]:
        """The revision of the commit which 'bustage fixes' this one or None.

        We detect if a push was 'bustage fixed' with a simple heuristic:

            - there is a close enough child push where the task/group passes;
            - the child push where the task/group passes is associated to the same bug
              as the push of interest.

        Returns:
            str or None: The commit revision which 'bustage fixes' this push (or None).
        """
        if self.backedout:
            return None

        def fix_same_bugs(push1, push2):
            return len(push1.bugs & push2.bugs) > 0

        # Skip checking regressions if we can't find any possible candidate.
        possible_bustage_fixes = set(
            other
            for other in self._iterate_children(MAX_DEPTH)
            if self != other and fix_same_bugs(self, other)
        )
        if len(possible_bustage_fixes) == 0:
            return None

        def find(runnable_type: str) -> Optional[str]:
            for other, candidate_regressions, _, _ in self._iterate_failures(
                runnable_type, MAX_DEPTH
            ):
                if other == self or other not in possible_bustage_fixes:
                    continue

                other_summaries = getattr(other, f"{runnable_type}_summaries")

                if any(
                    name in other_summaries
                    and other_summaries[name].status == Status.PASS
                    for name in candidate_regressions
                ):
                    return other.rev

                possible_bustage_fixes.remove(other)
                if len(possible_bustage_fixes) == 0:
                    break

            return None

        return find("label") or find("config_group")

    @memoize
    def get_regressions(
        self, runnable_type: str, historical_analysis: bool = True
    ) -> Dict[str, int]:
        """All regressions, both likely and definite.

        Each regression is associated with an integer, which is the number of
        parent and children pushes that didn't run the runnable. A count of 0 means
        the runnable failed on the current push and passed on the previous push.
        A count of 3 means there were three pushes between the failure and the
        last time the task passed (so any one of them could have caused it).
        A count of MAX_DEPTH means that the maximum number of parents were
        searched without finding the task and we gave up.

        Returns:
            dict: A dict of the form {<str>: <int>}.
        """
        regressions: Dict[str, int] = {}

        # If the push was not backed-out and was not "bustage fixed", it can't
        # have caused regressions.
        if (
            (historical_analysis or self.is_finalized)
            and self.branch != "try"
            and not self.backedout
            and not self.bustage_fixed_by
        ):
            return regressions

        for name, (count, failure_summary) in self.get_candidate_regressions(
            runnable_type
        ).items():
            other = self.parent
            prior_regression = False

            # test-verify is special, we can assume the test-verify task is not the same as the one
            # in the parent pushes.
            if (
                runnable_type != "label"
                or "test-verify" not in name
                or "test-coverage" not in name
            ):
                found_in_parent = False
                for other in other._iterate_parents(MAX_DEPTH):
                    if count < 0:
                        break

                    runnable_summaries = getattr(other, f"{runnable_type}_summaries")

                    if name in runnable_summaries:
                        found_in_parent = True
                        summary = runnable_summaries[name]

                        # If the failure is not intermittent...
                        if not failure_summary.is_intermittent:
                            # ...and it failed permanently in the first parent where it ran, it is a
                            # prior regression.
                            # Otherwise, if it passed or was intermittent, it is likely not a prior
                            # regression.
                            if (
                                summary.status != Status.PASS
                                and not summary.is_intermittent
                            ):
                                prior_regression = True

                            break

                        # If the failure is intermittent and it failed intermittently in a close
                        # parent too, it is likely a prior regression.
                        # We need to explore the parent's parents instead if it passed or failed
                        # consistently in the parent.
                        elif summary.is_intermittent:
                            prior_regression = True
                            break

                    if not found_in_parent:
                        count += 1

            # Given that our "bustage fix" detection is a heuristic which might fail, we
            # penalize regressions for pushes which weren't backed-out by doubling their count
            # (basically, we consider the push to be further away from the failure, which makes
            # it more likely to fall outside of MAX_DEPTH).
            if (
                (historical_analysis or self.is_finalized)
                and self.branch != "try"
                and not self.backedout
            ):
                count *= 2

            # Also penalize cases where the status was intermittent.
            if failure_summary.is_intermittent:
                count *= 2

            if not prior_regression and count <= MAX_DEPTH:
                regressions[name] = int(count) if count > 0 else 0

        return regressions

    def get_possible_regressions(
        self, runnable_type: str, historical_analysis: bool = True
    ) -> Set[str]:
        """The set of all runnables that may have been regressed by this push.

        A possible regression is a candidate_regression that didn't run on one or
        more parent pushes.

        Returns:
            set: Set of runnables (str).
        """
        return set(
            name
            for name, count in self.get_regressions(
                runnable_type, historical_analysis
            ).items()
            if count > 0
        )

    def get_likely_regressions(
        self, runnable_type: str, historical_analysis: bool = True
    ) -> Set[str]:
        """The set of all runnables that were likely regressed by this push.

        A likely regression is a candidate_regression that both ran and passed
        on the immediate parent push. It still isn't a sure thing as the task
        could be intermittent.

        Returns:
            set: Set of runnables (str).
        """
        return set(
            name
            for name, count in self.get_regressions(
                runnable_type, historical_analysis
            ).items()
            if count == 0
        )

    def classify_regressions(
        self,
        intermittent_confidence_threshold: float = 0.8,
        real_confidence_threshold: float = 0.9,
        use_possible_regressions: bool = False,
        unknown_from_regressions: bool = True,
        consider_children_pushes_configs: bool = True,
        cross_config_counts: Optional[Tuple[int, int]] = (2, 2),
        consistent_failures_counts: Optional[Tuple[int, int]] = (2, 3),
    ) -> Tuple[Regressions, ToRetriggerOrBackfill]:
        """
        Use group classification data from bugbug to classify all likely
        regressions into three categories: real, intermittent or unknown failures

        Output:
        A dict with several lists of task groups:
          - real: set of tasks that are definitely real failures
          - intermittent: set of tasks that are definitely intermittents
          - unknown: set of tasks we don't have enough information about
        And a dict with several lists of task groups:
          - real_retrigger: set of tasks to retrigger with consistent_failures_counts[1]
          - intermittent_retrigger: set of tasks to retrigger with consistent_failures_counts[0]
          - backfill: set of tasks to backfill
        """
        cache_prefix = f"{self.push_uuid}/classify_group_tasks/"

        # Retrieve test selection data for that push, from cache or bugbug
        bugbug_selection = config.cache.get(cache_prefix + "test_selection")
        if bugbug_selection is None:
            bugbug_selection = self.get_test_selection_data()

            config.cache.put(
                cache_prefix + "test_selection",
                bugbug_selection,
                config["cache"]["retention"],
            )

        # Fetch likely group regressions for that push from treeherder + Taskcluster
        # We do not cache these results as we might want to analyze in-progress
        # pushes and keep updating these values
        likely_regressions = self.get_likely_regressions("group", False)
        possible_regressions = self.get_possible_regressions("group", False)
        groups_regressions = likely_regressions
        if use_possible_regressions:
            groups_regressions |= possible_regressions

        # Get task groups with high and low confidence from bugbug scheduling
        groups_high = {
            g
            for g, confidence in bugbug_selection["groups"].items()
            if confidence >= real_confidence_threshold
        }
        groups_low = {
            g
            for g, confidence in bugbug_selection["groups"].items()
            if confidence < intermittent_confidence_threshold
        }
        logger.debug(f"Got {len(groups_high)} groups with high confidence")
        logger.debug(f"Got {len(groups_low)} groups with low confidence")

        # Classify task groups regarding cross config failure and overall failure
        # - if a group is failing in all tasks, then it is a "cross-config" failure
        # - if a group is failing only in some tasks but not all, then it is not a "cross-config" failure
        # Consider groups in following pushes too in case there is a failure due to this push in a child push.
        push_groups = self.group_summaries.values()
        if consider_children_pushes_configs:
            all_groups = build_group_summaries(
                sum((push.tasks for push in self._iterate_children(MAX_DEPTH)), [])
            ).values()
        else:
            all_groups = push_groups

        groups_relevant_failure = {
            g.name
            for g in all_groups
            if (
                cross_config_counts is not None
                and g.is_cross_config_failure(cross_config_counts[1])
            )
            or (
                consistent_failures_counts is not None
                and g.is_config_consistent_failure(consistent_failures_counts[1])
            )
        }

        groups_non_relevant_failure = {
            g.name
            for g in all_groups
            if g.status != Status.PASS
            and (
                (
                    cross_config_counts is None
                    or g.is_cross_config_failure(cross_config_counts[0]) is False
                )
                and (
                    consistent_failures_counts is None
                    or g.is_config_consistent_failure(consistent_failures_counts[0])
                    is False
                )
            )
        }

        groups_failing = {g.name for g in all_groups if g.status != Status.PASS}

        groups_no_confidence = {
            g.name
            for g in all_groups
            if g.name not in list(bugbug_selection["groups"].keys())
        }
        logger.debug(
            f"Got {len(groups_relevant_failure)} groups with cross-config or config-consistent failures"
        )
        logger.debug(
            f"Got {len(groups_non_relevant_failure)} groups with no cross-config and no config-consistent failures"
        )
        logger.debug(
            f"Got {len(groups_failing)} groups failing in the push or one of its children"
        )
        logger.debug(
            f"Got {len(groups_no_confidence)} groups without bugbug confidence"
        )

        # Real failure are groups with likely regressions that were selected with high confidence
        # AND failing across config
        real_failures = groups_regressions & groups_relevant_failure & groups_high

        # Intermittent failures are groups that were NOT selected (low confidence)
        # OR without any confidence from bugbug (too low confidence)
        # AND are not failing across config
        # Only consider groups in this push because we don't care about intermittents in other pushes.
        # We only use children pushes information to determine cross-config or config-consistent state.
        all_intermittent_failures = groups_non_relevant_failure & groups_low.union(
            groups_no_confidence
        )
        intermittent_failures = (
            set(g.name for g in push_groups) & all_intermittent_failures
        )

        # Unknown failures all the remaining failing groups that are not real nor intermittent
        unknown_failures = (
            (groups_regressions if unknown_from_regressions else groups_failing)
            - real_failures
            - all_intermittent_failures
        )

        groups_still_running = set()
        for group_name in real_failures:
            for parent in self._iterate_parents(max_depth=MAX_DEPTH):
                # If the group run in a parent, then we don't care if it's still running in a grandparent.
                if group_name in parent.group_summaries:
                    break

                if parent.is_group_running(self.group_summaries[group_name]):
                    groups_still_running.add(group_name)
                    break

        logger.debug(
            f"Got {len(groups_still_running)} groups failing in this push but still running in a parent push, so we can't know if they are regressions from this push"
        )
        real_failures -= groups_still_running
        unknown_failures |= groups_still_running

        logger.debug(f"Got {len(real_failures)} real failures")
        logger.debug(f"Got {len(intermittent_failures)} intermittent failures")
        logger.debug(f"Got {len(unknown_failures)} unknown failures")

        def _map_failing_tasks(groups):
            # Link all the failing tasks on the given groups
            return {name: self.group_summaries[name].failing_tasks for name in groups}

        # See the following comment that explains how we decide the groups to retrigger/backfill
        # https://github.com/mozilla/mozci/issues/654#issuecomment-1139488070
        real_failures_to_be_retriggered = (
            groups_regressions & groups_high
        ) - groups_relevant_failure
        real_groups_still_running = groups_still_running | {
            group_name
            for group_name in real_failures_to_be_retriggered
            if self.is_group_running(self.group_summaries[group_name])
        }
        real_failures_to_be_retriggered -= real_groups_still_running

        intermittent_failures_to_be_retriggered = (
            set(g.name for g in push_groups if g.status != Status.PASS)
            & groups_low.union(groups_no_confidence)
        ) - groups_non_relevant_failure
        intermittent_groups_still_running = groups_still_running | {
            group_name
            for group_name in intermittent_failures_to_be_retriggered
            if self.is_group_running(self.group_summaries[group_name])
        }
        intermittent_failures_to_be_retriggered -= intermittent_groups_still_running

        failures_to_be_backfilled = list(
            possible_regressions.difference(likely_regressions) & groups_high
        )

        # Sorting groups to be backfilled, first ones will be groups present in groups_relevant_failure with a high confidence
        failures_to_be_backfilled.sort(
            key=lambda group: int(group in groups_relevant_failure)
            + bugbug_selection["groups"].get(group, 0)
        )
        failures_to_be_backfilled.reverse()

        # Output real, intermittent and unknown groupfailures
        # along with their failing configurations + groupfailures to retrigger/backfill
        return Regressions(
            real=_map_failing_tasks(real_failures),
            intermittent=_map_failing_tasks(intermittent_failures),
            unknown=_map_failing_tasks(unknown_failures),
        ), ToRetriggerOrBackfill(
            real_retrigger=_map_failing_tasks(real_failures_to_be_retriggered),
            intermittent_retrigger=_map_failing_tasks(
                intermittent_failures_to_be_retriggered
            ),
            backfill=_map_failing_tasks(failures_to_be_backfilled),
        )

    def classify(
        self,
        intermittent_confidence_threshold: float = 0.8,
        real_confidence_threshold: float = 0.9,
        use_possible_regressions: bool = False,
        unknown_from_regressions: bool = True,
        consider_children_pushes_configs: bool = True,
        cross_config_counts: Optional[Tuple[int, int]] = (2, 2),
        consistent_failures_counts: Optional[Tuple[int, int]] = (2, 3),
    ) -> Tuple[PushStatus, Regressions, ToRetriggerOrBackfill]:
        """
        Classify the overall push state using its group tasks states
        from classify_regressions:
        - bad push: when there are any task group with real failures
        - good push: when there are only intermittent failures
        - unknown state: when other tasks are failing
        """
        regressions, to_retrigger_or_backfill = self.classify_regressions(
            intermittent_confidence_threshold,
            real_confidence_threshold,
            use_possible_regressions,
            unknown_from_regressions,
            consider_children_pushes_configs,
            cross_config_counts,
            consistent_failures_counts,
        )

        # If there are any real failures, it's a bad push
        if len(regressions.real) > 0:
            return PushStatus.BAD, regressions, to_retrigger_or_backfill

        # If all failures are intermittent, it's a good push
        if len(regressions.unknown) == 0 and len(regressions.intermittent) >= 0:
            return PushStatus.GOOD, regressions, to_retrigger_or_backfill

        # Fallback to unknown
        return PushStatus.UNKNOWN, regressions, to_retrigger_or_backfill

    @memoize
    def get_shadow_scheduler_tasks(self, name: str) -> List[dict]:
        """Returns all tasks the given shadow scheduler would have scheduled,
        or None if the given scheduler didn't run.

        Args:
            name (str): The name of the shadow scheduler to query.

        Returns:
            set: All task labels that would have been scheduled.
        """
        index = self.index + ".source.shadow-scheduler-{}".format(name)
        task = Task.create(index=index)

        optimized = task.get_artifact("public/shadow-scheduler/optimized-tasks.json")
        return list(optimized.values())

    @property
    def shadow_scheduler_names(self) -> List[str]:
        return sorted(
            label.split("shadow-scheduler-")[1]
            for label in self.scheduled_task_labels
            if "shadow-scheduler" in label
        )

    def generate_all_shadow_scheduler_tasks(
        self,
    ) -> Iterator[Tuple[str, Union[Set[str], Exception]]]:
        """Generates all tasks from all of the shadow schedulers that ran on the push.

        Yields:
            tuple: Of the form (<name>, {<label>}) where the first value is the
            name of the shadow scheduler and the second is the set of tasks it
            would have scheduled, or an exception instance in case the shadow
            scheduler failed.
        """
        for name in sorted(self.shadow_scheduler_names):
            try:
                yield name, set(
                    t["label"] for t in self.get_shadow_scheduler_tasks(name)
                )
            except Exception as e:
                yield name, e

    def generate_all_shadow_scheduler_config_groups(
        self,
    ) -> Iterator[Tuple[str, Union[Set[Tuple[str, str]], Exception]]]:
        """Generates all groups from all tasks from all of the shadow schedulers that
           ran on the push.

        Yields:
            tuple: Of the form (<name>, {(<config>, <group>)}) where the first value
            is the name of the shadow scheduler and the second is the set of groups, on
            given configurations, it would have scheduled, or an exception instance in
            case the shadow scheduler failed.
        """
        for name in sorted(self.shadow_scheduler_names):
            try:
                config_groups = {
                    (get_configuration_from_label(task["label"]), group)
                    for task in self.get_shadow_scheduler_tasks(name)
                    for group in task["attributes"].get("test_manifests", [])
                }

                yield name, config_groups
            except Exception as e:
                yield name, e

    @memoize
    def get_test_selection_data(self):
        """Retrieves Push schedules from various data sources.

        As for now, the 'push_test_selection_data' contract is fulfilled by two data sources:
        bugbug -> The call will be retried until we receive data or it times out/fails.
        taskcluster -> The call will be made one time.
        """
        return data.handler.get(
            "push_test_selection_data", branch=self.branch, rev=self.rev
        )

    def get_existing_classification(self, environment: str) -> PushStatus:
        """Retrieves existing classification from Taskcluster artifacts

        Do not memoize this method as the classification may change every few minutes remotely
        """
        existing = data.handler.get(
            "push_existing_classification",
            branch=self.branch,
            rev=self.rev,
            environment=environment,
        )

        # Convert from raw string to enum
        return PushStatus[str(existing)]

    def __repr__(self):
        return f"{super(Push, self).__repr__()} rev='{self.rev}'"


def make_push_objects(**kwargs):
    try:
        if "from_date" in kwargs and "to_date" in kwargs:
            # Load by date range
            pushes_data = data.handler.get("push_revisions", **kwargs)
        elif "nb" in kwargs:
            # Load latest pushes
            pushes_data = data.handler.get("pushes", **kwargs)
        else:
            raise Exception(
                "Unsupported parameters (either from_date and to_date or nb are required)"
            )
    except MissingDataError:
        return []

    pushes = []

    for push_data in pushes_data:
        extra = {}
        if "branch" in kwargs:
            extra = {"branch": kwargs["branch"]}

        cur = Push(push_data["revs"], **extra)

        # avoids the need to query hgmo to find this info
        cur._id = push_data["pushid"]
        cur._date = push_data["date"]

        pushes.append(cur)

    pushes.sort(key=lambda p: p._id)

    for i, cur in enumerate(pushes):
        if i != 0:
            cur._parent = pushes[i - 1]

        if i != len(pushes) - 1:
            cur._child = pushes[i + 1]

    return pushes


def make_summary_objects(from_date, to_date, branch, type):
    """Returns a list of summary objects matching the parameters.

    When invoked with a `type` argument, this method will return a list of
    Summary objects of the corresponding type. For example, `type='group'` will
    return a list of GroupSummary objects.

    Args:
        from_date (str): String representing a date value.
        to_date (str): String representing a date value.
        branch (str): String that references one of the Mozilla CI's repositories.
        type (str): String that references one of the supported Summary types.

    Returns:
        list: List of Summary objects, or an empty list.

    """
    # Retrieve the function by name using the provided `type` argument.
    func = "__make_{}_summary_objects".format(type).lower()

    # If the method name `func` (maps to either of the private methods)
    # is not found, then return an empty list.
    if not func:
        return []

    # Obtain list of all pushes for the specified branch, from_date and to_date.
    pushes = make_push_objects(from_date=from_date, to_date=to_date, branch=branch)

    # Flatten list of tasks for every push to a 1-dimensional list.
    tasks = sorted(
        [task for push in pushes for task in push.tasks], key=lambda x: x.label
    )

    summaries = globals()[func](tasks)

    # Sort by either the label (LabelSummary) or name (GroupSummary).
    summaries.sort(key=lambda x: (getattr(x, "label", "name")))
    return summaries


def __make_label_summary_objects(tasks):
    """Generates a list of LabelSummary objects from a list of tasks.

    Args:
        tasks (list): List of Task objects.

    Returns:
        list: List of LabelSummary objects.
    """
    # Make a mapping keyed by task.label containing list of Task objects.
    tasks_by_config = defaultdict(lambda: defaultdict(list))
    for task in tasks:
        tasks_by_config[task.configuration][task.label]["tasks"].append(task)

    return [
        LabelSummary(label, tasks)
        for config in tasks_by_config.keys()
        for label, tasks in tasks_by_config[config].items()
    ]


def __make_group_summary_objects(tasks):
    """Generates a list of GroupSummary objects from a list of tasks.

    Args:
        tasks (list): List of Task objects.

    Returns:
        list: List of GroupSummary objects.
    """
    # Make a mapping keyed by group name containing list of Task objects.
    tasks_by_config = defaultdict(lambda: defaultdict(list))
    for task in tasks:
        for result in task.results:
            # Build the mapping of group to the group durations and TestTask objects.
            tasks_by_config[task.configuration][result.group].append(task)

    return [
        GroupSummary(key, tasks)
        for config in tasks_by_config.keys()
        for key, tasks in tasks_by_config[config].items()
    ]
