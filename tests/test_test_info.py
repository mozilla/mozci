# -*- coding: utf-8 -*-
from mozci import data
from mozci.data.sources.treeherder import TreeherderClientSource
from mozci.push import Push  # noqa: F401 (import order, see mozci.util.test_info)
from mozci.attribution import is_failure_line_about_group, normalize_failure_line
from mozci.task import GroupResult, Task
from mozci.util.test_info import is_flaky_group, job_type, normalize_group, summarize


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
        "dom/tests/mochitest.toml": {
            "test-linux/opt-mochitest": (6, 96),
            "test-windows/opt-mochitest": (1, 4),
        },
        "testing/web-platform/tests/css/css-grid": {
            "test-linux/opt-mochitest": (0, 10)
        },
    }


def test_normalize_group():
    assert normalize_group("/css/css-grid") == "testing/web-platform/tests/css/css-grid"
    assert (
        normalize_group("/_mozilla/webgpu/cts")
        == "testing/web-platform/mozilla/tests/webgpu/cts"
    )
    assert normalize_group("dom/tests/mochitest.toml") == "dom/tests/mochitest.toml"


def test_job_type():
    assert job_type("test-linux/opt-mochitest-browser-chrome-3") == (
        "test-linux/opt-mochitest-browser-chrome"
    )
    assert job_type("test-linux/opt-web-platform-tests") == (
        "test-linux/opt-web-platform-tests"
    )


def test_is_flaky_group():
    stats = {
        "flaky.toml": {"linux": (30, 2000), "windows": (0, 2000)},
        "stable.toml": {"linux": (0, 100)},
        "busy.toml": {"linux": (20, 10000)},
    }
    assert is_flaky_group(stats, "flaky.toml", "linux")
    assert not is_flaky_group(stats, "flaky.toml", "windows")  # flaky on linux only
    assert not is_flaky_group(stats, "flaky.toml", "mac")
    assert not is_flaky_group(stats, "stable.toml", "linux")
    assert not is_flaky_group(stats, "busy.toml", "linux")  # rate too low
    assert not is_flaky_group(stats, "unknown.toml", "linux")
    assert not is_flaky_group(None, "flaky.toml", "linux")


def test_normalize_failure_line():
    assert normalize_failure_line(
        "FATAL ERROR: connection to merino.services.mozilla.com (2a04:4e42::347)"
    ) == normalize_failure_line(
        "FATAL ERROR: connection to merino.services.mozilla.com (151.101.1.91)"
    )
    assert normalize_failure_line("test_foo.html | timed out after 370 seconds") == (
        "test_foo.html | timed out after <n> seconds"
    )


