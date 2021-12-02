# -*- coding: utf-8 -*-

from itertools import count

import pytest

from mozci import config
from mozci.data.sources import bugbug
from mozci.errors import (
    ChildPushNotFound,
    ParentPushNotFound,
    PushNotFound,
    SourcesNotFound,
)
from mozci.push import Push, PushStatus, Regressions
from mozci.task import GroupResult, GroupSummary, Task, TestTask
from mozci.util.hgmo import HgRev
from mozci.util.taskcluster import (
    PRODUCTION_TASKCLUSTER_ROOT_URL,
    get_artifact_url,
    get_index_url,
)

SCHEDULES_EXTRACT = {
    "tasks": {
        "test-android-em-7.0-x86_64-lite-qr/debug-geckoview-junit-fis-e10s": 0.51,
        "test-linux1804-64-qr/opt-telemetry-tests-client-fis-e10s": 0.52,
    },
    "groups": {
        "toolkit/modules/tests/browser/browser.ini": 0.68,
        "devtools/client/framework/test/browser.ini": 0.99,
    },
    "config_groups": {
        "toolkit/modules/tests/browser/browser.ini": [
            "test-linux1804-64-qr/opt-*-swr-e10s"
        ],
        "devtools/client/framework/test/browser.ini": [
            "test-linux1804-64-qr/opt-*-e10s"
        ],
    },
    "reduced_tasks": {
        "test-android-em-7.0-x86_64-lite-qr/opt-geckoview-junit-fis-e10s": 0.88,
        "test-linux1804-64-qr/debug-reftest-swr-e10s-2": 0.83,
    },
    "reduced_tasks_higher": {},
    "known_tasks": [
        "test-windows10-64-2004-qr/debug-web-platform-tests-swr-e10s-9",
        "test-windows10-64-2004-qr/debug-mochitest-devtools-chrome-fis-e10s-1",
    ],
}

GROUP_SUMMARIES_DEFAULT = {
    group.name: group
    for group in [
        GroupSummary(
            f"group{i}",
            [
                Task.create(
                    id=j,
                    label=f"test-task{j}",
                    result="failed",
                    _results=[GroupResult(group=f"group{i}", ok=False)],
                )
                for j in range(1, 4)
            ],
        )
        for i in range(1, 6)
    ]
}


def make_tasks(group_id):
    return [
        TestTask(
            id=j,
            label=f"test-task{j}",
            result="failed",
            _results=[GroupResult(group=group_id, ok=False)],
        )
        for j in range(1, 4)
    ]


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


def test_push_tasks_with_tier(responses):
    cache = config.cache
    rev = "abcdef"
    branch = "autoland"

    TASKS_KEY = "{}/{}/tasks".format(branch, rev)

    # Making sure there's nothing left in the cache
    if cache.get(TASKS_KEY):
        cache.forget(TASKS_KEY)
    assert cache.get(TASKS_KEY) is None

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={"changesets": [{"node": rev, "pushdate": [1638349140]}]},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.v2.autoland.revision.abcdef.taskgraph.decision",
        json={"taskId": 1},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/1",
        json={"taskGroupId": "xyz789"},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task-group/xyz789/list",
        json={
            "tasks": [
                {
                    "task": {
                        "extra": {
                            "treeherder": {"tier": 3},
                        },
                        "metadata": {
                            "name": "task-A",
                        },
                        "tags": {"name": "tag-A"},
                    },
                    "status": {
                        "taskId": "abc13",
                        "state": "unscheduled",
                    },
                },
                {
                    "task": {
                        "extra": {
                            "treeherder": {"tier": 1},
                        },
                        "metadata": {
                            "name": "task-B",
                        },
                        "tags": {"name": "tag-A"},
                    },
                    "status": {
                        "taskId": "abc123",
                        "state": "unscheduled",
                    },
                },
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "https://treeherder.mozilla.org/api/project/autoland/note/push_notes/?revision=abcdef&format=json",
        json={},
        status=200,
    )

    push = Push(rev, branch)
    tasks = push.tasks
    print(len(tasks))
    assert len(tasks) == 1


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


def test_iterate_children(responses):
    rev = "a" * 40
    branch = "integration/autoland"
    push = Push(rev, branch)

    push_id = 10
    depth = 5

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/{branch}/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"pushid": push_id},
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/{branch}/json-pushes?version=2&startID={push_id}&endID={push_id+depth+1}",
        json={
            "pushes": {
                push_id + i: {"changesets": [chr(ord("a") + i) * 40], "date": 1}
                for i in range(1, depth + 2)
            }
        },
        status=200,
    )

    for other in push._iterate_children(depth):
        assert other.id == push_id
        push_id += 1


