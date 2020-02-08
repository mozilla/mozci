# -*- coding: utf-8 -*-

from mozci.push import Push, MAX_DEPTH
from mozci.task import Task


def test_succeeded_in_parent_didnt_run_in_current_failed_in_child_failed_in_grandchild():
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, and failed in its following pushes.
    '''
    first = Push("first")
    parent1 = Push("parent1")
    parent2 = Push("parent2")
    current = Push("current")
    child1 = Push("child1")
    child2 = Push("child2")
    last = Push("last")

    first.parent = first
    first.child = parent1
    first.tasks = []
    first.backedoutby = None

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []
    parent1.backedoutby = None

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    parent2.backedoutby = None

    current.parent = parent2
    current.child = child1
    current.tasks = []
    current.backedoutby = "xxx"

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child1.backedoutby = "xxx"

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child2.backedoutby = "xxx"

    last.parent = child2
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 1}
    assert child1.get_regressions("label") == {"test-prova": 1}
    assert child2.get_regressions("label") == {}


def test_succeeded_in_parent_didnt_run_in_current_failed_in_child_succeeded_in_grandchild():
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, failed in a following push, and succeeded in a second
    following push.
    '''
    first = Push("first")
    parent1 = Push("parent1")
    parent2 = Push("parent2")
    current = Push("current")
    child1 = Push("child1")
    child2 = Push("child2")
    last = Push("last")

    first.parent = first
    first.child = parent1
    first.tasks = []
    first.backedoutby = None

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []
    parent1.backedoutby = None

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    parent2.backedoutby = None

    current.parent = parent2
    current.child = child1
    current.tasks = []
    current.backedoutby = "xxx"

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child1.backedoutby = "xxx"

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    child2.backedoutby = None

    last.parent = child2
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 1}
    assert child1.get_regressions("label") == {"test-prova": 1}
    assert child2.get_regressions("label") == {}


def test_succeeded_in_parent_didnt_run_in_current_passed_in_child_failed_in_grandchild():
    '''
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest, succeeded in a following push, and failed in a second
    following push.
    '''
    first = Push("first")
    parent1 = Push("parent1")
    parent2 = Push("parent2")
    current = Push("current")
    child1 = Push("child1")
    child2 = Push("child2")
    last = Push("last")

    first.parent = first
    first.child = parent1
    first.tasks = []
    first.backedoutby = None

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []
    parent1.backedoutby = None

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    parent2.backedoutby = None

    current.parent = parent2
    current.child = child1
    current.tasks = []
    current.backedoutby = None

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="success")]
    child1.backedoutby = None

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child2.backedoutby = "xxx"

    last.parent = child2
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {}
    assert child1.get_regressions("label") == {}
    assert child2.get_regressions("label") == {"test-prova": 0}


def test_succeeded_in_parent_succeeded_in_current_failed_in_child_failed_in_grandchild():
    '''
    Tests the scenario where a task succeeded in a parent push, succeeded in the
    push of interest, failed in a following push, and failed in a second
    following push.
    '''
    first = Push("first")
    parent1 = Push("parent1")
    parent2 = Push("parent2")
    current = Push("current")
    child1 = Push("child1")
    child2 = Push("child2")
    last = Push("last")

    first.parent = first
    first.child = parent1
    first.tasks = []
    first.backedoutby = None

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []
    parent1.backedoutby = None

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    parent2.backedoutby = None

    current.parent = parent2
    current.child = child1
    current.tasks = [Task.create(id="1", label="test-prova", result="success")]
    current.backedoutby = None

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child1.backedoutby = "xxx"

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    child2.backedoutby = "xxx"

    last.parent = child2
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {}
    assert child1.get_regressions("label") == {"test-prova": 0}
    assert child2.get_regressions("label") == {}


def test_succeeded_in_parent_failed_in_current_succeeded_in_child_succeeded_in_grandchild():
    '''
    Tests the scenario where a task succeeded in a parent push, failed in the
    push of interest, succeeded in a following push, and succeeded in a second
    following push.
    '''
    first = Push("first")
    parent1 = Push("parent1")
    parent2 = Push("parent2")
    current = Push("current")
    child1 = Push("child1")
    child2 = Push("child2")
    last = Push("last")

    first.parent = first
    first.child = parent1
    first.tasks = []
    first.backedoutby = None

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []
    parent1.backedoutby = None

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    parent2.backedoutby = None

    current.parent = parent2
    current.child = child1
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    current.backedoutby = "xxx"

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="success")]
    child1.backedoutby = None

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="success")]
    child2.backedoutby = None

    last.parent = child2
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 0}
    assert child1.get_regressions("label") == {}
    assert child2.get_regressions("label") == {}


def test_succeeded_and_backedout():
    '''
    Tests the scenario where a task succeeded in a push which was backed-out.
    '''
    first = Push("first")
    current = Push("current")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = []
    first.backedoutby = None

    current.parent = first
    current.child = last
    current.tasks = [Task.create(id="1", label="test-prova", result="success")]
    current.backedoutby = "xxx"

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {}


def test_failed_and_backedout():
    '''
    Tests the scenario where a task failed in a push which was backed-out.
    '''
    first = Push("first")
    current = Push("current")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]
    first.backedoutby = None

    current.parent = first
    current.child = last
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    current.backedoutby = "xxx"

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-prova': 0}


def test_failed_and_not_backedout():
    '''
    Tests the scenario where a task failed in a push which was not backed-out.
    '''
    first = Push("first")
    current = Push("current")
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]
    first.backedoutby = None

    current.parent = first
    current.child = last
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa
    current.backedoutby = None

    last.parent = current
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-prova': 0}


def test_child_failed_and_not_backedout():
    '''
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out, and failed in a following push.
    '''
    first = Push("first")
    current = Push("current")
    children = []
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]
    first.backedoutby = None

    children = [Push(f"child{i}") for i in range(MAX_DEPTH // 4)]

    current.parent = first
    current.child = children[0]
    current.tasks = []
    current.backedoutby = None

    for i in range(MAX_DEPTH // 4):
        children[i].tasks = []
        children[i].backedoutby = None

        if i == 0:
            children[i].parent = current
        else:
            children[i].parent = children[i - 1]

        if i == len(children) - 1:
            children[i].child = last
        else:
            children[i].child = children[i + 1]

    children[len(children) - 1].tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last.parent = children[len(children) - 1]
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {'test-prova': 6}


def test_far_child_failed_and_backedout():
    '''
    Tests the scenario where a task didn't run in the push of interest, which was not
    backed-out, and failed in a (far away) following push.
    '''
    first = Push("first")
    current = Push("current")
    children = []
    last = Push("last")

    first.parent = first
    first.child = current
    first.tasks = [Task.create(id="1", label="test-prova", result="success")]
    first.backedoutby = None

    children = [Push(f"child{i}") for i in range(MAX_DEPTH // 2 + 1)]

    current.parent = first
    current.child = children[0]
    current.tasks = []
    current.backedoutby = None

    for i in range(MAX_DEPTH // 2 + 1):
        children[i].tasks = []
        children[i].backedoutby = None

        if i == 0:
            children[i].parent = current
        else:
            children[i].parent = children[i - 1]

        if i == len(children) - 1:
            children[i].child = last
        else:
            children[i].child = children[i + 1]

    children[len(children) - 1].tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last.parent = children[len(children) - 1]
    last.child = last
    last.tasks = []
    last.backedoutby = None

    assert current.get_regressions("label") == {}