def test_is_failure_line_about_group():
    line = "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | oops"
    assert is_failure_line_about_group(line, "dom/tests/mochitest.toml")
    assert not is_failure_line_about_group(line, "dom/base/mochitest.toml")
    wpt = "TEST-UNEXPECTED-FAIL | /css/css-grid/a.html | oops"
    assert is_failure_line_about_group(wpt, "testing/web-platform/tests/css/css-grid")
    assert not is_failure_line_about_group(
        wpt, "testing/web-platform/tests/css/css-flexbox"
    )
    mozilla = "TEST-UNEXPECTED-FAIL | /_mozilla/css/foo.html | oops"
    assert is_failure_line_about_group(
        mozilla, "testing/web-platform/mozilla/tests/css"
    )
    assert not is_failure_line_about_group(mozilla, "testing/web-platform/tests/css")
    # Lines which don't name a test.
    assert is_failure_line_about_group("FATAL ERROR: oops", "dom/base/mochitest.toml")


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
    p[4].attribution._group_failure_stats = {
        "dom/tests/mochitest.toml": {"test-linux/opt-mochitest": (0, 2000)}
    }
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}

    p[4].__dict__.pop("_get_regressions", None)
    p[4].attribution._group_failure_stats = {
        "dom/tests/mochitest.toml": {
            "test-linux/opt-mochitest": (50, 2000),
            "test-windows/opt-mochitest": (0, 2000),
        }
    }

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

    # The group is flaky on another platform only: the classification is trusted.
    flaky_stats = p[4].attribution._group_failure_stats
    p[4].attribution._group_failure_stats = {
        "dom/tests/mochitest.toml": {
            "test-linux/opt-mochitest": (0, 2000),
            "test-windows/opt-mochitest": (50, 2000),
        }
    }
    p[4].__dict__.pop("_get_regressions", None)
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}
    p[4].attribution._group_failure_stats = flaky_stats

    # A failure line which matches no bug (only an internal Treeherder issue) and
    # also appears in another task of the push: the classification is trusted.
    fatal = {
        "search": "FATAL ERROR: Non-local network connections are disabled and a "
        "connection attempt to example.com (151.101.1.91) was made.",
        "failure_new_in_rev": False,
        "bugs": {"open_recent": [{"id": None}], "all_others": []},
    }
    other_fatal = {
        **fatal,
        "search": fatal["search"].replace("151.101.1.91", "10.0.0.1"),
    }
    tasks_by_job = {}

    def get_job_from_task(self, task):
        tasks_by_job[task.id] = task
        return {"id": task.id}

    monkeypatch.setattr(TreeherderClientSource, "get_job_from_task", get_job_from_task)
    monkeypatch.setattr(
        TreeherderClientSource,
        "get_bug_suggestions",
        lambda self, job_id, branch="autoland": (
            [suggestions[0], fatal] if job_id == "1" * 22 else [other_fatal]
        ),
    )
    other = task(3, False, "fixed by commit")
    other._results = [
        GroupResult(group="dom/base/mochitest.toml", ok=False, duration=1)
    ]
    p[4].tasks.append(other)
    for attr in ("_get_regressions", "_failure_lines"):
        p[4].__dict__.pop(attr, None)
        p[4].attribution.__dict__.pop(attr, None)
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}
    # It doesn't appear elsewhere: the failure is considered intermittent.
    p[4].tasks.remove(other)
    for attr in ("_get_regressions", "_failure_lines"):
        p[4].__dict__.pop(attr, None)
        p[4].attribution.__dict__.pop(attr, None)
    assert p[4].get_regressions("group") == {}
    monkeypatch.setattr(
        TreeherderClientSource, "get_job_from_task", lambda self, task: {"id": 1}
    )
    monkeypatch.setattr(
        TreeherderClientSource,
        "get_bug_suggestions",
        lambda self, job_id, branch="autoland": suggestions,
    )
    p[4].attribution.__dict__.pop("_failure_lines", None)

    # A new failure, matching no known bug: the classification is trusted.
    suggestions[0] = {
        "search": "Assertion failure: aStart <= len, at Span.h:691",
        "failure_new_in_rev": True,
        "bugs": {"open_recent": [], "all_others": []},
    }
    for attr in ("_get_regressions", "_failure_lines"):
        p[4].__dict__.pop(attr, None)
        p[4].attribution.__dict__.pop(attr, None)
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
    for attr in ("_get_regressions", "_failure_lines"):
        p[4].__dict__.pop(attr, None)
        p[4].attribution.__dict__.pop(attr, None)
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
    p[4].attribution.__dict__.pop("_failure_lines", None)

    # If the group kept failing on the following pushes until the backout, the
    # classification is trusted.
    p[5].tasks = [task(2, False, "fixed by commit")]
    p[5].tasks[0].classification_note = p[6].rev
    for push in p[4:6]:
        for attr in (
            "_get_regressions",
            "_failures_until_backout",
            "_bustage_fixed_by",
            "_group_summaries",
        ):
            push.__dict__.pop(attr, None)
            push.attribution.__dict__.pop(attr, None)
    assert p[4].get_regressions("group") == {"dom/tests/mochitest.toml": 0}