def test_iterate_parents(responses):
    rev = "a" * 40
    branch = "integration/autoland"
    push = Push(rev, branch)

    push_id = 10
    depth = 5

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/{branch}/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"pushid": push_id},
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/{branch}/json-pushes?version=2&startID={push_id-2-depth}&endID={push_id-1}",
        json={
            "pushes": {
                push_id - i: {"changesets": [chr(ord("a") + i) * 40], "date": 1}
                for i in range(1, depth + 2)
            }
        },
        status=200,
    )

    for other in push._iterate_parents(depth):
        assert other.id == push_id
        push_id -= 1


def test_get_test_selection_data_from_cache(responses):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(responses.GET, task_url, status=200, json={"taskId": "a" * 10})

    cache_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/queue/v1/task/aaaaaaaaaa/artifacts/public/bugbug-push-schedules.json"
    responses.add(responses.GET, cache_url, status=200, json=SCHEDULES_EXTRACT)

    data = push.get_test_selection_data()
    assert data == SCHEDULES_EXTRACT

    assert len(responses.calls) == 2
    assert [(call.request.method, call.request.url) for call in responses.calls] == [
        ("GET", task_url),
        ("GET", cache_url),
    ]


def test_get_test_selection_data_from_bugbug_handle_errors(responses, monkeypatch):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(responses.GET, task_url, status=200, json={"taskId": "a" * 10})

    cache_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/queue/v1/task/aaaaaaaaaa/artifacts/public/bugbug-push-schedules.json"
    responses.add(responses.GET, cache_url, status=404)

    url = f"{bugbug.BUGBUG_BASE_URL}/push/{branch}/{rev}/schedules"
    responses.add(responses.GET, url, status=500)

    monkeypatch.setattr(bugbug, "DEFAULT_RETRY_TIMEOUT", 3)
    monkeypatch.setattr(bugbug, "DEFAULT_RETRY_INTERVAL", 1)
    with pytest.raises(SourcesNotFound) as e:
        push.get_test_selection_data()
    assert (
        e.value.msg
        == "No registered sources were able to fulfill 'push_test_selection_data'!"
    )

    assert len(responses.calls) == 5
    assert [(call.request.method, call.request.url) for call in responses.calls] == [
        ("GET", task_url),
        ("GET", cache_url),
        # We retry 3 times the call to the Bugbug HTTP service
        ("GET", url),
        ("GET", url),
        ("GET", url),
    ]


def test_get_test_selection_data_from_bugbug_handle_exceeded_timeout(
    responses, monkeypatch
):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(responses.GET, task_url, status=200, json={"taskId": "a" * 10})

    cache_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/queue/v1/task/aaaaaaaaaa/artifacts/public/bugbug-push-schedules.json"
    responses.add(responses.GET, cache_url, status=404)

    url = f"{bugbug.BUGBUG_BASE_URL}/push/{branch}/{rev}/schedules"
    responses.add(responses.GET, url, status=202)

    monkeypatch.setattr(bugbug, "DEFAULT_RETRY_TIMEOUT", 3)
    monkeypatch.setattr(bugbug, "DEFAULT_RETRY_INTERVAL", 1)
    with pytest.raises(bugbug.BugbugTimeoutException) as e:
        push.get_test_selection_data()
    assert str(e.value) == "Timed out waiting for result from Bugbug HTTP Service"

    assert len(responses.calls) == 5
    assert [(call.request.method, call.request.url) for call in responses.calls] == [
        ("GET", task_url),
        ("GET", cache_url),
        # We retry 3 times the call to the Bugbug HTTP service
        ("GET", url),
        ("GET", url),
        ("GET", url),
    ]


