# -*- coding: utf-8 -*-

from mozci.push import Push
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

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current.parent = parent2
    current.child = child1
    current.tasks = []

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last.child = last
    last.tasks = []

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

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current.parent = parent2
    current.child = child1
    current.tasks = []

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    last.child = last
    last.tasks = []

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

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current.parent = parent2
    current.child = child1
    current.tasks = []

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="success")]

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last.child = last
    last.tasks = []

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

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current.parent = parent2
    current.child = child1
    current.tasks = [Task.create(id="1", label="test-prova", result="success")]

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    last.child = last
    last.tasks = []

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {}
    assert child1.get_regressions("label") == {"test-prova": 0}
    assert child2.get_regressions("label") == {}


# fails in first, passes in second, passes in third -> regression of first
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

    parent1.parent = first
    parent1.child = parent2
    parent1.tasks = []

    parent2.parent = parent1
    parent2.child = current
    parent2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    current.parent = parent2
    current.child = child1
    current.tasks = [Task.create(id="1", label="test-prova", result="testfailed", classification="not classified")]  # noqa

    child1.parent = current
    child1.child = child2
    child1.tasks = [Task.create(id="1", label="test-prova", result="success")]

    child2.parent = child1
    child2.child = last
    child2.tasks = [Task.create(id="1", label="test-prova", result="success")]

    last.child = last
    last.tasks = []

    assert parent1.get_regressions("label") == {}
    assert parent2.get_regressions("label") == {}
    assert current.get_regressions("label") == {"test-prova": 0}
    assert child1.get_regressions("label") == {}
    assert child2.get_regressions("label") == {}
