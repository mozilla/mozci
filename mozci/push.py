# -*- coding: utf-8 -*-
import concurrent.futures
import copy
import itertools
import math
from argparse import Namespace
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union

from loguru import logger

from mozci import config, data
from mozci.errors import (
    ChildPushNotFound,
    MissingDataError,
    ParentPushNotFound,
    PushNotFound,
)
from mozci.task import (
    GroupResult,
    GroupSummary,
    LabelSummary,
    RunnableSummary,
    Status,
    Task,
    TestTask,
    get_configuration_from_label,
)
from mozci.util.hgmo import HGMO
from mozci.util.memoize import memoize, memoized_property

BASE_INDEX = "gecko.v2.{branch}.revision.{rev}"

MAX_DEPTH = config.get("maxdepth", 20)
"""The maximum number of parents or children to look for previous/next task runs,
when the task did not run on the currently considered push.
"""

FAILURE_CLASSES = ("not classified", "fixed by commit")


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
            self._revs = None
            revs = [revs]
        else:
            self._revs = revs

        self.branch = branch
        self._hgmo = HGMO.create(revs[0], branch=self.branch)

        self._id = None
        self._date = None

        # Need to use full hash in the index.
        if len(revs[0]) == 40:
            self.rev = revs[0]
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

    @memoized_property
    def bugs(self):
        """The bugs associated with the commits of this push.

        Returns:
            set: A set of bug IDs.
        """
        return self._hgmo.bugs

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

    def create_push(self, push_id):
        result = self._hgmo.json_pushes(push_id_start=push_id - 1, push_id_end=push_id)
        if str(push_id) not in result:
            raise PushNotFound(
                f"push id {push_id} does not exist", rev=self.rev, branch=self.branch
            )

        result = result[str(push_id)]
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
                hgmo = HGMO.create(parent_rev, branch=branch)
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
        tasks = config.cache.get(f"{self.push_uuid}/tasks")
        if tasks is not None:
            return tasks

        logger.debug(f"Retrieving all tasks and groups which run on {self.rev}...")

        logger.debug(f"Gathering data about tasks that run on {self.rev}...")

        # Gather data about tasks that ran on a given push.
        try:
            # TODO: Skip tasks with `retry` as result
            tasks = data.handler.get("push_tasks", branch=self.branch, rev=self.rev)
        except MissingDataError:
            return []

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

        logger.debug(f"Gathering test groups for {self.rev}...")

        # Gather information from the unittest table. We allow missing data for this table because
        # ActiveData and Treeherder only hold very recent data in it, but we have fallbacks on Taskcluster
        # artifacts.
        try:
            groups = data.handler.get(
                "push_test_groups", branch=self.branch, rev=self.rev
            )
            for task in tasks:
                results = groups.get(task["id"])
                if results is not None:
                    task["_results"] = [
                        GroupResult(group=group, ok=ok) for group, ok in results.items()
                    ]
        except MissingDataError:
            pass

        tasks = [Task.create(**task) for task in tasks]

        logger.debug(
            f"Gathering test groups which were missing from the API for {self.rev}..."
        )

        # Gather group data which could have been missing in ActiveData or Treeherder.
        concurrent.futures.wait(
            [
                Push.THREAD_POOL_EXECUTOR.submit(lambda task: task.groups, task)
                for task in tasks
                if isinstance(task, TestTask)
            ],
            return_when=concurrent.futures.FIRST_EXCEPTION,
        )

        logger.debug(f"Retrieved all tasks and groups which run on {self.rev}.")

        # Now we can cache the results.
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
        groups = defaultdict(list)

        for task in self.tasks:
            if not isinstance(task, TestTask):
                continue

            for group in task.groups:
                groups[group].append(task)

        return {group: GroupSummary(group, tasks) for group, tasks in groups.items()}

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
            if task.tags.get("tests_grouped") == "1":
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

    def _is_classified_as_cause(self, first_appareance_push, classifications):
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
            try:
                fix_hgmo = HGMO.create(classification_note, branch=self.branch)
                if len(fix_hgmo.backouts) == 0:
                    continue
            except PushNotFound:
                logger.warning(
                    f"Classification note ({classification_note}) references a revision which does not exist on push {first_appareance_push.rev}"
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
                    HGMO.create(backedout, branch=self.branch).pushid
                    <= first_appareance_push.id
                    for backedout in backedouts
                ):
                    other_fixes.add(backout[:12])

            # If the backout push contains a bustage fix of another push, then we could
            # consider it as a regression of another push.
            if len(fix_hgmo.bugs_without_backouts) > 0:
                other_parent = first_appareance_push
                for i in range(MAX_DEPTH):
                    if other_parent != self:
                        for bug in other_parent.bugs:
                            if bug in fix_hgmo.bugs_without_backouts:
                                other_fixes.add(
                                    fix_hgmo.bugs_without_backouts[bug][:12]
                                )

                    other_parent = other_parent.parent

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

            try:
                other = other.child
            except ChildPushNotFound:
                break

            if max_depth is not None and i == max_depth:
                break

    def _iterate_failures(
        self, runnable_type: str, max_depth: Optional[int] = None
    ) -> Iterator[Tuple["Push", Dict[str, Tuple[float, RunnableSummary]]]]:
        ever_passing_runnables = set()
        passing_runnables = set()
        candidate_regressions = {}

        first_appareance = {}

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

                if name not in first_appareance:
                    first_appareance[name] = other

                is_classified_as_cause = self._is_classified_as_cause(
                    first_appareance[name], summary.classifications
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

            yield other, adjusted_candidate_regressions
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

        for other, candidate_regressions in self._iterate_failures(runnable_type):
            # Break early if we reached the backout of this push, since any failure
            # after that won't be blamed on this push.
            if self.branch != "try" and (
                self.backedoutby in other.child.revs
                or self.bustage_fixed_by in other.child.revs
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
                    other.child, f"{runnable_type}_summaries"
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
            if fix_same_bugs(self, other)
        )
        if len(possible_bustage_fixes) == 0:
            return None

        def find(runnable_type: str) -> Optional[str]:
            for other, candidate_regressions in self._iterate_failures(
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
    def get_regressions(self, runnable_type: str) -> Dict[str, int]:
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
        if self.branch != "try" and not self.backedout and not self.bustage_fixed_by:
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
                i = 0
                while count >= 0 and i < MAX_DEPTH:
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

                    other = other.parent
                    if not found_in_parent:
                        count += 1
                    i += 1

            # Given that our "bustage fix" detection is a heuristic which might fail, we
            # penalize regressions for pushes which weren't backed-out by doubling their count
            # (basically, we consider the push to be further away from the failure, which makes
            # it more likely to fall outside of MAX_DEPTH).
            if self.branch != "try" and not self.backedout:
                count *= 2

            # Also penalize cases where the status was intermittent.
            if failure_summary.is_intermittent:
                count *= 2

            if not prior_regression and count <= MAX_DEPTH:
                regressions[name] = int(count) if count > 0 else 0

        return regressions

    def get_possible_regressions(self, runnable_type):
        """The set of all runnables that may have been regressed by this push.

        A possible regression is a candidate_regression that didn't run on one or
        more parent pushes.

        Returns:
            set: Set of runnables (str).
        """
        return set(
            name
            for name, count in self.get_regressions(runnable_type).items()
            if count > 0
        )

    def get_likely_regressions(self, runnable_type):
        """The set of all runnables that were likely regressed by this push.

        A likely regression is a candidate_regression that both ran and passed
        on the immediate parent push. It still isn't a sure thing as the task
        could be intermittent.

        Returns:
            set: Set of runnables (str).
        """
        return set(
            name
            for name, count in self.get_regressions(runnable_type).items()
            if count == 0
        )

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

    def __repr__(self):
        return f"{super(Push, self).__repr__()} rev='{self.rev}'"


def make_push_objects(**kwargs):
    try:
        pushes_data = data.handler.get("push_revisions", **kwargs)
    except MissingDataError:
        return []

    pushes = []

    for push_data in pushes_data:
        cur = Push(push_data["revs"])

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
        from_date (str): String representing an acceptable date value in ActiveData.
        to_date (str): String representing an acceptable date value in ActiveData.
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

    summaries = globals()[func](pushes, branch)

    # Sort by either the label (LabelSummary) or name (GroupSummary).
    summaries.sort(key=lambda x: (getattr(x, "label", "name")))
    return summaries


def __make_label_summary_objects(pushes, branch):
    """Generates a list of LabelSummary objects from a list of pushes.

    Args:
        pushes (list): List of Push objects.

    Returns:
        list: List of LabelSummary objects.
    """
    # Flatten list of tasks for every push to a 1-dimensional list.
    tasks = sorted(
        [task for push in pushes for task in push.tasks], key=lambda x: x.label
    )

    # Make a mapping keyed by task.label containing list of Task objects.
    tasks_by_config = defaultdict(lambda: defaultdict(list))
    for task in tasks:
        tasks_by_config[task.configuration][task.label]["tasks"].append(task)

    return [
        LabelSummary(label, tasks)
        for config in tasks_by_config.keys()
        for label, tasks in tasks_by_config[config].items()
    ]


def __make_group_summary_objects(pushes, branch):
    """Generates a list of GroupSummary objects from a list of pushes.

    Args:
        pushes (list): List of Push objects.

    Returns:
        list: List of GroupSummary objects.
    """
    import adr

    # Obtain all the task.id values contained in the pushes. It will be used in
    # the `where` query against ActiveData.
    results = []
    revs = [p.rev for p in pushes]
    # if we have too many revisions, ActiveData returns an error
    for i in range(0, len(revs), 30):
        for revs_chunk in revs[i : i + 30]:
            try:
                results += adr.query.run_query(
                    "group_durations", Namespace(push_ids=revs_chunk, branch=branch)
                )["data"]
            except adr.MissingDataError:
                pass

    # Sort by the result.group attribute.
    results = sorted(results, key=lambda x: x[1])

    tasks_by_config = {}
    task_id_to_task = {t.id: t for push in pushes for t in push.tasks}

    for task_id, result_group, result_duration in results:
        # TODO: remove this when https://github.com/mozilla/mozci/issues/297 is fixed
        if task_id not in task_id_to_task:
            continue

        # tasks that had exception or failed by timeout have no duration for a group
        if result_duration is None:
            continue

        task = task_id_to_task[task_id]
        if task.configuration not in tasks_by_config:
            # Dictionary to hold the mapping keyed by result.group mapped to list of
            # task.id and list of and result.duration.
            tasks_by_config[task.configuration] = defaultdict(lambda: defaultdict(list))

        # Build the mapping of group to the group durations and TestTask objects.
        tasks_by_config[task.configuration][result_group]["tasks"].append(task)
        tasks_by_config[task.configuration][result_group]["durations"].append(
            result_duration
        )

    return [
        GroupSummary(key, value["tasks"], value["durations"])
        for config in tasks_by_config.keys()
        for key, value in tasks_by_config[config].items()
    ]