def test_get_test_selection_data_from_bugbug(responses):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    task_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/index/v1/task/gecko.v2.{branch}.revision.{rev}.taskgraph.decision"
    responses.add(responses.GET, task_url, status=200, json={"taskId": "a" * 10})

    cache_url = f"{PRODUCTION_TASKCLUSTER_ROOT_URL}/api/queue/v1/task/aaaaaaaaaa/artifacts/public/bugbug-push-schedules.json"
    responses.add(responses.GET, cache_url, status=404)

    url = f"{bugbug.BUGBUG_BASE_URL}/push/{branch}/{rev}/schedules"
    responses.add(responses.GET, url, status=200, json=SCHEDULES_EXTRACT)

    data = push.get_test_selection_data()
    assert data == SCHEDULES_EXTRACT

    assert len(responses.calls) == 3
    assert [(call.request.method, call.request.url) for call in responses.calls] == [
        ("GET", task_url),
        ("GET", cache_url),
        ("GET", url),
    ]


@pytest.mark.parametrize(
    "classify_regressions_return_value, expected_result",
    [
        (Regressions(real={"group1": []}, intermittent={}, unknown={}), PushStatus.BAD),
        (
            Regressions(real={"group1": []}, intermittent={"group2": []}, unknown={}),
            PushStatus.BAD,
        ),
        (
            Regressions(real={"group1": []}, intermittent={}, unknown={"group2": []}),
            PushStatus.BAD,
        ),
        (Regressions(real={}, intermittent={}, unknown={}), PushStatus.GOOD),
        (
            Regressions(real={}, intermittent={"group1": []}, unknown={}),
            PushStatus.GOOD,
        ),
        (
            Regressions(real={}, intermittent={"group1": [], "group2": []}, unknown={}),
            PushStatus.GOOD,
        ),
        (
            Regressions(real={}, intermittent={}, unknown={"group1": []}),
            PushStatus.UNKNOWN,
        ),
        (
            Regressions(real={}, intermittent={"group1": []}, unknown={"group2": []}),
            PushStatus.UNKNOWN,
        ),
    ],
)
def test_classify(monkeypatch, classify_regressions_return_value, expected_result):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    def mock_return(self, *args, **kwargs):
        return classify_regressions_return_value

    monkeypatch.setattr(Push, "classify_regressions", mock_return)
    assert push.classify()[0] == expected_result


def generate_mocks(
    monkeypatch,
    push,
    get_test_selection_data_value,
    get_likely_regressions_value,
    cross_config_values,
):
    monkeypatch.setattr(config.cache, "get", lambda x: None)

    def mock_return_get_test_selection_data(*args, **kwargs):
        return get_test_selection_data_value

    monkeypatch.setattr(
        Push, "get_test_selection_data", mock_return_get_test_selection_data
    )

    def mock_return_get_likely_regressions(*args, **kwargs):
        return get_likely_regressions_value

    monkeypatch.setattr(
        Push, "get_likely_regressions", mock_return_get_likely_regressions
    )

    push.group_summaries = GROUP_SUMMARIES_DEFAULT
    for index, group in enumerate(push.group_summaries.values()):
        group.is_cross_config_failure = cross_config_values[index]


@pytest.mark.parametrize(
    "test_selection_data, are_cross_config",
    [
        (
            {"groups": {"group1": 0.7, "group2": 0.3}},
            [True for i in range(0, len(GROUP_SUMMARIES_DEFAULT))],
        ),  # There are only cross-config failures with low confidence
        (
            {
                "groups": {
                    "group1": 0.85,
                    "group2": 0.85,
                    "group3": 0.85,
                    "group4": 0.85,
                    "group5": 0.85,
                }
            },
            [False for i in range(0, len(GROUP_SUMMARIES_DEFAULT))],
        ),  # There are only non cross-config failures with medium confidence
        (
            {
                "groups": {
                    "group1": 0.7,
                    "group2": 0.85,
                    "group3": 0.3,
                    "group4": 0.85,
                    "group5": 0.3,
                }
            },
            [False if i % 2 else True for i in range(0, len(GROUP_SUMMARIES_DEFAULT))],
        ),  # There are some non cross-config failures and some low confidence groups but they don't match
    ],
)
def test_classify_almost_good_push(monkeypatch, test_selection_data, are_cross_config):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)
    generate_mocks(
        monkeypatch,
        push,
        test_selection_data,
        set(),
        are_cross_config,
    )

    assert push.classify() == (
        PushStatus.UNKNOWN,
        Regressions(
            real={},
            intermittent={},
            unknown={
                "group1": make_tasks("group1"),
                "group2": make_tasks("group2"),
                "group3": make_tasks("group3"),
                "group4": make_tasks("group4"),
                "group5": make_tasks("group5"),
            },
        ),
    )


