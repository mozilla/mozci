# -*- coding: utf-8 -*-
import requests

from mozci.push import MAX_DEPTH
from mozci.task import Task
from mozci.util.hgmo import HGMO


def test_succeeded_in_parent_didnt_run_in_current_failed_in_child_failed_in_grandchild(
    create_pushes,
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, and failed in its following pushes.
    """
    p = create_pushes(7)
    i = 3  # the index of the push we are mainly interested in

    # setup
    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].backedoutby = p[i + 3].rev

    assert p[i - 2].get_regressions("label") == {}
    assert p[i - 1].get_regressions("label") == {}
    assert p[i].get_regressions("label") == {"test-prova": 1}
    assert p[i + 1].get_regressions("label") == {"test-prova": 1}
    assert p[i + 2].get_regressions("label") == {}


def test_succeeded_in_parent_didnt_run_in_current_failed_in_child_succeeded_in_grandchild(
    create_pushes,
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, failed in a following push, and succeeded in a second
    following push.
    """
    p = create_pushes(7)
    i = 3  # the index of the push we are mainly interested in

    # setup
    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [Task.create(id="1", label="test-prova", result="success")]

    assert p[i - 2].get_regressions("label") == {}
    assert p[i - 1].get_regressions("label") == {}
    assert p[i].get_regressions("label") == {"test-prova": 1}
    assert p[i + 1].get_regressions("label") == {"test-prova": 1}
    assert p[i + 2].get_regressions("label") == {}


def test_succeeded_in_parent_didnt_run_in_current_passed_in_child_failed_in_grandchild(
    create_pushes,
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, succeeded in a following push, and failed in a second
    following push.
    """
    p = create_pushes(7)
    i = 3  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i + 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].backedoutby = p[i + 3].rev

    assert p[i - 2].get_regressions("label") == {}
    assert p[i - 1].get_regressions("label") == {}
    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {"test-prova": 0}


def test_succeeded_in_parent_succeeded_in_current_failed_in_child_failed_in_grandchild(
    create_pushes,
):
    """
    Tests the scenario where a task succeeded in a parent push, succeeded in the
    push of interest, failed in a following push, and failed in a second
    following push.
    """
    p = create_pushes(7)
    i = 3  # the index of the push we are mainly interested in

    p[i - 2].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].backedoutby = p[i + 3].rev

    assert p[i - 2].get_regressions("label") == {}
    assert p[i - 1].get_regressions("label") == {}
    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-prova": 0}
    assert p[i + 2].get_regressions("label") == {}


def test_succeeded_in_parent_failed_in_current_succeeded_in_child_succeeded_in_grandchild(
    create_pushes,
):
    """
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest, succeeded in a following push, and succeeded in a second
    following push.
    """
    p = create_pushes(7)
    i = 3  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i + 2].tasks = [Task.create(id="1", label="test-prova", result="success")]

    assert p[i - 2].get_regressions("label") == {}
    assert p[i - 1].get_regressions("label") == {}
    assert p[i].get_regressions("label") == {"test-prova": 0}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_on_backout(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in the push containing the backout of the push of interest.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = []
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 2}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_on_bustage_fix(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in the push containing the bustage fix of the push of interest.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [
        Task.create(id="1", label="test", result="success"),
        Task.create(id="1", label="test_for_detecting_bustage_fix", result="success"),
    ]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test_for_detecting_bustage_fix",
            result="testfailed",
            classification="not classified",
        ),
    ]
    p[i].bugs = {123}
    p[i + 1].tasks = []
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1", label="test", result="testfailed", classification="not classified",
        ),
        Task.create(id="1", label="test_for_detecting_bustage_fix", result="success",),
    ]
    p[i + 2].bugs = {123}

    assert p[i].get_regressions("label") == {"test_for_detecting_bustage_fix": 0}
    assert p[i + 1].get_regressions("label") == {"test": 2}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_on_multiple_backouts(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in the push containing the backout of the push of interest.
    The push containing the backout of the push of interest backs out multiple revisions.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = "myrev"
    p[i + 1].tasks = []
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2]._revs = [p[i + 1].rev, "myrev"]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 2}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_after_backout(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a push after the backout of the push of interest.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 1].rev
    p[i + 1].tasks = []
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {"test-failure": 2}


def test_failure_keeps_happening_on_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest and failed in the backout of the push of interest.
    """
    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = []
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_intermittent_on_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest and failed as intermittent in the backout of the push of interest.
    """
    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = []
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="intermittent",
        )
    ]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_not_on_push_keeps_happening_on_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a push after the push of interest, but kept failing
    on the backout of the push of interest.
    """
    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = []
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}


def test_failure_not_on_push_keeps_happening_after_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a push after the push of interest, but kept failing
    after the backout of the push of interest.
    """
    p = create_pushes(7)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = []
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = []
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 5].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {"test-failure": 2}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}
    assert p[i + 3].get_regressions("label") == {}


def test_succeeded_and_backedout(create_pushes):
    """
    Tests the scenario where a task succeeded in a push which was backed-out.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].backedoutby = p[i + 1].rev

    assert p[i].get_regressions("label") == {}


