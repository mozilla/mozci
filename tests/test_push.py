# -*- coding: utf-8 -*-

import pytest

from mozci.push import Push, MAX_DEPTH
from mozci.task import Task
from mozci.util.hgmo import HGMO


@pytest.fixture(autouse=True, scope='module')
def reset_hgmo_cache():
    yield
    HGMO.CACHE = {}


def test_succeeded_in_parent_didnt_run_in_current_failed_in_child_failed_in_grandchild(create_push):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, and failed in its following pushes.
    '''
    create_push("first")

    parent1 = create_push("parent1")

    parent2 = create_push("parent2")
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")
    current.backedoutby = "xxx"

    child1 = create_push("child1")
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child1.backedoutby = "xxx"

    child2 = create_push("child2")
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child2.backedoutby = "xxx"

    last = create_push("last")
    last.child = last

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 1}
    assert child1.get_regressions("label") == {"test-prova": 1}
    assert child2.get_regressions("label") == {}


def test_succeeded_in_parent_didnt_run_in_current_failed_in_child_succeeded_in_grandchild(create_push):  # noqa
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, failed in a following push, and succeeded in a second
    following push.
    '''
    create_push("first")

    parent1 = create_push("parent1")

    parent2 = create_push("parent2")
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")
    current.backedoutby = "xxx"

    child1 = create_push("child1")
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child1.backedoutby = "xxx"

    child2 = create_push("child2")
    child2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    last = create_push("last")
    last.child = last

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 1}
    assert child1.get_regressions("label") == {"test-prova": 1}
    assert child2.get_regressions("label") == {}


def test_succeeded_in_parent_didnt_run_in_current_passed_in_child_failed_in_grandchild(create_push):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, succeeded in a following push, and failed in a second
    following push.
    '''
    create_push("first")

    parent1 = create_push("parent1")

    parent2 = create_push("parent2")
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")

    child1 = create_push("child1")
    child1.tasks = [Task.create(id="1", label="test-prova", result="success")]

    child2 = create_push("child2")
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child2.backedoutby = "xxx"

    last = create_push("last")
    last.child = last

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {}
    assert child1.get_regressions("label") == {}
    assert child2.get_regressions("label") == {"test-prova": 0}


def test_succeeded_in_parent_succeeded_in_current_failed_in_child_failed_in_grandchild(create_push):
    '''
    Tests the scenario where a task succeeded in a parent push, succeeded in the
    push of interest, failed in a following push, and failed in a second
    following push.
    '''
    create_push("first")

    parent1 = create_push("parent1")

    parent2 = create_push("parent2")
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")
    current.tasks = [Task.create(id="1", label="test-prova", result="success")]

    child1 = create_push("child1")
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child1.backedoutby = "xxx"

    child2 = create_push("child2")
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child2.backedoutby = "xxx"

    last = create_push("last")
    last.child = last

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {}
    assert child1.get_regressions("label") == {"test-prova": 0}
    assert child2.get_regressions("label") == {}


def test_succeeded_in_parent_failed_in_current_succeeded_in_child_succeeded_in_grandchild(create_push):  # noqa
    '''
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest, succeeded in a following push, and succeeded in a second
    following push.
    '''
    create_push("first")

    parent1 = create_push("parent1")

    parent2 = create_push("parent2")
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    current.backedoutby = "xxx"

    child1 = create_push("child1")
    child1.tasks = [Task.create(id="1", label="test-prova", result="success")]

    child2 = create_push("child2")
    child2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    last = create_push("last")
    last.child = last

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 0}
    assert child1.get_regressions("label") == {}
    assert child2.get_regressions("label") == {}


def test_succeeded_and_backedout(create_push):
    '''
    Tests the scenario where a task succeeded in a push which was backed-out.
    '''
    create_push("first")

    current = create_push("current")
    current.tasks = [Task.create(id="1", label="test-prova", result="success")]
    current.backedoutby = "xxx"

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {}


def test_failed_and_backedout(create_push):
    '''
    Tests the scenario where a task failed in a push which was backed-out.
    '''
    first = create_push("first")
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    current.backedoutby = "xxx"

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {'test-prova': 0}


def test_failed_and_not_backedout(create_push):
    '''
    Tests the scenario where a task failed in a push which was not backed-out.
    '''
    first = create_push("first")
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {'test-prova': 0}


def test_child_failed_and_not_backedout(create_push):
    '''
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out, and failed in a following push.
    '''
    first = create_push("first")
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")

    children = [create_push(f"child{i}") for i in range(MAX_DEPTH // 4)]
    children[len(children) - 1].tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {'test-prova': 6}


def test_far_child_failed_and_backedout(create_push):
    '''
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out, and failed in a (far away) following push.
    '''
    first = create_push("first")
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current = create_push("current")

    children = [create_push(f"child{i}") for i in range(MAX_DEPTH // 2 + 1)]
    children[len(children) - 1].tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {}


def test_fixed_by_commit(monkeypatch, create_push):
    '''
    Tests the scenario where two tasks succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to the back-outs.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = create_push("first")
    first.tasks = [
        Task.create(id="1", label="test-failure-current", result="success"),
        Task.create(id="1", label="test-failure-next", result="success")
    ]

    current = create_push("current")
    current.backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"

    next = create_push("next")
    next.tasks = [
        Task.create(id="1", label="test-failure-current", result="testfailed", classification="fixed by commit", classification_note="d25e5c66de225e2d1b989af61a0420874707dd14"),  # noqa
        Task.create(id="1", label="test-failure-next", result="testfailed", classification="fixed by commit", classification_note="012c3f1626b3"),  # noqa
    ]
    next.backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {'test-failure-current': 0}
    assert next.get_regressions("label") == {'test-failure-next': 0}