def test_classify_good_push_only_intermittent_failures(monkeypatch):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    test_selection_data = {"groups": {"group1": 0.7, "group2": 0.3}}
    likely_regressions = {"group3", "group4"}
    are_cross_config = [False for i in range(0, len(GROUP_SUMMARIES_DEFAULT))]
    generate_mocks(
        monkeypatch,
        push,
        test_selection_data,
        likely_regressions,
        are_cross_config,
    )

    assert push.classify() == (
        PushStatus.GOOD,
        Regressions(
            real={},
            # All groups aren't cross config failures and were either selected by bugbug
            # with low confidence or not at all (no confidence)
            intermittent={
                "group1": make_tasks("group1"),
                "group2": make_tasks("group2"),
                "group3": make_tasks("group3"),
                "group4": make_tasks("group4"),
                "group5": make_tasks("group5"),
            },
            unknown={},
        ),
    )


@pytest.mark.parametrize(
    "test_selection_data, likely_regressions, are_cross_config",
    [
        (
            {"groups": {}},
            {"group1", "group2", "group3", "group4", "group5"},
            [True for i in range(0, len(GROUP_SUMMARIES_DEFAULT))],
        ),  # There are only cross-config failures likely to regress
        # but they weren't selected by bugbug (no confidence)
        (
            {
                "groups": {
                    "group1": 0.92,
                    "group2": 0.92,
                    "group3": 0.92,
                    "group4": 0.92,
                    "group5": 0.92,
                }
            },
            set(),
            [True for i in range(0, len(GROUP_SUMMARIES_DEFAULT))],
        ),  # There are only cross-config failures that were selected
        # with high confidence by bugbug but weren't likely to regress
        (
            {
                "groups": {
                    "group1": 0.92,
                    "group2": 0.92,
                    "group3": 0.92,
                    "group4": 0.92,
                    "group5": 0.92,
                }
            },
            {"group1", "group2", "group3", "group4", "group5"},
            [False for i in range(0, len(GROUP_SUMMARIES_DEFAULT))],
        ),  # There are only groups that were selected with high confidence by
        # bugbug and also likely to regress but they aren't cross-config failures
    ],
)
def test_classify_almost_bad_push(
    monkeypatch, test_selection_data, likely_regressions, are_cross_config
):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)
    generate_mocks(
        monkeypatch,
        push,
        test_selection_data,
        likely_regressions,
        are_cross_config,
    )

    assert push.classify() == (
        PushStatus.UNKNOWN,
        Regressions(
            real={},
            intermittent={},
            unknown={
                "group1": make_tasks("group1"),
                "group2": make_tasks("group2"),
                "group3": make_tasks("group3"),
                "group4": make_tasks("group4"),
                "group5": make_tasks("group5"),
            },
        ),
    )


def test_classify_bad_push_some_real_failures(monkeypatch):
    rev = "a" * 40
    branch = "autoland"
    push = Push(rev, branch)

    test_selection_data = {"groups": {"group1": 0.99, "group2": 0.95, "group3": 0.91}}
    likely_regressions = {"group1", "group2", "group3"}
    are_cross_config = [
        False if i % 2 else True for i in range(0, len(GROUP_SUMMARIES_DEFAULT))
    ]
    generate_mocks(
        monkeypatch,
        push,
        test_selection_data,
        likely_regressions,
        are_cross_config,
    )

    assert push.classify() == (
        PushStatus.BAD,
        Regressions(
            # group1 & group3 were both selected by bugbug with high confidence, likely to regress
            # and are cross config failures
            real={"group1": make_tasks("group1"), "group3": make_tasks("group3")},
            # group4 isn't a cross config failure and was not selected by bugbug (no confidence)
            intermittent={"group4": make_tasks("group4")},
            # group2 isn't a cross config failure but was selected with high confidence by bugbug
            # group5 is a cross config failure but was not selected by bugbug nor likely to regress
            unknown={"group2": make_tasks("group2"), "group5": make_tasks("group5")},
        ),
    )