def test_failed_and_backedout(create_pushes):
    """
    Tests the scenario where a task failed in a push which was backed-out.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i].backedoutby = p[i + 1].rev

    assert p[i].get_regressions("label") == {"test-prova": 0}


def test_failed_and_bustage_fixed(create_pushes):
    """
    Tests the scenario where a task failed in a push which was linked to the same bug
    as a child push where the failure was not happening anymore.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova1", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-prova1",
            result="testfailed",
            classification="not classified",
        ),
        Task.create(id="1", label="test-prova2", result="success",),
    ]
    p[i].bugs = {123}
    p[i + 1].tasks = [Task.create(id="1", label="test-prova1", result="success")]
    p[i + 1].bugs = {123}

    assert p[i].get_regressions("label") == {"test-prova1": 0}


def test_failed_and_bustage_fixed_intermittently(create_pushes):
    """
    Tests the scenario where a task failed intermittently in a push which was linked
    to the same bug as a child push where the failure was not happening anymore.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].tasks = [
        Task.create(
            id="4",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        ),
        Task.create(id="5", label="test-prova", result="success",),
    ]
    p[i].bugs = {123}
    p[i + 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i + 1].bugs = {123}

    assert p[i].get_regressions("label") == {"test-prova": 0}


def test_failed_with_child_push_fixing_same_bug(create_pushes):
    """
    Tests the scenario where a task failed in a push which was linked to the same bug
    as a child push where the same task didn't run.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i].bugs = {123}
    p[i + 1].bugs = {123}

    assert p[i].get_regressions("label") == {}


def test_failed_with_child_push_still_failing_fixing_same_bug(create_pushes):
    """
    Tests the scenario where a task failed in a push which was linked to the same bug
    as a child push where the task kept failing.
    This test ensures a child push is not considered a bustage fix if there are no clear
    matching task failures/passes to justify it.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure", result="success"),
        Task.create(id="2", label="test-success", result="success",),
        Task.create(id="3", label="test-classified-intermittent", result="success",),
    ]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        ),
        Task.create(id="2", label="test-success", result="success",),
        Task.create(
            id="3",
            label="test-classified-intermittent",
            result="testfailed",
            classification="intermittent",
        ),
    ]
    p[i].bugs = {123}
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        ),
        Task.create(id="2", label="test-success", result="success",),
        Task.create(id="3", label="test-classified-intermittent", result="success",),
    ]
    p[i + 1].bugs = {123}

    assert p[i].get_regressions("label") == {}


def test_failed_and_not_backedout_nor_bustage_fixed(create_pushes):
    """
    Tests the scenario where a task failed in a push which was not backed-out nor
    bustage fixed.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}


