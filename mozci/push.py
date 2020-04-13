# -*- coding: utf-8 -*-
import concurrent.futures
import math
from argparse import Namespace
from collections import defaultdict
from functools import lru_cache

from adr.errors import MissingDataError
from adr.query import run_query
from adr.util.memoize import memoized_property
from loguru import logger

from mozci.errors import ChildPushNotFound, ParentPushNotFound, PushNotFound
from mozci.task import GroupResult, GroupSummary, LabelSummary, Status, Task, TestTask
from mozci.util.hgmo import HGMO

BASE_INDEX = "gecko.v2.{branch}.revision.{rev}"

MAX_DEPTH = 14
"""The maximum number of parents or children to look for previous/next task runs,
when the task did not run on the currently considered push.
"""


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
            self.rev = self._hgmo["node"]

        self.index = BASE_INDEX.format(branch=self.branch, rev=self.rev)

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
        return self._hgmo.get("backedoutby") or None

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
        return set(
            bug["no"]
            for changeset in self._hgmo.changesets
            for bug in changeset["bugs"]
        )

    @property
    def date(self):
        """The push date.

        Returns:
            int: The push date in ms since the epoch.
        """
        if self._date:
            return self._date

        self._date = self._hgmo["pushdate"][0]
        return self._date

    @property
    def id(self):
        """The push id.

        Returns:
            int: The push id.
        """
        if self._id:
            return self._id

        self._id = self._hgmo["pushid"]
        return self._id

    def create_push(self, push_id):
        result = self._hgmo.json_pushes(push_id_start=push_id - 1, push_id_end=push_id)
        if str(push_id) not in result:
            raise PushNotFound(
                f"push id {push_id} does not exist", rev=self.rev, branch=self.branch
            )

        result = result[str(push_id)]
        push = Push(result["changesets"][::-1])
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
                head = hgmo.changesets[0]["pushhead"]
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
                    f"child push does not exist", rev=self.rev, branch=self.branch
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

        args = Namespace(rev=self.rev, branch=self.branch)
        tasks = defaultdict(dict)
        retries = defaultdict(int)

        list_keys = (
            "_result_ok",
            "_result_group",
        )

        def add(result):
            if "header" in result:
                result["data"] = [
                    {
                        field: value
                        for field, value in zip(result["header"], entry)
                        if value is not None
                    }
                    for entry in result["data"]
                ]

            for task in result["data"]:
                if "id" not in task:
                    logger.trace(f"Skipping {task} because of missing id.")
                    continue

                task_id = task["id"]

                # If a task is re-run, use the data from the last run.
                if "retry_id" in task:
                    if task["retry_id"] < retries[task_id]:
                        logger.trace(
                            f"Skipping {task} because there is a newer run of it."
                        )
                        continue

                    retries[task_id] = task["retry_id"]

                    # We don't need to store the retry ID.
                    del task["retry_id"]

                cur_task = tasks[task_id]

                for key, val in task.items():
                    if key in list_keys:
                        if key not in cur_task:
                            cur_task[key] = []

                        cur_task[key].append(val)
                    else:
                        cur_task[key] = val

        # Gather information from the treeherder table.
        try:
            add(run_query("push_tasks_from_treeherder", args))
        except MissingDataError:
            pass

        # Gather information from the unittest table. We allow missing data for this table because
        # ActiveData only holds very recent data in it, but we have fallbacks on Taskcluster
        # artifacts.
        # TODO: We have fallbacks for groups and results, but not for kind.
        try:
            add(run_query("push_tasks_results_from_unittest", args))
        except MissingDataError:
            pass

        try:
            add(run_query("push_tasks_groups_from_unittest", args))
        except MissingDataError:
            pass

        # If we are missing one of these keys, discard the task.
        required_keys = (
            "id",
            "label",
        )

        # Normalize and validate.
        normalized_tasks = []
        for task in tasks.values():
            missing = [k for k in required_keys if k not in task]
            taskstr = task.get("label", task["id"])

            if missing:
                logger.trace(
                    f"Skipping task '{taskstr}' because it is missing "
                    f"the following attributes: {', '.join(missing)}"
                )
                continue

            if task.get("tags"):
                task["tags"] = {t["name"]: t["value"] for t in task["tags"]}

            if task.get("classification_note"):
                if isinstance(task["classification_note"], list):
                    task["classification_note"] = task["classification_note"][-1]

            if task.get("_groups"):
                if isinstance(task["_groups"], str):
                    task["_groups"] = [task["_groups"]]

            if task.get("_result_ok"):
                oks = task.pop("_result_ok")

                if task.get("_result_group"):
                    groups = task.pop("_result_group")

                    task["_results"] = [
                        GroupResult(group=group, ok=ok)
                        for group, ok in zip(groups, oks)
                    ]

            normalized_tasks.append(task)

        return [Task.create(**task) for task in normalized_tasks]

    @property
    def task_labels(self):
        """The set of task labels that ran on this push.

        Returns:
            set: A set of task labels (str).
        """
        return set(t.label for t in self.tasks)

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
    def group_summaries(self):
        """All group summaries combining retriggers.

        Returns:
            dict: A dictionary of the form {<group>: [<GroupSummary>]}.
        """
        groups = defaultdict(list)

        future_to_task = {
            Push.THREAD_POOL_EXECUTOR.submit(lambda task: task.groups, task): task
            for task in self.tasks
            if isinstance(task, TestTask)
        }

        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            for group in future.result():
                groups[group].append(task)

        groups = {group: GroupSummary(group, tasks) for group, tasks in groups.items()}
        return groups

    @memoized_property
    def label_summaries(self):
        """All label summaries combining retriggers.

        Returns:
            dict: A dictionary of the form {<label>: [<LabelSummary>]}.
        """
        labels = defaultdict(list)
        for task in self.tasks:
            labels[task.label].append(task)
        labels = {label: LabelSummary(label, tasks) for label, tasks in labels.items()}
        return labels

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

    def _is_classified_as_cause(self, other, classifications):
        """Checks a 'fixed by commit' classification to figure out what push it references.

        Returns:
            bool or None: True, if the classification references this push.
                          False, if the classification references another push.
                          None, if it is not clear what the classification references.
        """
        fixed_by_commit_classification_notes = [
            n[:12]
            for c, n in classifications
            if c == "fixed by commit"
            if n is not None
        ]

        if len(fixed_by_commit_classification_notes) == 0:
            return None

        # If the failure was classified as fixed by commit, and the fixing commit
        # is a backout of the current push, it is definitely a regression of the
        # current push.
        if (
            self.backedout
            and self.backedoutby[:12] in fixed_by_commit_classification_notes
        ):
            return True

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
                    f"Classification note ({classification_note}) references a revision which does not exist on push {other.rev}"
                )
                return None

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
                    return True

            # Otherwise, as long as the commit which was backed-out was landed **before**
            # the appearance of this failure, we can be sure it was its cause and so
            # the current push is not at fault.
            for backout, backedouts in fix_hgmo.backouts.items():
                if backout[:12] != classification_note[:12]:
                    continue

                if any(
                    HGMO.create(backedout, branch=self.branch).pushid <= other.id
                    for backedout in backedouts
                ):
                    return False

            # Otherwise, if the backout push also contains the backout commit of this push,
            # we can consider it as a regression of this push.
            # if self.backedoutby:
            if self.backedout:
                for backout in fix_hgmo.backouts:
                    if backout[:12] == self.backedoutby[:12]:
                        return True

        return None

    def _iterate_children(self):
        other = self
        for _ in range(MAX_DEPTH + 1):
            yield other

            try:
                other = other.child
            except ChildPushNotFound:
                break

    def _iterate_failures(self, runnable_type):
        failclass = ("not classified", "fixed by commit")

        passing_runnables = set()
        candidate_regressions = {}

        count = 0
        for other in self._iterate_children():
            for name, summary in getattr(other, f"{runnable_type}_summaries").items():
                if name in passing_runnables:
                    # It passed in one of the pushes between the current and its
                    # children, so it is definitely not a regression in the current.
                    continue

                if summary.status == Status.PASS:
                    passing_runnables.add(name)
                    continue

                if all(c not in failclass for c, n in summary.classifications):
                    passing_runnables.add(name)
                    continue

                is_classified_as_cause = self._is_classified_as_cause(
                    other, summary.classifications
                )
                if is_classified_as_cause is True:
                    candidate_regressions[name] = (-math.inf, summary.status)
                elif is_classified_as_cause is False:
                    passing_runnables.add(name)
                    continue

                if name in candidate_regressions:
                    # It failed in one of the pushes between the current and its
                    # children, we don't want to increase the previous distance.
                    continue

                candidate_regressions[name] = (count, summary.status)

            yield other, candidate_regressions

            other = other.child
            count += 1

    def get_candidate_regressions(self, runnable_type):
        """Retrieve the set of "runnables" that are regression candidates for this push.

        A "runnable" can be any group of tests, e.g. a label, a manifest across platforms,
        a manifest on a given platform.

        A candidate regression is any runnable for which at least one
        associated task failed (therefore including intermittents), and which
        is either not classified or fixed by commit.

        Returns:
            set: Set of runnable names (str).
        """
        for other, candidate_regressions in self._iterate_failures(runnable_type):
            # Break early if we reached the backout of this push, since any failure
            # after that won't be blamed on this push.
            if (
                self.backedoutby in other.child.revs
                or self.bustage_fixed_by in other.child.revs
            ):
                break

        return candidate_regressions

    @memoized_property
    def bustage_fixed_by(self):
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
            other for other in self._iterate_children() if fix_same_bugs(self, other)
        )
        if len(possible_bustage_fixes) == 0:
            return None

        for other, candidate_regressions in self._iterate_failures("label"):
            if other == self or other not in possible_bustage_fixes:
                continue

            if any(
                name in other.label_summaries
                and other.label_summaries[name].status == Status.PASS
                for name in candidate_regressions
            ):
                return other.rev

            possible_bustage_fixes.remove(other)
            if len(possible_bustage_fixes) == 0:
                break

        return None

    @lru_cache(maxsize=None)
    def get_regressions(self, runnable_type):
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
        regressions = {}

        # If the push was not backed-out and was not "bustage fixed", it can't
        # have caused regressions.
        if not self.backedout and not self.bustage_fixed_by:
            return regressions

        for name, (count, status) in self.get_candidate_regressions(
            runnable_type
        ).items():
            other = self.parent
            prior_regression = False

            while count >= 0 and count < MAX_DEPTH:
                runnable_summaries = getattr(other, f"{runnable_type}_summaries")

                if name in runnable_summaries:
                    if runnable_summaries[name].status != Status.PASS:
                        prior_regression = True
                    break

                other = other.parent
                count += 1

            # Given that our "bustage fix" detection is a heuristic which might fail, we
            # penalize regressions for pushes which weren't backed-out by doubling their count
            # (basically, we consider the push to be further away from the failure, which makes
            # it more likely to fall outside of MAX_DEPTH).
            if not self.backedout:
                count *= 2

            # Also penalize cases where the status was intermittent.
            if status == Status.INTERMITTENT:
                count *= 2

            if not prior_regression and count <= MAX_DEPTH:
                regressions[name] = count if count > 0 else 0

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

    @lru_cache(maxsize=None)
    def get_shadow_scheduler_tasks(self, name):
        """Returns all tasks the given shadow scheduler would have scheduled,
        or None if the given scheduler didn't run.

        Args:
            name (str): The name of the shadow scheduler to query.

        Returns:
            set: All task labels that would have been scheduled.
        """
        index = self.index + ".source.shadow-scheduler-{}".format(name)
        task = Task.create(index=index)
        labels = task.get_artifact("public/shadow-scheduler/optimized_tasks.list")
        return set(labels.splitlines())

    def generate_all_shadow_scheduler_tasks(self):
        """Generates all tasks from all of the shadow schedulers that ran on the push.

        Yields:
            tuple: Of the form (<name>, [<label>]) where the first value is the
            name of the shadow scheduler and the second is the set of tasks it
            would have scheduled.
        """
        names = [
            label.split("shadow-scheduler-")[1]
            for label in self.scheduled_task_labels
            if "shadow-scheduler" in label
        ]
        for name in sorted(names):
            yield name, self.get_shadow_scheduler_tasks(name)

    def __repr__(self):
        return f"{super(Push, self).__repr__()} rev='{self.rev}'"


def make_push_objects(**kwargs):
    result = run_query("push_revisions", Namespace(**kwargs))

    pushes = []

    for pushid, date, revs, parents in result["data"]:
        topmost = list(set(revs) - set(parents))[0]

        cur = Push([topmost] + [r for r in revs if r != topmost])

        # avoids the need to query hgmo to find this info
        cur._id = pushid
        cur._date = date

        pushes.append(cur)

    pushes.sort(key=lambda p: p._id)

    for i, cur in enumerate(pushes):
        if i != 0:
            cur._parent = pushes[i - 1]

        if i != len(pushes) - 1:
            cur._child = pushes[i + 1]

    return pushes
