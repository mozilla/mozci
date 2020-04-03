# -*- coding: utf-8 -*-

import pytest

from mozci.errors import ChildPushNotFound, ParentPushNotFound, PushNotFound
from mozci.push import Push
from mozci.util.hgmo import HGMO


@pytest.fixture
def create_changesets():
    """Return a set of changesets in automationrelevance format.

    Ordered from base -> head.
    """

    def node(i):
        i = str(i)
        pad = "0" * (40 - len(i))
        return pad + i

    def inner(num, extra=None, head=1):
        changesets = []
        for i in reversed(range(head, num + head)):
            c = {
                "node": node(i),
                "parents": [node(i + 1)],
                "pushhead": node(head),
            }
            if isinstance(extra, list):
                c.update(extra[num - i])
            elif isinstance(extra, dict):
                c.update(extra)

            changesets.append(c)

        return changesets

    return inner


def test_create_push(responses):
    ctx = {
        "branch": "integration/autoland",
        "push_id_start": "122",
        "push_id_end": "123",
    }
    responses.add(
        responses.GET,
        HGMO.JSON_PUSHES_TEMPLATE.format(**ctx),
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


def test_push_does_not_exist(responses):
    # We hit hgmo when 'rev' is less than 40 characters.
    rev = "foobar"
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev=rev),
        json={f"error": "unknown revision '{rev}'"},
        status=404,
    )

    with pytest.raises(PushNotFound):
        Push(rev)

    # Otherwise we need to hit hgmo some other way.
    rev = "a" * 40
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev=rev),
        json={f"error": "unknown revision '{rev}'"},
        status=404,
    )
    p = Push(rev)
    with pytest.raises(PushNotFound):
        p.id


def test_push_bugs(responses):
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"bugs": [{"no": "1624503"}]},
                {"bugs": [{"no": "1624503"}]},
            ]
        },
        status=200,
    )

    p = Push(rev)
    assert p.bugs == {"1624503"}


def test_push_bugs_different(responses):
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"bugs": [{"no": "1617050"}]},
                {"bugs": [{"no": "1625220"}]},
                {"bugs": [{"no": "1625220"}]},
                {"bugs": [{"no": "1625220"}]},
                {"bugs": [{"no": "1595768"}]},
                {"bugs": [{"no": "1595768"}]},
            ]
        },
        status=200,
    )

    p = Push(rev)
    assert p.bugs == {"1617050", "1625220", "1595768"}


def test_push_bugs_multiple(responses):
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"bugs": [{"no": "1617050"}, {"no": "123"}]},
                {"bugs": [{"no": "1617050"}]},
                {"bugs": [{"no": "456"}]},
            ]
        },
        status=200,
    )

    p = Push(rev)
    assert p.bugs == {"123", "456", "1617050"}


def test_push_parent_on_autoland(responses):
    ctx = {
        "branch": "integration/autoland",
        "push_id_start": "121",
        "push_id_end": "122",
    }
    responses.add(
        responses.GET,
        HGMO.JSON_PUSHES_TEMPLATE.format(**ctx),
        json={
            "pushes": {
                "122": {
                    "changesets": ["b" * 40],
                    "date": 1213174092,
                    "user": "user@example.org",
                },
            },
        },
        status=200,
    )

    p1 = Push("a" * 40)
    p1._id = 123
    parent = p1.parent

    assert parent.id == 122


def test_push_parent_on_try(responses, create_changesets):
    changesets = create_changesets(
        4,
        [
            {"phase": "public"},
            {"phase": "public"},
            {"phase": "draft"},
            {"phase": "draft"},
        ],
    )

    from pprint import pprint

    pprint(changesets, indent=2)
    head = changesets[-1]["node"]
    ctx = {"branch": "try", "rev": head}

    # We'll query the initial pushes' changesets first.
    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"changesets": changesets},
        status=200,
    )

    # Should find changesets[1] as the parent and then start searching for it.
    parent_rev = changesets[1]["node"]

    # First we'll search mozilla-central, but won't find parent_rev.
    ctx["rev"] = parent_rev
    ctx["branch"] = "mozilla-central"
    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={f"error": "unknown revision '{parent_rev}'"},
        status=404,
    )

    # Next we'll search mozilla-beta, we'll find parent_rev but it's not a push head.
    ctx["branch"] = "mozilla-beta"
    changesets = create_changesets(4, {"phase": "public"})
    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"changesets": changesets},
        status=200,
    )

    # Finally we'll search mozilla-release, we find it and it's the push head!
    ctx["branch"] = "mozilla-release"
    changesets = create_changesets(2, {"phase": "public"}, head=3)
    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"changesets": changesets},
        status=200,
    )

    # Now run it and assert.
    push = Push(head, branch="try")
    parent = push.parent
    assert parent.rev == parent_rev
    assert parent.branch == "mozilla-release"


def test_push_parent_on_try_fails_with_merge_commit(responses, create_changesets):
    ctx = {
        "branch": "try",
        "rev": "a" * 40,
    }

    # Finding parent fails on merge commits.
    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"changesets": create_changesets(1, {"parents": ["b" * 40, "c" * 40]})},
        status=200,
    )

    push = Push(ctx["rev"], ctx["branch"])
    with pytest.raises(ParentPushNotFound):
        push.parent


def test_push_parent_on_try_fails_when_not_a_push_head(responses, create_changesets):
    changesets = create_changesets(3)
    head = changesets[-1]["node"]
    ctx = {
        "branch": "try",
        "rev": head,
    }
    responses.add(
        responses.GET,
        HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"changesets": changesets},
        status=200,
    )

    # We raise if rev is not found or a push head anywhere.
    ctx["rev"] = changesets[0]["parents"][0]
    for branch in (
        "mozilla-central",
        "mozilla-beta",
        "mozilla-release",
        "integration/autoland",
    ):
        ctx["branch"] = branch
        responses.add(
            responses.GET,
            HGMO.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
            json={"changesets": changesets},
            status=200,
        )

    push = Push(head, branch="try")
    with pytest.raises(ParentPushNotFound):
        push.parent


def test_push_child_raises(responses):
    rev = "a" * 40

    # Try and mozilla-unified are not supported.
    for branch in ("try", "mozilla-unified"):
        push = Push(rev, branch=branch)
        with pytest.raises(ChildPushNotFound):
            push.child

    # A push with no children raises.
    push = Push(rev, branch="integration/autoland")
    push._id = 100
    url = HGMO.JSON_PUSHES_TEMPLATE.format(
        branch=push.branch, push_id_start=push.id, push_id_end=push.id + 1,
    )
    responses.add(
        responses.GET, url, json={"lastpushid": push.id, "pushes": {}}, status=200,
    )

    with pytest.raises(ChildPushNotFound):
        push.child