def test_child_failed_and_bustage_fixed(create_pushes):
    """
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out but bustage fixed, and failed in a following push.
    """
    p = create_pushes(3 + (MAX_DEPTH // 4))
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].bugs = {123}
    p[len(p) - 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[len(p) - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[len(p) - 1].bugs = {123}

    assert p[i].get_regressions("label") == {"test-prova": 6}


def test_child_failed_and_not_backedout(create_pushes):
    """
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out, and failed in a following push.
    """
    p = create_pushes(3 + (MAX_DEPTH // 4))
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[len(p) - 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}


def test_far_child_failed_and_backedout(create_pushes):
    """
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out, and failed in a (far away) following push.
    """
    p = create_pushes(3 + (MAX_DEPTH // 2 + 1))
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[len(p) - 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}


def test_fixed_by_commit(monkeypatch, create_pushes):
    """
    Tests the scenario where two tasks succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to the back-outs.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"][:12] == p[i + 2].rev:
            return {p[i + 2].rev: [p[i].rev]}

        elif cls.context["rev"] == p[i + 3].rev:
            return {p[i + 3].rev: [p[i + 1].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    monkeypatch.setattr(HGMO, "pushid", property(lambda cls: 1))

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure-current", result="success"),
        Task.create(id="1", label="test-failure-next", result="success"),
    ]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        ),
        Task.create(
            id="1",
            label="test-failure-next",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        ),
    ]
    p[i + 1].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {"test-failure-current": 0}
    assert p[i + 1].get_regressions("label") == {"test-failure-next": 0}


def test_fixed_by_commit_task_didnt_run_in_parents(monkeypatch, create_pushes):
    """
    Tests the scenario where a task didn't run in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to the back-outs.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {p[i + 2].rev: [p[i].rev]}

        elif cls.context["rev"] == p[i + 3].rev:
            return {p[i + 3].rev: [p[i + 1].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    monkeypatch.setattr(HGMO, "pushid", property(lambda cls: 1))

    p[i].backedoutby = p[i + 2].rev

    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {"test-failure-current": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_push_wasnt_backedout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of another push.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {p[i + 3].rev: [p[i - 1].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure-current", result="success")
    ]
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 2].rev

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of another push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {p[i + 3].rev: [p[i + 1].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 4].rev
    p[i + 1].tasks = []
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 0}


def test_fixed_by_commit_another_push_possible_classification2(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of another push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == "rev3":
            return {
                "rev3": [p[i + 2].rev],
                "rev3.2": [p[i + 1].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 4].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note="rev3",
        )
    ]
    p[i + 1].backedoutby = "rev3.2"
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note="3rev1",
        )
    ]
    p[i + 2].backedoutby = "rev3"
    p[i + 3]._revs = ["rev3", "rev3.2"]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 0}
    assert p[i + 2].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification3(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a wrong revision, then failed in a following push with 'fixed by commit'
    information pointing to a back-out of another push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {
                p[i + 3].rev: [p[i + 2].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 4].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 0}
    assert p[i + 2].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification4(
    monkeypatch, create_pushes
):
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {
                p[i + 3].rev: [p[i].rev],
                "rev3.2": [p[i + 1].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]
    p[i + 2].backedoutby = "rev3.2"
    p[i + 3]._revs = [p[i + 3].rev, "rev3.2"]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {"test-failure": 0}
    assert p[i + 3].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification5(
    monkeypatch, create_pushes
):
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {
                p[i + 3].rev: [p[i + 1].rev],
                "3rev2": [p[i].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = "3rev2"
    p[i + 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]
    p[i + 2].backedoutby = p[i + 3].rev
    p[i + 3]._revs = [p[i + 3].rev, "3rev2"]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {"test-failure": 0}
    assert p[i + 3].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification6(
    monkeypatch, create_pushes, responses
):
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    r = requests.get(
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(
            branch="integration/autoland", rev=p[i + 3].rev
        )
    )

    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(
            branch="integration/autoland", rev="3rev2"
        ),
        json=r.json(),
    )

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {
                p[i + 3].rev: [p[i].rev],
                "3rev2": [p[i + 1].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note="3rev2",
        )
    ]
    p[i + 2].backedoutby = "3rev2"
    p[i + 3]._revs = [p[i + 3].rev, "3rev2"]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {"test-failure": 0}
    assert p[i + 3].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification7(
    monkeypatch, create_pushes, responses
):
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    r = requests.get(
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(
            branch="integration/autoland", rev=p[i + 3].rev
        )
    )

    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(
            branch="integration/autoland", rev="3rev2"
        ),
        json=r.json(),
    )

    def mock_backouts(cls):
        if cls.context["rev"] == "3rev2":
            return {
                p[i + 3].rev: [p[i + 1].rev],
                "3rev2": [p[i].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = "3rev2"
    p[i + 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note="3rev2",
        )
    ]
    p[i + 2].backedoutby = p[i + 3].rev
    p[i + 3]._revs = [p[i + 3].rev, "3rev2"]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}
    assert p[i + 3].get_regressions("label") == {}


def test_fixed_by_commit_another_push_possible_classification8(
    monkeypatch, create_pushes
):
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 4].rev:
            return {
                p[i + 4].rev: [p[i + 2].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 4].rev,
        )
    ]
    p[i + 2].tasks = []
    p[i + 2].backedoutby = p[i + 4].rev
    p[i + 3].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 4].rev,
        )
    ]
    p[i + 4].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i + 4].bugs = p[i].bugs
    p[i + 4]._revs = [p[i + 4].rev, "rev4.2"]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}
    assert p[i + 3].get_regressions("label") == {}


def test_intermittent_then_unclassified(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'intermittent' classification,
    then failed in a following push without classification.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 4].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="intermittent",
        )
    ]
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="not classified",
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    # TODO: Should it be considered a regression of this push? (only if the push was backed-out)
    assert p[i + 2].get_regressions("label") == {}