def test_fixed_by_commit_task_didnt_run_in_parents(monkeypatch, create_push):
    '''
    Tests the scenario where a task didn't run in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to the back-outs.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = create_push("first")
    first.parent = first

    current = create_push("current")
    current.backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"

    next = create_push("next")
    next.tasks = [Task.create(id="1", label="test-failure-current", result="testfailed", classification="fixed by commit", classification_note="d25e5c66de225e2d1b989af61a0420874707dd14")]  # noqa
    next.backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {'test-failure-current': 0}
    assert next.get_regressions("label") == {}


def test_fixed_by_commit_push_wasnt_backedout(monkeypatch, create_push):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of another push.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = create_push("first")
    first.tasks = [Task.create(id="1", label="test-failure-current", result="success")]

    current = create_push("current")

    next = create_push("next")
    next.tasks = [Task.create(id="1", label="test-failure-current", result="testfailed", classification="fixed by commit", classification_note="xxx")]  # noqa
    next.backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {}
    assert next.get_regressions("label") == {}


def test_fixed_by_commit_no_backout(monkeypatch, create_push):
    '''
    Tests the scenario where two tasks succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a bustage fix.
    '''
    def mock_is_backout(cls):
        if cls.rev == "xxx":
            return False

        return True

    monkeypatch.setattr(HGMO, 'is_backout', property(mock_is_backout))

    first = create_push("first")
    first.tasks = [Task.create(id="1", label="test-failure-current", result="success"), Task.create(id="1", label="test-failure-next", result="success")]  # noqa

    current = create_push("current")
    current.backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"

    next = create_push("next")
    next.tasks = [
        Task.create(id="1", label="test-failure-current", result="testfailed", classification="fixed by commit", classification_note="xxx"),  # noqa
        Task.create(id="1", label="test-failure-next", result="testfailed", classification="fixed by commit", classification_note="012c3f1626b3"),  # noqa
    ]
    next.backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    last = create_push("last")
    last.child = last

    assert current.get_regressions("label") == {'test-failure-current': 1}
    assert next.get_regressions("label") == {'test-failure-current': 1, 'test-failure-next': 0}


def test_intermittent_without_classification_and_not_backedout(monkeypatch):
    '''
    Tests the scenario where a task succeeded in a parent push, was intermittent
    in the push of interest, which was not backed-out and didn't have a classification.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = Push("first")
    current = Push("current")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    first.backedoutby = None

    current.parent = first
    current.child = last
    current.tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(id="2", label="test-intermittent", result="testfailed", classification="not classified"),  # noqa
    ]
    current.backedoutby = None
    current.backedoutby = "xxx"

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-intermittent': 0}


