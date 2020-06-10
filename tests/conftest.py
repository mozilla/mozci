# -*- coding: utf-8 -*-
import json

import pytest
from responses import RequestsMock

from mozci.push import MAX_DEPTH, Push
from mozci.util.hgmo import HGMO


@pytest.fixture(autouse=True)
def reset_hgmo_cache():
    yield
    HGMO.CACHE = {}


@pytest.fixture
def responses():
    with RequestsMock(assert_all_requests_are_fired=False) as rsps:
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

    def inner(rev=None, branch="integration/autoland", json_data=None):
        nonlocal prev_push, push_id

        if not rev:
            rev = "rev{}".format(push_id)

        if json_data is None:
            json_data = {
                "node": rev,
            }

        responses.add(
            responses.GET,
            HGMO.JSON_TEMPLATE.format(branch=branch, rev=rev),
            json=json_data,
            status=200,
        )

        def automationrelevance_callback(request):
            *repo, _, revision = request.path_url[1:].split("/")
            body = {
                "changesets": [
                    {
                        "bugs": [{"no": bug_id} for bug_id in push.bugs],
                        "backsoutnodes": [],
                    }
                ]
            }
            return (200, {}, json.dumps(body))

        responses.add_callback(
            responses.GET,
            HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(branch=branch, rev=rev),
            callback=automationrelevance_callback,
            content_type="application/json",
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
    """

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
