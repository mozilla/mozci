# -*- coding: utf-8 -*-
import json
import os
import re

import pytest
from responses import RequestsMock

import mozci
from mozci import data
from mozci.configuration import Configuration
from mozci.data.base import DataHandler
from mozci.push import MAX_DEPTH, Push
from mozci.util.hgmo import HgRev

here = os.path.abspath(os.path.dirname(__file__))


@pytest.fixture(autouse=True, scope="session")
def set_config_path():
    os.environ["MOZCI_CONFIG_PATH"] = os.path.join(here, "config.toml")
    mozci.config = Configuration()
    data.handler = DataHandler(*mozci.config.data_sources)


@pytest.fixture(autouse=True)
def reset_hgmo_cache():
    yield
    HgRev.CACHE = {}


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

    monkeypatch.setattr(HgRev, "pushid", property(mock_pushid))

    def mock_node(cls):
        return cls.context["rev"]

    monkeypatch.setattr(HgRev, "node", property(mock_node))

    def inner(rev=None, branch="integration/autoland"):
        nonlocal prev_push, push_id

        if not rev:
            rev = "rev{}".format(push_id)

        def automationrelevance_callback(request):
            *repo, _, revision = request.path_url[1:].split("/")
            body = {
                "changesets": [
                    {
                        "node": rev,
                        "bugs": [{"no": bug_id} for bug_id in push.bugs],
                        "backsoutnodes": [],
                        "pushhead": push.rev,
                    }
                    for rev in push._revs
                ]
            }
            return (200, {}, json.dumps(body))

        responses.add_callback(
            responses.GET,
            HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(branch=branch, rev=rev),
            callback=automationrelevance_callback,
            content_type="application/json",
        )

        responses.add(
            responses.GET,
            re.compile(
                "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/.*/artifacts"
            ),
            json={"artifacts": []},
            status=200,
        )

        url = re.escape(HgRev.JSON_PUSHES_TEMPLATE_BASE.format(branch=branch))
        responses.add(
            responses.GET,
            re.compile(url + ".*"),
            json={"pushes": {}},
            status=200,
        )

        push = Push(rev, branch)
        push._id = push_id
        push_rev_to_id[rev] = push_id
        push.backedoutby = None
        push.bugs = {push_id}
        push.tasks = []
        push._revs = [push.rev]
        push.is_manifest_level = False

        if prev_push:
            push.parent = prev_push
            if branch != "try":
                prev_push.child = push

        # Update global state
        prev_push = push
        push_id += 1
        return push

    yield inner


@pytest.fixture
def create_pushes(create_push):
    """Returns a factory method that creates a range of pushes."""

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