def test_far_intermittent_without_classification_and_not_backedout(monkeypatch):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was not
    backed-out and didn't have a classification.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = Push("first")
    current = Push("current")
    next = Push("next")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    first.backedoutby = None

    current.parent = first
    current.child = next
    current.tasks = []
    current.backedoutby = None

    next.parent = current
    next.child = last
    next.tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(id="2", label="test-intermittent", result="testfailed", classification="not classified"),  # noqa
    ]
    next.backedoutby = None

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-intermittent': 4}
    assert next.get_regressions("label") == {'test-intermittent': 4}


def test_intermittent_without_classification_and_backedout(monkeypatch):
    '''
    Tests the scenario where a task succeeded in a parent push, was intermittent
    in the push of interest, which was backed-out and didn't have a classification.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = Push("first")
    current = Push("current")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    first.backedoutby = None

    current.parent = first
    current.child = last
    current.tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(id="2", label="test-intermittent", result="testfailed", classification="not classified"),  # noqa
    ]
    current.backedoutby = "xxx"

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-intermittent': 0}


def test_far_intermittent_without_classification_and_backedout(monkeypatch):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was
    backed-out and didn't have a classification.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = Push("first")
    current = Push("current")
    next = Push("next")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    first.backedoutby = None

    current.parent = first
    current.child = next
    current.tasks = []
    current.backedoutby = "xxx"

    next.parent = current
    next.child = last
    next.tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(id="2", label="test-intermittent", result="testfailed", classification="not classified"),  # noqa
    ]
    next.backedoutby = "yyy"

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-intermittent': 2}
    assert next.get_regressions("label") == {'test-intermittent': 2}


def test_intermittent_fixed_by_commit(monkeypatch):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was
    backed-out and had a 'fixed by commit' classification.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = Push("first")
    second = Push("second")
    current = Push("current")
    next = Push("next")
    last = Push("last")

    first.parent = first
    first.child = second
    first.tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    first.backedoutby = None

    second.parent = first
    second.child = current
    second.tasks = []
    second.backedoutby = None

    current.parent = second
    current.child = next
    current.tasks = []
    current.backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"

    next.parent = current
    next.child = last
    next.tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(id="2", label="test-intermittent", result="testfailed", classification="fixed by commit", classification_note="d25e5c66de225e2d1b989af61a0420874707dd14"),  # noqa
    ]
    next.backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    last.parent = next
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-intermittent': 0}
    assert next.get_regressions("label") == {}


def test_intermittent_classification(monkeypatch):
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, failed in a following push, which was
    backed-out and had a 'intermittent' classification.
    '''
    monkeypatch.setattr(HGMO, 'is_backout', property(lambda cls: True))

    first = Push("first")
    second = Push("second")
    current = Push("current")
    next = Push("next")
    last = Push("last")

    first.parent = first
    first.child = second
    first.tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    first.backedoutby = None

    second.parent = first
    second.child = current
    second.tasks = []
    second.backedoutby = None

    current.parent = second
    current.child = next
    current.tasks = []
    current.backedoutby = "xxx"

    next.parent = current
    next.child = last
    next.tasks = [Task.create(id="1", label="test-intermittent", result="testfailed", classification="intermittent")]  # noqa
    next.backedoutby = "yyy"

    last.parent = next
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {}
    assert next.get_regressions("label") == {}


def test_create_push(responses):
    responses.add(
        responses.GET,
        'https://hg.mozilla.org/integration/autoland/json-pushes?version=2&startID=122&endID=123',
        json={
            'pushes': {
                '123': {
                    'changesets': ['123456'],
                    'date': 1213174092,
                    'user': 'user@example.org',
                },
            },
        },
        status=200,
    )

    p1 = Push("abcdef")
    p2 = p1.create_push(123)
    assert p2.rev == '123456'
    assert p2.id == 123
    assert p2.date == 1213174092
