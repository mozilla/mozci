from argparse import Namespace
from collections import defaultdict

import requests
from adr.errors import MissingDataError
from adr.query import run_query
from adr.util.memoize import memoize, memoized_property
from loguru import logger

from mozci.task import (
    GroupSummary,
    LabelSummary,
    Status,
    Task,
    TestTask,
    GroupResult,
)
from mozci.util.taskcluster import find_task_id

HGMO_JSON_URL = "https://hg.mozilla.org/integration/{branch}/rev/{rev}?style=json"
HGMO_JSON_PUSHES_URL = "https://hg.mozilla.org/integration/{branch}/json-pushes?version=2&startID={push_id_start}&endID={push_id_end}"  # noqa

BASE_INDEX = "gecko.v2.{branch}.revision.{rev}"

# The maximum number of parents or children to look for previous/next task runs,
# when the task did not run on the currently considered push.
MAX_DEPTH = 14


class Push:

    def __init__(self, revs, branch='autoland'):
        """A representation of a single push.

        Args:
            revs (list): List of revisions of commits in the push (top-most is the first element).
            branch (str): Branch to look on (default: autoland).
        """
        if isinstance(revs, str):
            revs = [revs]

        self.revs = revs
        self.branch = branch
        self.index = BASE_INDEX.format(branch=self.branch, rev=self.rev)
        self._id = None
        self._date = None

    @property
    def rev(self):
        return self.revs[0]

    @memoized_property
    def backedoutby(self):
        """The revision of the commit which backs out this one or None.

        Returns:
            str or None: The commit revision which backs this push out (or None).
        """
        return self._hgmo.get('backedoutby') or None

    @property
    def backedout(self):
        """Whether the push was backed out or not.

        Returns:
            bool: True if this push was backed out.
        """
        return bool(self.backedoutby)

    @property
    def date(self):
        """The push date.

        Returns:
            int: The push date in ms since the epoch.
        """
        if self._date:
            return self._date

        self._date = self._hgmo['pushdate'][0]
        return self._date

    @property
    def id(self):
        """The push id.

        Returns:
            int: The push id.
        """
        if self._id:
            return self._id

        self._id = self._hgmo['pushid']
        return self._id

    def create_push(self, push_id):
        url = HGMO_JSON_PUSHES_URL.format(
            branch=self.branch,
            push_id_start=push_id - 1,
            push_id_end=push_id
        )

        r = requests.get(url)
        r.raise_for_status()
        result = r.json()["pushes"][str(push_id)]

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
        """
        return self.create_push(self.id - 1)

    @memoized_property
    def child(self):
        """Returns the child push of this push.

        Returns:
            Push: A `Push` instance representing the child push.
        """
        return self.create_push(self.id + 1)

    @memoized_property
    def decision_task(self):
        """A representation of the decision task.

        Returns:
            Task: A `Task` instance representing the decision task.
        """
        index = self.index + ".taskgraph.decision"
        task_id = find_task_id(index)
        return Task(id=task_id)

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
            "_result_ok", "_result_group",
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
                if 'id' not in task:
                    logger.trace(f"Skipping {task} because of missing id.")
                    continue

                task_id = task['id']

                # If a task is re-run, use the data from the last run.
                if 'retry_id' in task:
                    if task['retry_id'] < retries[task_id]:
                        logger.trace(f"Skipping {task} because there is a newer run of it.")
                        continue

                    retries[task_id] = task['retry_id']

                    # We don't need to store the retry ID.
                    del task['retry_id']

                cur_task = tasks[task_id]

                for key, val in task.items():
                    if key in list_keys:
                        if key not in cur_task:
                            cur_task[key] = []

                        cur_task[key].append(val)
                    else:
                        cur_task[key] = val

        # Gather information from the treeherder table.
        add(run_query('push_tasks_from_treeherder', args))

        # Gather information from the unittest table. We allow missing data for this table because
        # ActiveData only holds very recent data in it, but we have fallbacks on Taskcluster
        # artifacts.
        # TODO: We have fallbacks for groups and results, but not for kind.
        try:
            add(run_query('push_tasks_results_from_unittest', args))
        except MissingDataError:
            pass

        try:
            add(run_query('push_tasks_groups_from_unittest', args))
        except MissingDataError:
            pass

        # If we are missing one of these keys, discard the task.
        required_keys = (
            'id',
            'label',
        )

        # Normalize and validate.
        normalized_tasks = []
        for task in tasks.values():
            missing = [k for k in required_keys if k not in task]
            taskstr = task.get('label', task['id'])

            if missing:
                logger.trace(f"Skipping task '{taskstr}' because it is missing "
                             f"the following attributes: {', '.join(missing)}")
                continue

            if task.get('tags'):
                task['tags'] = {t['name']: t['value'] for t in task['tags']}

            if task.get('_groups'):
                if isinstance(task['_groups'], str):
                    task['_groups'] = [task['_groups']]

            if task.get('_result_ok'):
                oks = task.pop('_result_ok')

                if task.get('_result_group'):
                    groups = task.pop('_result_group')

                    task['_results'] = [
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
        return set(self.decision_task.get_artifact('public/target-tasks.json'))

    @memoized_property
    def scheduled_task_labels(self):
        """The set of task labels that were originally scheduled to run on this push.

        This excludes backfills and Add New Jobs.

        Returns:
            set: A set of task labels (str).
        """
        tasks = self.decision_task.get_artifact('public/task-graph.json').values()
        return {t['label'] for t in tasks}

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
        for task in self.tasks:
            if not isinstance(task, TestTask):
                continue

            for group in task.groups:
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

    @memoize
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
        failclass = ('not classified', 'fixed by commit')

        passing_runnables = set()
        candidate_regressions = {}

        count = 0
        other = self
        while count < MAX_DEPTH + 1:
            for name, summary in getattr(other, f"{runnable_type}_summaries").items():
                if name in passing_runnables:
                    # It passed in one of the pushes between the current and its
                    # children, so it is definitely not a regression in the current.
                    continue

                if summary.status == Status.PASS:
                    passing_runnables.add(name)
                    continue

                if all(c not in failclass for c in summary.classifications):
                    passing_runnables.add(name)
                    continue

                if name in candidate_regressions:
                    # It failed in one of the pushes between the current and its
                    # children, we don't want to increase the previous distance.
                    continue

                candidate_regressions[name] = count

            other = other.child
            count += 1

        return candidate_regressions

    @memoize
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

        for name, child_count in self.get_candidate_regressions(runnable_type).items():
            count = 0
            other = self.parent
            prior_regression = False

            while count < MAX_DEPTH:
                runnable_summaries = getattr(other, f"{runnable_type}_summaries")

                if name in runnable_summaries:
                    if runnable_summaries[name].status != Status.PASS:
                        prior_regression = True
                    break

                other = other.parent
                count += 1

            total_count = count + child_count

            # When the push was not backed-out, it's less likely to be the cause of a failure.
            # So, we penalize it by doubling its count (basically, we consider the push to be
            # further away from the failure, which makes it more likely to fall outside of
            # MAX_DEPTH).
            # We can't fully exclude pushes which were not backed-out because of bustage fixes.
            if not self.backedout:
                total_count *= 2

            if not prior_regression and total_count <= MAX_DEPTH:
                regressions[name] = total_count

        return regressions

    def get_possible_regressions(self, runnable_type):
        """The set of all runnables that may have been regressed by this push.

        A possible regression is a candidate_regression that didn't run on one or
        more parent pushes.

        Returns:
            set: Set of runnables (str).
        """
        return set(name for name, count in self.get_regressions(runnable_type).items() if count > 0)

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
    def get_shadow_scheduler_tasks(self, name):
        """Returns all tasks the given shadow scheduler would have scheduled,
        or None if the given scheduler didn't run.

        Args:
            name (str): The name of the shadow scheduler to query.

        Returns:
            list: All task labels that would have been scheduled.
        """
        index = self.index + ".source.shadow-scheduler-{}".format(name)
        task = Task(id=find_task_id(index))
        labels = task.get_artifact('public/shadow-scheduler/optimized_tasks.list')
        return set(labels.splitlines())

    @memoized_property
    def _hgmo(self):
        """A JSON dict obtained from hg.mozilla.org.

        Returns:
            dict: Information regarding this push.
        """
        url = HGMO_JSON_URL.format(branch=self.branch, rev=self.rev)
        r = requests.get(url)
        r.raise_for_status()
        return r.json()

    def __repr__(self):
        return f"{super(Push, self).__repr__()} rev='{self.rev}'"


def make_push_objects(**kwargs):
    data = run_query("push_revisions", Namespace(**kwargs))["data"]

    pushes = []

    for row in data:
        pushid, date, revs, parents = row['pushid'], row['date'], row['revs'], row['parents']
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