def test_fixed_by_commit_after_intermittent(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed and was marked as intermittent
    in the push of interest, then marked as 'fixed by commit' (pointing to a backout of the push of
    interest) in a later push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {
                p[i + 2].rev: [p[i].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="intermittent",
        )
    ]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        )
    ]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_after_success(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, succeeded in the push of interest,
    then marked as 'fixed by commit' (pointing to a backout of the push of interest) in a later push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {
                p[i + 2].rev: [p[i].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [Task.create(id="1", label="test-failure", result="success",)]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        )
    ]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_intermittent_after_fixed_by_commit(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed and was marked as 'fixed by commit' (pointing to a
    backout of the push of interest) in the push of interest, then marked as intermittent in a later push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {
                p[i + 2].rev: [p[i].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        )
    ]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="intermittent",
        )
    ]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_success_after_fixed_by_commit(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed and was marked as 'fixed by commit' (pointing to a
    backout of the push of interest) in the push of interest, then marked as intermittent in a later push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {
                p[i + 2].rev: [p[i].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        )
    ]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [Task.create(id="1", label="test-failure", result="success",)]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_success_after_fixed_by_commit_not_on_push_interest(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the push of interest, failed and was marked as
    'fixed by commit' (pointing to a backout of the push of interest) in a following push, then passed in
    a later push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {
                p[i + 3].rev: [p[i].rev],
            }

        elif cls.context["rev"] == p[i + 4].rev:
            return {
                p[i + 4].rev: [p[i + 1].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = []
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 4].rev
    p[i + 2].tasks = [Task.create(id="1", label="test-failure", result="success",)]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_intermittent_after_fixed_by_commit_not_on_push_interest(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the push of interest, failed and was marked as
    'fixed by commit' (pointing to a backout of the push of interest) in a following push, then marked as 'fixed by commit'
    (pointing to a backout of another push) in a following push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {
                p[i + 3].rev: [p[i].rev],
            }

        elif cls.context["rev"] == p[i + 4].rev:
            return {
                p[i + 4].rev: [p[i + 1].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = []
    p[i].backedoutby = p[i + 3].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 4].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="intermittent",
        )
    ]

    assert p[i].get_regressions("label") == {"test-failure": 1}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_failure_on_another_push_possible_classification(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of the following push.
    """
    p = create_pushes(6)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 3].rev:
            return {p[i + 3].rev: [p[i + 1].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 4].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 3].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 0}


def test_fixed_by_commit_another_push_wrong_classification(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest and failed in a following push, with wrong 'fixed by commit' information
    pointing to a back-out of another push.
    """
    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == "rev4":
            return {"rev4": [p[i + 1].rev], "rev4.2": [p[i].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note="rev4",
        )
    ]
    p[i].backedoutby = "rev4.2"
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note="rev4",
        )
    ]
    p[i + 1].backedoutby = "rev4"
    p[i + 2]._revs = ["rev4", "rev4.2"]

    assert p[i].get_regressions("label") == {"test-failure": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_another_push_wrong_classification_bustage_fixed(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the push
    of interest (which had some possible candidates for bustage fixes) and failed in a following
    push, with wrong 'fixed by commit' information pointing to a back-out of another push.
    """
    p = create_pushes(7)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 4].rev:
            return {p[i + 4].rev: [p[i + 3].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = []
    p[i].bugs = {123}
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 4].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 5].rev
    p[i + 2].bugs = {123}

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 1}


def test_fixed_by_commit_another_push_wrong_classification_bustage_fixed2(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the push
    of interest (which had some possible candidates for bustage fixes) and failed in a following
    push, with wrong 'fixed by commit' information pointing to a back-out of another push.
    The only difference with the previous test is a different order of pushes.
    """
    p = create_pushes(7)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 4].rev:
            return {p[i + 4].rev: [p[i + 3].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = []
    p[i].bugs = {123}
    p[i + 1].bugs = {123}
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 4].rev,
        )
    ]
    p[i + 2].backedoutby = p[i + 5].rev

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {"test-failure": 2}


def test_fixed_by_commit_another_push_wrong_classification2(monkeypatch, create_pushes):
    p = create_pushes(7)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 4].rev:
            return {
                p[i + 4].rev: [p[i].rev],
            }

        if cls.context["rev"] == p[i + 5].rev:
            return {
                p[i + 5].rev: [p[i + 1].rev],
            }

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i].backedoutby = p[i + 4].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 4].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 5].rev
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 5].rev,
        )
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {"test-failure": 1}
    assert p[i + 2].get_regressions("label") == {}
    assert p[i + 3].get_regressions("label") == {}


