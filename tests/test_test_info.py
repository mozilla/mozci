# -*- coding: utf-8 -*-
from mozci import data
from mozci.data.sources.treeherder import TreeherderClientSource
from mozci.push import Push  # noqa: F401 (import order, see mozci.util.test_info)
from mozci.task import GroupResult, Task
from mozci.util.test_info import is_flaky_group, normalize_group, summarize


def test_summarize():
    report = {
        "2026-09-01": {
            "job_type_names": [
                "test-linux/opt-mochitest",
                "test-windows/opt-mochitest",
            ],
            "manifests": [
                {
                    "dom/tests/mochitest.toml": [
                        [0, "passed", 1, 90],
                        [0, "testfailed", 4, 6],
                        [1, "testfailed", 2, 3],
                        [1, "testfailed", 7, 1],
                    ]
                },
                {"/css/css-grid": [[0, "passed", 1, 10]]},
            ],
        },
        "2026-09-02": {"code": "ResourceNotFound"},
    }
    assert summarize(report) == {
        # Only intermittent classifications (4, 7, 8) count as intermittent failures.
        "dom/tests/mochitest.toml": (7, 100),
        "testing/web-platform/tests/css/css-grid": (0, 10),
    }


def test_normalize_group():
    assert normalize_group("/css/css-grid") == "testing/web-platform/tests/css/css-grid"
    assert (
        normalize_group("/_mozilla/webgpu/cts")
        == "testing/web-platform/mozilla/tests/webgpu/cts"
    )
    assert normalize_group("dom/tests/mochitest.toml") == "dom/tests/mochitest.toml"


def test_is_flaky_group():
    stats = {
        "flaky.toml": (30, 2000),
        "stable.toml": (0, 100),
        "busy.toml": (20, 10000),
    }
    assert is_flaky_group(stats, "flaky.toml")
    assert not is_flaky_group(stats, "stable.toml")
    assert not is_flaky_group(stats, "busy.toml")  # rate too low
    assert not is_flaky_group(stats, "unknown.toml")
    assert not is_flaky_group(None, "flaky.toml")


def test_fixed_by_commit_on_flaky_group_is_intermittent(create_pushes, monkeypatch):
    def task(i, ok, classification="not classified"):
        t = Task.create(
            id=str(i) * 22,
            label="test-linux/opt-mochitest-1",
            result="passed" if ok else "failed",
            classification=classification,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group="dom/tests/mochitest.toml", ok=ok, duration=1)]
        return t

    p = create_pushes(8)
    for j in range(0, 4):
        p[j].tasks = [task(1, True)]
    p[4].tasks = [task(1, False, "fixed by commit")]
    p[4].tasks[0].classification_note = p[6].rev
    for j in range(5, 8):
        p[j].tasks = [task(1, True)]
    p[4].backedoutby = p[6].rev

    # The group isn't flaky: the classification is trusted.
    p[4]._group_failure_stats = {"dom/tests/mochitest.toml": (0, 2000)}
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}

    p[4].__dict__.pop("_get_regressions", None)
    p[4]._group_failure_stats = {"dom/tests/mochitest.toml": (50, 2000)}

    # The failure matches a known intermittent bug: considered intermittent.
    suggestions = [
        {
            "search": "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | timed out",
            "failure_new_in_rev": False,
            "bugs": {"open_recent": [{"summary": "Intermittent test_foo.html"}]},
        },
        {
            "search": "PROCESS-CRASH | 1234-5678 | application crashed",
            "failure_new_in_rev": True,
            "bugs": {"open_recent": [], "all_others": []},
        },
    ]
    monkeypatch.setattr(
        TreeherderClientSource, "get_job_from_task", lambda self, task: {"id": 1}
    )
    monkeypatch.setattr(
        TreeherderClientSource,
        "get_bug_suggestions",
        lambda self, job_id, branch="autoland": suggestions,
    )
    assert p[4].get_regressions("group") == {}

    # A new failure, matching no known bug: the classification is trusted.
    suggestions[0] = {
        "search": "Assertion failure: aStart <= len, at Span.h:691",
        "failure_new_in_rev": True,
        "bugs": {"open_recent": [], "all_others": []},
    }
    for attr in ("_get_regressions", "_bug_suggestions_cache"):
        p[4].__dict__.pop(attr, None)
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}

    # Treeherder has no failure lines (e.g. the log was too large to be parsed): the
    # errorsummaries are used, the classification is trusted if the group crashed with
    # a signature which also crashed another test on the push.
    saved = suggestions[:]
    suggestions.clear()
    signature = "@ mozilla::FFVPXRuntimeLinker::GetFFTFuncs"
    failing = p[4].tasks[0]
    failing._crashes = {
        "dom/tests/mochitest.toml": [("dom/tests/test_foo.html", signature)]
    }
    other = task(3, False, "fixed by commit")
    other._results = []
    other._crashes = {
        "dom/media/test/mochitest.toml": [("dom/media/test/test_bar.html", "[Unknown]")]
    }
    p[4].tasks.append(other)
    for attr in ("_get_regressions", "_bug_suggestions_cache"):
        p[4].__dict__.pop(attr, None)
    assert p[4].get_regressions("group") == {}
    # Unknown signatures don't tell crashes apart.
    failing._crashes = {
        "dom/tests/mochitest.toml": [("dom/tests/test_foo.html", "[Unknown]")]
    }
    p[4].__dict__.pop("_get_regressions", None)
    assert p[4].get_regressions("group") == {}
    failing._crashes = {
        "dom/tests/mochitest.toml": [("dom/tests/test_foo.html", signature)]
    }
    other._crashes = {
        "dom/media/test/mochitest.toml": [("dom/media/test/test_bar.html", signature)]
    }
    p[4].__dict__.pop("_get_regressions", None)
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}
    p[4].tasks.remove(other)

    # It can't be checked: the classification is trusted.
    def unavailable(*args, **kwargs):
        raise Exception("unavailable")

    failing._crashes = None
    with monkeypatch.context() as m:
        m.setattr(data.handler, "get", unavailable)
        p[4].__dict__.pop("_get_regressions", None)
        assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}
    suggestions.extend(saved)
    suggestions[0]["failure_new_in_rev"] = False
    p[4].__dict__.pop("_bug_suggestions_cache", None)

    # If the group kept failing on the following pushes until the backout, the
    # classification is trusted.
    p[5].tasks = [task(2, False, "fixed by commit")]
    p[5].tasks[0].classification_note = p[6].rev
    for push in p[4:6]:
        for attr in (
            "_get_regressions",
            "_failures_until_backout_cache",
            "_bustage_fixed_by",
            "_group_summaries",
        ):
            push.__dict__.pop(attr, None)
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}
