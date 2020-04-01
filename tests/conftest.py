# -*- coding: utf-8 -*-
import pytest
from responses import RequestsMock

from mozci.push import MAX_DEPTH, Push
from mozci.util.hgmo import HGMO


@pytest.fixture
def responses():
    with RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def create_push(monkeypatch, responses):
    """Returns a factory method that creates a `Push` instance.

    Each subsequent call to the factory will set the previously created
    instance as the current's parent.
    """

    prev_push = None
    push_id = 1

    push_rev_to_id = {}

    def mock_pushid(cls):
        return push_rev_to_id[cls.context["rev"]]

    monkeypatch.setattr(HGMO, "pushid", property(mock_pushid))

    def inner(
        rev=None, branch="integration/autoland", json=None, automationrelevance=None
    ):
        nonlocal prev_push, push_id

        if not rev:
            rev = "rev{}".format(push_id)

        if json is None:
            json = {
                "node": rev,
            }

        responses.add(
            responses.GET,
            HGMO.JSON_TEMPLATE.format(branch=branch, rev=rev),
            json=json,
            status=200,
        )

        if automationrelevance is not None:
            responses.add(
                responses.GET,
                HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(branch=branch, rev=rev),
                json=automationrelevance,
                status=200,
            )

        push = Push(rev, branch)
        push._id = push_id
        push_rev_to_id[rev] = push_id
        push.backedoutby = None
        push.bugs = {push_id}
        push.tasks = []
        push._revs = [push.rev]

        if prev_push:
            push.parent = prev_push
            prev_push.child = push

        # Update global state
        prev_push = push
        push_id += 1
        return push

    yield inner


@pytest.fixture
def create_pushes(create_push):
    """Returns a factory method that creates a range of pushes.

    The first push will set itself as it's own """

    def inner(num):
        pushes = []

        # Create parents.
        for j in range(MAX_DEPTH + 1):
            create_push()

        # Create our pushes.
        for i in range(num):
            pushes.append(create_push())

        # Create children.
        for j in range(MAX_DEPTH + 1):
            create_push()

        return pushes

    return inner