def test_fixed_by_commit_multiple_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of both revisions from this push and another push.
    """
    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {p[i + 2].rev: [p[i + 1].rev, "rev1.2"], "rev4.2": ["rev1.1"]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    def mock_pushid(cls):
        if cls.context["rev"] == "rev1.1":
            return int(p[i]._id)
        elif cls.context["rev"] == "rev1.2":
            return int(p[i]._id)
        elif cls.context["rev"] == "rev3":
            return int(3)
        elif cls.context["rev"] == "rev18":
            return int(18)
        else:
            raise Exception(cls.context["rev"])

    monkeypatch.setattr(HGMO, "pushid", property(mock_pushid))

    p[i - 1].tasks = [Task.create(id="1", label="test-failure", result="success")]
    p[i]._revs = ["rev1.1", "rev1.2"]
    p[i].backedoutby = "rev4.2"
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        )
    ]
    p[i + 1].backedoutby = p[i + 2].rev
    p[i + 2]._revs = [p[i + 2].rev, "rev4.2"]

    assert p[i].get_regressions("label") == {"test-failure": 1}
    assert p[i + 1].get_regressions("label") == {"test-failure": 1}


def test_fixed_by_commit_no_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where two tasks succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a bustage fix.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == "xxx":
            return {}

        if cls.context["rev"] == p[i + 2].rev:
            return {p[i + 2].rev: p[i + 1].rev}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    monkeypatch.setattr(HGMO, "pushid", property(lambda cls: 1))

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure-current", result="success"),
        Task.create(id="1", label="test-failure-next", result="success"),
    ]
    p[i].backedoutby = p[i + 3].rev

    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note="xxx",
        ),
        Task.create(
            id="1",
            label="test-failure-next",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        ),
    ]
    p[i + 1].backedoutby = p[i + 2].rev

    assert p[i].get_regressions("label") == {"test-failure-current": 1}
    assert p[i + 1].get_regressions("label") == {
        "test-failure-current": 1,
        "test-failure-next": 0,
    }


def test_intermittent_without_classification_and_not_backedout(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, was intermittent
    in the push of interest, which was not backed-out and didn't have a classification.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="not classified",
        ),
    ]
    p[i].backedoutby = p[i + 1].rev

    assert p[i].get_regressions("label") == {"test-intermittent": 0}


def test_far_intermittent_without_classification_and_not_backedout(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was not
    backed-out and didn't have a classification.
    """
    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i + 1].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="not classified",
        ),
    ]

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}


def test_intermittent_without_classification_and_backedout(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, was intermittent
    in the push of interest, which was backed-out and didn't have a classification.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="not classified",
        ),
    ]
    p[i].backedoutby = p[i + 1].rev

    assert p[i].get_regressions("label") == {"test-intermittent": 0}


def test_far_intermittent_without_classification_and_backedout(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was
    backed-out and didn't have a classification.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="not classified",
        ),
    ]
    p[i + 1].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {"test-intermittent": 2}
    assert p[i + 1].get_regressions("label") == {"test-intermittent": 2}


def test_intermittent_fixed_by_commit(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was
    backed-out and had a 'fixed by commit' classification.
    """
    p = create_pushes(6)
    i = 2  # the index of the push we are mainly interested in

    def mock_backouts(cls):
        if cls.context["rev"] == p[i + 2].rev:
            return {p[i + 2].rev: [p[i].rev, p[i + 2].rev]}

        return {}

    monkeypatch.setattr(HGMO, "backouts", property(mock_backouts))

    p[i - 2].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i - 2].backedoutby = None
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="fixed by commit",
            classification_note=p[i + 2].rev,
        ),
    ]
    p[i + 1].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {"test-intermittent": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_intermittent_classification(create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, failed in a following push, which was
    backed-out and had a 'intermittent' classification.
    """
    p = create_pushes(5)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i].backedoutby = p[i + 2].rev
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-intermittent",
            result="testfailed",
            classification="intermittent",
        )
    ]
    p[i + 1].backedoutby = p[i + 3].rev

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}
