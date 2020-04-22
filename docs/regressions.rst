Regressions
===========

One of the primary uses of ``mozci`` is to help detect which tasks and/or tests (if any) a push has
regressed. Since we do not run all tasks on every push and because of other factors like
intermittents, this problem is more difficult than it first appears. In fact ``mozci`` can make very
few guarantees and so has to rely on probabilistic guesses.

This page will help explain how regressions are calculated by introducing concepts one at a time.

Definitions
-----------

There are currently two different vectors of regression that ``mozci`` can check for: *label* and
*group*.

* **label** - is a task label (e.g ``test-linux1804-64/debug-mochitest-e10s-1``)
* **group** - is a grouping of tests, typically a manifest (e.g ``dom/indexedDB/test/mochitest.ini``).
* **runnable** is the unique label identifying a set of tasks, or the unique group identifying a set of tests.
* **classification** - an annotation that Sheriffs apply to tasks manually. It is also known as "starring" because it puts a little asterisk next to the task in Treeherder.


Runnable Summary
----------------

Thanks to retriggers, each runnable can run multiple times on the same push. The collection of
labels or groups of the same type that ran on a push is called a *runnable summary*. For instance,
if all the runnables on a push passed, then the status of the runnable summary is also PASS.
Likewise if they all failed. If at least one instance of a runnable passes, and at least one
instance of a runnable failed, then the runnable summary is said to be intermittent.

The :class:`~mozci.task.GroupSummary` class implements this logic for groups and the
:class:`~mozci.task.LabelSummary` implements the logic for labels. Both classes inherit from the
:class:`~mozci.task.RunnableSummary` abstract base class.

All instances of :class:`~mozci.task.RunnableSummary` have an overall status and an overall classification.


Candidate Regression
--------------------

A candidate regression is a runnable which meets the following criteria:

    * At least one instance of this runnable failed on target push (i.e, the status of the runnable
      summary is either FAIL or INTERMITTENT)
    * The overall classification of the runnable summary is either ``unclassified``, or ``fixed by
      commit``.  This means runnables classified as a known intermittent are not candidate
      regressions.
    * For runnables classified ``fixed by commit``, the referenced backout backs out the target push
      and not some other one.

    OR

    * The runnable ran on a child push (up to :data:`~mozci.push.MAX_DEPTH` pushes away), and
      is classified ``fixed by commit``.
    * The classification references a backout that backs out the target push.


Candidate regressions are the set of all runnables that could possibly be a regression of this push.
This *does not* mean that they are regressions. Just that they could be.

The set of candidate regressions can be obtained by calling
:meth:`Push.get_candidate_regressions() <mozci.push.Push.get_candidate_regressions()>`.


Regression
----------

A *regression* is a candidate regression that additionally satisfies the following criteria:

    * The candidate regression is not marked as a regression of any parent pushes up
      to :data:`~mozci.push.MAX_DEPTH` pushes away.
    * The condition ``total_distance <= MAX_DEPTH`` is satisfied. This condition is explained in more detail below.

.. note:: Distance Calculation

    The ``total_distance`` is the number of parent pushes we need to go back to see the runnable plus
    the number of child pushes we need to go forward to see the runnable. A ``total_distance`` of 0
    means the runnable ran on the actual target push.

    The ``total_distance`` can be modified in certain scenarios:

    1. The push was not backed out => total distance is doubled.
    2. The runnable was intermittent => total distance is doubled.
    3. The runnable was marked as ``fixed by commit`` referencing a backout that backs out the
       target push => total distance is 0 even if it didn't run on the target push.

    These modifications help us deal with (un)certainty in special easy to detect circumstances. The
    first two make a candidate regression less likely to be treated as a regression, while the third
    guarantees it.

Regressions can be obtained by calling :meth:`Push.get_regressions()
<mozci.push.Push.get_regressions()>`.


Likely Regressions
------------------

A *likely regression* is a regression whose associated ``total_distance`` is 0.  In other words, we
are as sure as we can be that these are regressions.

Likely regressions can be obtained by calling :meth:`Push.get_likely_regressions()
<mozci.push.Push.get_likely_regressions()>`.


Possible Regressions
--------------------

A *possible regression* is a regression whose associated ``total_distance`` is above 0. In other
words, it could be a regression, or it could be regressed from one of its parent pushes. We aren't
sure. The higher the ``total_distance`` the less sure we are.

Possible regressions can be obtained by calling :meth:`Push.get_possible_regressions()
<mozci.push.Push.get_possible_regressions()>`.

.. note::

    Candidate regressions that aren't also possible regressions could still technically be real
    regressions. Mozci just thinks the likelihood is so low they aren't worth counting.
