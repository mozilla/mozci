# -*- coding: utf-8 -*-

import pytest

from mozci.push import MAX_DEPTH, Push
from mozci.task import Task
from mozci.util.hgmo import HGMO


@pytest.fixture(autouse=True)
def reset_hgmo_cache():
    yield
    HGMO.CACHE = {}


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
    p[i].backedoutby = "xxx"
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 1].backedoutby = "xxx"
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].backedoutby = "xxx"

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
    p[i].backedoutby = "xxx"
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 1].backedoutby = "xxx"
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
    p[i + 2].backedoutby = "xxx"

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
    p[i + 1].backedoutby = "xxx"
    p[i + 2].tasks = [
        Task.create(
            id="1",
            label="test-prova",
            result="testfailed",
            classification="not classified",
        )
    ]
    p[i + 2].backedoutby = "xxx"

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
    p[i].backedoutby = "xxx"
    p[i + 1].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i + 2].tasks = [Task.create(id="1", label="test-prova", result="success")]

    assert p[i - 2].get_regressions("label") == {}
    assert p[i - 1].get_regressions("label") == {}
    assert p[i].get_regressions("label") == {"test-prova": 0}
    assert p[i + 1].get_regressions("label") == {}
    assert p[i + 2].get_regressions("label") == {}


def test_succeeded_and_backedout(create_pushes):
    """
    Tests the scenario where a task succeeded in a push which was backed-out.
    """
    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i].tasks = [Task.create(id="1", label="test-prova", result="success")]
    p[i].backedoutby = "xxx"

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
    p[i].backedoutby = "xxx"

    assert p[i].get_regressions("label") == {"test-prova": 0}


def test_failed_and_not_backedout(create_pushes):
    """
    Tests the scenario where a task failed in a push which was not backed-out.
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

    assert p[i].get_regressions("label") == {"test-prova": 0}


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

    assert p[i].get_regressions("label") == {"test-prova": 6}


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
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

    p = create_pushes(3)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure-current", result="success"),
        Task.create(id="1", label="test-failure-next", result="success"),
    ]
    p[i].backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note="d25e5c66de225e2d1b989af61a0420874707dd14",
        ),
        Task.create(
            id="1",
            label="test-failure-next",
            result="testfailed",
            classification="fixed by commit",
            classification_note="012c3f1626b3",
        ),
    ]
    p[i + 1].backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    assert p[i].get_regressions("label") == {"test-failure-current": 0}
    assert p[i + 1].get_regressions("label") == {"test-failure-next": 0}


def test_fixed_by_commit_task_didnt_run_in_parents(monkeypatch, create_pushes):
    """
    Tests the scenario where a task didn't run in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to the back-outs.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i].backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"

    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note="d25e5c66de225e2d1b989af61a0420874707dd14",
        )
    ]
    p[i + 1].backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    assert p[i].get_regressions("label") == {"test-failure-current": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_push_wasnt_backedout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a back-out of another push.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure-current", result="success")
    ]
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-failure-current",
            result="testfailed",
            classification="fixed by commit",
            classification_note="xxx",
        )
    ]
    p[i + 1].backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}


def test_fixed_by_commit_no_backout(monkeypatch, create_pushes):
    """
    Tests the scenario where two tasks succeeded in a parent push, didn't run in the
    push of interest and failed in a following push, with 'fixed by commit' information
    pointing to a bustage fix.
    """

    def mock_is_backout(cls):
        if cls.context["rev"] == "xxx":
            return False

        return True

    monkeypatch.setattr(HGMO, "is_backout", property(mock_is_backout))

    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [
        Task.create(id="1", label="test-failure-current", result="success"),
        Task.create(id="1", label="test-failure-next", result="success"),
    ]
    p[i].backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"

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
            classification_note="012c3f1626b3",
        ),
    ]
    p[i + 1].backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    assert p[i].get_regressions("label") == {"test-failure-current": 1}
    assert p[i + 1].get_regressions("label") == {
        "test-failure-current": 1,
        "test-failure-next": 0,
    }


def test_intermittent_without_classification_and_not_backedout(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, was intermittent
    in the push of interest, which was not backed-out and didn't have a classification.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

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
    p[i].backedoutby = "xxx"

    assert p[i].get_regressions("label") == {"test-intermittent": 0}


def test_far_intermittent_without_classification_and_not_backedout(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was not
    backed-out and didn't have a classification.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

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

    assert p[i].get_regressions("label") == {"test-intermittent": 4}
    assert p[i + 1].get_regressions("label") == {"test-intermittent": 4}


def test_intermittent_without_classification_and_backedout(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, was intermittent
    in the push of interest, which was backed-out and didn't have a classification.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

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
    p[i].backedoutby = "xxx"

    assert p[i].get_regressions("label") == {"test-intermittent": 0}


def test_far_intermittent_without_classification_and_backedout(
    monkeypatch, create_pushes
):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was
    backed-out and didn't have a classification.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

    p = create_pushes(4)
    i = 1  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i].backedoutby = "xxx"
    p[i + 1].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="not classified",
        ),
    ]
    p[i + 1].backedoutby = "yyy"

    assert p[i].get_regressions("label") == {"test-intermittent": 2}
    assert p[i + 1].get_regressions("label") == {"test-intermittent": 2}


def test_intermittent_fixed_by_commit(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, was intermittent in a following push, which was
    backed-out and had a 'fixed by commit' classification.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

    p = create_pushes(5)
    i = 2  # the index of the push we are mainly interested in

    p[i - 2].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i - 2].backedoutby = None
    p[i].backedoutby = "d25e5c66de225e2d1b989af61a0420874707dd14"
    p[i + 1].tasks = [
        Task.create(id="1", label="test-intermittent", result="success"),
        Task.create(
            id="2",
            label="test-intermittent",
            result="testfailed",
            classification="fixed by commit",
            classification_note="d25e5c66de225e2d1b989af61a0420874707dd14",
        ),
    ]
    p[i + 1].backedoutby = "012c3f1626b3e9bcd803d19aaf9584a81c5c95de"

    assert p[i].get_regressions("label") == {"test-intermittent": 0}
    assert p[i + 1].get_regressions("label") == {}


def test_intermittent_classification(monkeypatch, create_pushes):
    """
    Tests the scenario where a task succeeded in a parent push, didn't run in the
    in the push of interest, failed in a following push, which was
    backed-out and had a 'intermittent' classification.
    """
    monkeypatch.setattr(HGMO, "is_backout", property(lambda cls: True))

    p = create_pushes(5)
    i = 2  # the index of the push we are mainly interested in

    p[i - 1].tasks = [Task.create(id="1", label="test-intermittent", result="success")]
    p[i].backedoutby = "xxx"
    p[i + 1].tasks = [
        Task.create(
            id="1",
            label="test-intermittent",
            result="testfailed",
            classification="intermittent",
        )
    ]
    p[i + 1].backedoutby = "yyy"

    assert p[i].get_regressions("label") == {}
    assert p[i + 1].get_regressions("label") == {}


def test_create_push(responses):
    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-pushes?version=2&startID=122&endID=123",
        json={
            "pushes": {
                "123": {
                    "changesets": ["123456"],
                    "date": 1213174092,
                    "user": "user@example.org",
                },
            },
        },
        status=200,
    )
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev="abcdef"),
        json={"node": "abcdef"},
        status=200,
    )
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev="123456"),
        json={"node": "123456"},
        status=200,
    )

    p1 = Push("abcdef")
    p2 = p1.create_push(123)
    assert p2.rev == "123456"
    assert p2.id == 123
    assert p2.date == 1213174092
