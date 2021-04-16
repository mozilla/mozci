# -*- coding: utf-8 -*-

from itertools import count

import pytest

from mozci.errors import ChildPushNotFound, ParentPushNotFound, PushNotFound
from mozci.push import Push
from mozci.util.hgmo import HgRev
from mozci.util.taskcluster import get_artifact_url, get_index_url


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
    def setup_responses(ctx):
        responses.reset()
        responses.add(
            responses.GET,
            HgRev.JSON_PUSHES_TEMPLATE.format(**ctx),
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
            HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(
                branch=ctx["branch"], rev="abcdef"
            ),
            json={"changesets": [{"node": "abcdef"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(
                branch=ctx["branch"], rev="123456"
            ),
            json={"changesets": [{"node": "123456"}]},
            status=200,
        )

    ctx = {
        "branch": "integration/autoland",
        "push_id_start": "122",
        "push_id_end": "123",
    }
    setup_responses(ctx)
    p1 = Push("abcdef")
    p2 = p1.create_push(123)
    assert p2.rev == "123456"
    assert p2.id == 123
    assert p2.date == 1213174092
    assert p2.branch in ctx["branch"]

    ctx["branch"] = "mozilla-central"
    setup_responses(ctx)
    p1 = Push("abcdef", branch=ctx["branch"])
    p2 = p1.create_push(123)
    assert p2.rev == "123456"
    assert p2.id == 123
    assert p2.date == 1213174092
    assert p2.branch in ctx["branch"]


def test_push_does_not_exist(responses):
    # We hit hgmo when 'rev' is less than 40 characters.
    rev = "foobar"
    responses.add(
        responses.GET,
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(
            branch="integration/autoland", rev="foobar"
        ),
        json={"error": f"unknown revision '{rev}'"},
        status=404,
    )

    with pytest.raises(PushNotFound):
        Push(rev)

    # Otherwise we need to hit hgmo some other way.
    rev = "a" * 40
    responses.add(
        responses.GET,
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(
            branch="integration/autoland", rev=rev
        ),
        json={"error": f"unknown revision '{rev}'"},
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
        HgRev.JSON_PUSHES_TEMPLATE.format(**ctx),
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
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
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
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"error": f"unknown revision '{parent_rev}'"},
        status=404,
    )

    # Next we'll search mozilla-beta, we'll find parent_rev but it's not a push head.
    ctx["branch"] = "mozilla-beta"
    changesets = create_changesets(4, {"phase": "public"})
    responses.add(
        responses.GET,
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
        json={"changesets": changesets},
        status=200,
    )

    # Finally we'll search mozilla-release, we find it and it's the push head!
    ctx["branch"] = "mozilla-release"
    changesets = create_changesets(2, {"phase": "public"}, head=3)
    responses.add(
        responses.GET,
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
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
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
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
        HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
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
            HgRev.AUTOMATION_RELEVANCE_TEMPLATE.format(**ctx),
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
    url = HgRev.JSON_PUSHES_TEMPLATE.format(
        branch=push.branch,
        push_id_start=push.id,
        push_id_end=push.id + 1,
    )
    responses.add(
        responses.GET,
        url,
        json={"lastpushid": push.id, "pushes": {}},
        status=200,
    )

    with pytest.raises(ChildPushNotFound):
        push.child


def test_generate_all_shadow_scheduler_tasks(responses):
    rev = "a" * 40
    shadow_schedulers = (
        (
            "bar",
            ["task-1", "task-3", "task-4"],
        ),  # names will be generated alphabetically
        ("foo", ["task-2", "task-4"]),
    )

    push = Push(rev)
    responses.add(
        responses.GET,
        get_index_url(push.index + ".taskgraph.decision"),
        json={"taskId": 1},
        status=200,
    )

    id = count(2)
    responses.add(
        responses.GET,
        get_artifact_url(1, "public/task-graph.json"),
        json={
            next(id): {"label": f"source-test-shadow-scheduler-{s[0]}"}
            for s in shadow_schedulers
        },
        status=200,
    )

    id = count(2)
    for ss in shadow_schedulers:
        s_id = next(id)
        responses.add(
            responses.GET,
            get_index_url(f"{push.index}.source.shadow-scheduler-{ss[0]}"),
            json={"taskId": s_id},
            status=200,
        )

        responses.add(
            responses.GET,
            get_artifact_url(s_id, "public/shadow-scheduler/optimized-tasks.json"),
            stream=True,
            json={next(id): {"label": task} for task in ss[1]},
            status=200,
        )

    # retrieve the data
    for i, (name, tasks) in enumerate(push.generate_all_shadow_scheduler_tasks()):
        print(i, name, tasks)
        assert name == shadow_schedulers[i][0]
        assert tasks == set(shadow_schedulers[i][1])


def test_generate_all_shadow_scheduler_config_groups(responses):
    rev = "a" * 40
    shadow_schedulers = (
        (
            "bar",
            [
                (
                    "test-linux1804-64/debug-xpcshell-spi-nw-e10s-1",
                    ["group1", "group5"],
                ),
                ("test-linux1804-64/debug-xpcshell-spi-nw-e10s-2", ["group2"]),
                ("test-windows7-32/opt-xpcshell-e10s-1", ["group3"]),
            ],
            {
                ("test-linux1804-64/debug-*-spi-nw-e10s", "group2"),
                ("test-linux1804-64/debug-*-spi-nw-e10s", "group5"),
                ("test-linux1804-64/debug-*-spi-nw-e10s", "group1"),
                ("test-windows7-32/opt-*-e10s", "group3"),
            },
        ),
        (
            "foo",
            [
                ("test-macosx1014-64/opt-xpcshell-e10s-1", ["group4"]),
                (
                    "test-android-em-7.0-x86_64/debug-geckoview-xpcshell-e10s-1",
                    ["group3"],
                ),
            ],
            {
                ("test-android-em-7.0-x86_64/debug-geckoview-*-e10s", "group3"),
                ("test-macosx1014-64/opt-*-e10s", "group4"),
            },
        ),
    )

    push = Push(rev)
    responses.add(
        responses.GET,
        get_index_url(push.index + ".taskgraph.decision"),
        json={"taskId": 1},
        status=200,
    )

    id = count(2)
    responses.add(
        responses.GET,
        get_artifact_url(1, "public/task-graph.json"),
        json={
            next(id): {"label": f"source-test-shadow-scheduler-{s[0]}"}
            for s in shadow_schedulers
        },
        status=200,
    )

    id = count(2)
    for ss in shadow_schedulers:
        s_id = next(id)
        responses.add(
            responses.GET,
            get_index_url(f"{push.index}.source.shadow-scheduler-{ss[0]}"),
            json={"taskId": s_id},
            status=200,
        )

        responses.add(
            responses.GET,
            get_artifact_url(s_id, "public/shadow-scheduler/optimized-tasks.json"),
            stream=True,
            json={
                next(id): {"label": label, "attributes": {"test_manifests": groups}}
                for label, groups in ss[1]
            },
            status=200,
        )

    # retrieve the data
    for i, (name, config_groups) in enumerate(
        push.generate_all_shadow_scheduler_config_groups()
    ):
        print(i, name, config_groups)
        assert name == shadow_schedulers[i][0]
        assert config_groups == shadow_schedulers[i][2]
