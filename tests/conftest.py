import pytest
from responses import RequestsMock

from mozci.push import Push
from mozci.util.hgmo import HGMO


@pytest.fixture
def responses():
    with RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def create_push(responses):
    """Returns a factory method that creates a `Push` instance.

    Each subsequent call to the factory will set the previously created
    instance as the current's parent.
    """

    prev_push = None
    push_id = 1

    def inner(rev=None, branch="autoland", json=None, automationrelevance=None):
        nonlocal prev_push, push_id

        if not rev:
            rev = 'rev{}'.format(push_id)

        push = Push(rev, branch)
        push._id = push_id
        push.backedoutby = None
        push.tasks = []

        if json is not None:
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

        if prev_push:
            push.parent = prev_push
            prev_push.child = push

        # Update global state
        prev_push = push
        push_id += 1
        return push

    yield inner
