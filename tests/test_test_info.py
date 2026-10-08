# -*- coding: utf-8 -*-
from mozci import data
from mozci.data.sources.treeherder import TreeherderClientSource
from mozci.push import Push  # imported first, see mozci.util.test_info
from mozci.attribution import (
    AttributionAnalysis,
    is_failure_line_about_group,
    normalize_failure_line,
)
from mozci.task import GroupResult, Task
from mozci.util import test_info
from mozci.util.hgmo import HgRev
from mozci.util.test_info import (
    groups_of_file,
    is_flaky_group,
    job_type,
    normalize_group,
    summarize,
    summarize_tests,
)


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


def test_summarize_tests():
    report = {
        "tests": {
            "Core::DOM": [
                {
                    "manifest": ["dom/tests/mochitest.toml"],
                    "test": "dom/tests/test_a.html",
                }
            ],
            "Testing::web-platform-tests": [
                {
                    "manifest": ["/css/css-grid"],
                    "test": "testing/web-platform/tests/css/css-grid/a.html",
                }
            ],
        }
    }
    assert summarize_tests(report) == {
        "dom/tests/test_a.html": ["dom/tests/mochitest.toml"],
        "testing/web-platform/tests/css/css-grid/a.html": [
            "testing/web-platform/tests/css/css-grid"
        ],
    }


def test_groups_of_file():
    manifests = {"dom/tests/test_a.html": ["dom/tests/mochitest.toml"]}
    assert groups_of_file("dom/tests/test_a.html", manifests) == {
        "dom/tests/mochitest.toml"
    }
    assert groups_of_file("dom/tests/mochitest.toml", manifests) == {
        "dom/tests/mochitest.toml"
    }
    assert groups_of_file("dom/base/Element.cpp", manifests) == set()
    wpt = {
        "testing/web-platform/tests/css",
        "testing/web-platform/tests/css/css-grid",
    }
    assert groups_of_file("testing/web-platform/tests/css/css-grid/a.html", {}) == wpt
    # Expectations of WPT tests.
    assert (
        groups_of_file("testing/web-platform/meta/css/css-grid/a.html.ini", {}) == wpt
    )


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


def test_fixed_by_commit_fixed_elsewhere_in_reland_is_intermittent(
    create_pushes, monkeypatch
):
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

    p = create_pushes(9)
    for j in list(range(0, 4)) + list(range(5, 9)):
        p[j].tasks = [task(1, True)]
    p[4].tasks = [task(1, False, "fixed by commit")]
    p[4].tasks[0].classification_note = p[6].rev
    p[4].backedoutby = p[6].rev
    p[4]._bugs = {123}
    # The group isn't flaky.
    p[4].attribution._group_failure_stats = {
        "dom/tests/mochitest.toml": {"test-linux/opt-mochitest": (0, 2000)}
    }

    # The failure matches a known intermittent bug.
    monkeypatch.setattr(
        TreeherderClientSource, "get_job_from_task", lambda self, task: {"id": 1}
    )
    monkeypatch.setattr(
        TreeherderClientSource,
        "get_bug_suggestions",
        lambda self, job_id, branch="autoland": [
            {
                "search": "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | timed out",
                "failure_new_in_rev": False,
                "bugs": {"open_recent": [{"summary": "Intermittent test_foo.html"}]},
            }
        ],
    )
    monkeypatch.setattr(
        test_info,
        "manifests_of_tests",
        lambda date: {
            "dom/tests/test_foo.html": ["dom/tests/mochitest.toml"],
            "dom/base/test/test_bar.html": ["dom/base/test/mochitest.toml"],
        },
    )

    # Changesets as {node: file}.
    # json-pushes data of the push, its backout, and pushes after it (a push for
    # another bug, then the reland).
    backout_id = p[6].id
    monkeypatch.setattr(
        HgRev, "load_json_pushes_between_ids", staticmethod(lambda *args: None)
    )

    def set_json_pushes():
        def changesets(nodes, desc="Bug 123 - Change"):
            return [
                {"node": node, "desc": desc, "files": [path]}
                for node, path in nodes.items()
            ]

        cache = {
            p[4].id: changesets(original),
            backout_id: changesets({"r": "dom/base/Element.cpp"}, "Revert"),
            backout_id + 1: changesets({"x": "other/x.cpp"}, "Bug 456 - Other"),
        }
        if reland:
            cache[backout_id + 2] = changesets(reland)
        monkeypatch.setattr(
            HgRev,
            "JSON_PUSHES_CACHE",
            {push_id: {"changesets": c} for push_id, c in cache.items()},
        )

    def regressions():
        set_json_pushes()
        for attr in (
            "_get_regressions",
            "_reland_files",
            "_failure_lines",
        ):
            p[4].__dict__.pop(attr, None)
            p[4].attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("group")

    original = {"a": "dom/base/Element.cpp"}

    # Not relanded: the classification is trusted.
    reland = {}
    assert regressions() == {"dom/tests/mochitest.toml": 0}

    # Relanded with a fix to a test of another group: the failure is considered
    # intermittent.
    reland = {"b": "dom/base/Element.cpp", "c": "dom/base/test/test_bar.html"}
    assert regressions() == {}

    # The reland also fixed a test of the group: the classification is trusted.
    reland["d"] = "dom/tests/test_foo.html"
    assert regressions() == {"dom/tests/mochitest.toml": 0}

    # Relanded unchanged: the classification is trusted.
    reland = {"b": "dom/base/Element.cpp"}
    assert regressions() == {"dom/tests/mochitest.toml": 0}

    # The push and the reland modified a test of the group: it is considered
    # changed (the patches aren't compared), the classification is trusted.
    original = {"a": "dom/base/Element.cpp", "e": "dom/tests/test_foo.html"}
    reland = {
        "b": "dom/base/Element.cpp",
        "c": "dom/base/test/test_bar.html",
        "f": "dom/tests/test_foo.html",
    }
    assert regressions() == {"dom/tests/mochitest.toml": 0}

    # The push and the reland modified a test of another group (the patches aren't
    # compared), and the reland changed something else: the classification is
    # trusted.
    original = {"a": "dom/base/Element.cpp", "e": "dom/base/test/test_bar.html"}
    reland = {
        "b": "dom/base/Element.cpp",
        "c": "dom/base/Node.cpp",
        "f": "dom/base/test/test_bar.html",
    }
    assert regressions() == {"dom/tests/mochitest.toml": 0}


def test_backout_file_names_of_the_commits_backing_out_the_push(
    create_pushes, monkeypatch
):
    p = create_pushes(9)
    # p[8] backs out both p[4] and p[5], with a commit each.
    p[4].backedoutby = p[5].backedoutby = p[8].rev
    monkeypatch.setattr(
        HgRev,
        "JSON_PUSHES_CACHE",
        {
            p[8].id: {
                "changesets": [
                    {
                        "node": "a" * 40,
                        "desc": "Revert 'Bug 1' for causing failures at test_foo.html",
                    },
                    {
                        "node": "b" * 40,
                        "desc": "Revert 'Bug 2' for causing failures at test_bar.html",
                    },
                ]
            }
        },
    )

    def names(backouts):
        monkeypatch.setattr(HgRev, "backouts", property(lambda self: backouts))
        result = []
        for push in (p[4], p[5]):
            push.attribution.__dict__.pop("_backout_file_names", None)
            result.append(push.attribution.backout_file_names)
        return result

    # Each push only gets the names from the commit backing it out.
    assert names({"a" * 40: [p[4].rev], "b" * 40: [p[5].rev]}) == [
        {"test_foo.html"},
        {"test_bar.html"},
    ]

    # Which commits are backed out is unknown: all names are used.
    assert names({}) == [{"test_foo.html", "test_bar.html"}] * 2


def test_fixed_by_commit_after_passing_on_same_job_type_is_intermittent(
    create_pushes, monkeypatch
):
    def task(
        i, ok, label="test-linux/opt-mochitest-1", classification="not classified"
    ):
        t = Task.create(
            id=str(i) * 22,
            label=label,
            result="passed" if ok else "failed",
            classification=classification,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group="dom/tests/mochitest.toml", ok=ok, duration=1)]
        return t

    p = create_pushes(9)
    for j in list(range(0, 4)) + list(range(6, 9)):
        p[j].tasks = [task(1, True)]
    # The group passed on the push, on the job type which failed on the next push.
    p[4].tasks = [task(1, True, label="test-linux/opt-mochitest-2")]
    failing = task(2, False, classification="fixed by commit")
    failing.classification_note = p[7].rev
    p[5].tasks = [failing]
    p[4].backedoutby = p[7].rev
    p[4]._bugs = {123}
    # The group isn't flaky, and wasn't relanded.
    p[4].attribution._group_failure_stats = {
        "dom/tests/mochitest.toml": {"test-linux/opt-mochitest": (0, 2000)}
    }
    monkeypatch.setattr(
        TreeherderClientSource, "get_job_from_task", lambda self, task: {"id": 1}
    )
    monkeypatch.setattr(
        TreeherderClientSource,
        "get_bug_suggestions",
        lambda self, job_id, branch="autoland": [
            {
                "search": "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | timed out",
                "failure_new_in_rev": False,
                "bugs": {"open_recent": [{"id": 1, "summary": "Intermittent"}]},
            }
        ],
    )
    backout_id = p[7].id
    monkeypatch.setattr(
        HgRev, "load_json_pushes_between_ids", staticmethod(lambda *args: None)
    )
    # The note points to the backout of the push.
    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: (
            any(c == "fixed by commit" for c, n in classifications) or None
        ),
    )

    def regressions(revert):
        monkeypatch.setattr(
            HgRev,
            "JSON_PUSHES_CACHE",
            {
                p[4].id: {
                    "changesets": [
                        {"node": "a", "desc": "Bug 123 - Change", "files": []}
                    ]
                },
                backout_id: {
                    "changesets": [{"node": "r", "desc": revert, "files": []}]
                },
            },
        )
        for push in p:
            for attr in (
                "_get_regressions",
                "_failure_lines",
                "_reland_files",
                "_group_summaries",
                "_failures_until_backout",
                "_backout_file_names",
            ):
                push.__dict__.pop(attr, None)
                push.attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("group")

    # The note is considered wrong: the group passed on that job type with the push.
    assert regressions("Revert 'Bug 123 - Change' for causing build bustages") == {}

    # The backout names the failing test: the classification is trusted.
    assert regressions(
        "Revert 'Bug 123 - Change' for causing failures at test_foo.html"
    ) == {"dom/tests/mochitest.toml": 0}

    # It passed on another job type only: the classification is trusted.
    p[4].tasks = [task(1, True, label="test-windows/opt-mochitest-2")]
    assert regressions("Revert 'Bug 123 - Change' for causing build bustages") == {
        "dom/tests/mochitest.toml": 0
    }


def test_config_group_failure_belongs_to_the_push_naming_the_group(
    create_pushes, monkeypatch
):
    group = "dom/tests/mochitest.toml"

    def task(i, ok, classification="not classified", note=None):
        t = Task.create(
            id=str(i) * 22,
            label="test-linux1804-64/opt-mochitest-plain-1",
            platform="linux1804-64",
            suite="mochitest-plain",
            result="passed" if ok else "failed",
            classification=classification,
            classification_note=note,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group=group, ok=ok, duration=1)]
        return t

    p = create_pushes(11)
    for j in list(range(0, 4)) + list(range(7, 11)):
        p[j].tasks = [task(1, True)]
    # The configuration didn't run on p[4] and p[5], both backed out, and failed on
    # p[6], with a note blaming the backout of p[5].
    p[4].tasks, p[5].tasks = [], []
    p[6].tasks = [task(2, False, "fixed by commit", p[9].rev)]
    p[4].backedoutby, p[5].backedoutby = p[8].rev, p[9].rev
    configuration = p[6].tasks[0].configuration

    # The note points to the push whose backout it references.
    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: any(
            n == self.backedoutby for c, n in classifications if c == "fixed by commit"
        ),
    )
    monkeypatch.setattr(AttributionAnalysis, "NAMED_GROUPS_CACHE", {})
    # Not relanded.
    for push in p:
        push.attribution._reland_files = None
    monkeypatch.setattr(
        test_info,
        "manifests_of_tests",
        lambda date: {"dom/tests/test_foo.html": [group]},
    )

    def regressions(backout_of_p4):
        monkeypatch.setattr(
            HgRev,
            "JSON_PUSHES_CACHE",
            {
                p[8].id: {"changesets": [{"node": "a", "desc": backout_of_p4}]},
                p[9].id: {
                    "changesets": [{"node": "b", "desc": "Revert 'Bug 2' for bustages"}]
                },
            },
        )
        AttributionAnalysis.NAMED_GROUPS_CACHE.clear()
        result = []
        for push in p:
            push.attribution.__dict__.pop("_backout_file_names", None)
        for push in (p[4], p[5]):
            for attr in ("_get_regressions", "_config_group_summaries"):
                push.__dict__.pop(attr, None)
                push.attribution.__dict__.pop(attr, None)
            result.append(push.get_regressions("config_group"))
        return result

    # Nothing names the group: the note is trusted.
    assert regressions("Revert 'Bug 1' for causing build bustages") == [
        {},
        {(configuration, group): 0},
    ]

    # The backout of p[4] names a test of the group: the failure is attributed to it.
    assert regressions("Revert 'Bug 1' for causing failures at test_foo.html") == [
        {(configuration, group): 0},
        {},
    ]


def test_failures_counted_until_a_distant_backout(create_pushes, monkeypatch):
    from mozci.push import MAX_DEPTH

    group = "dom/tests/mochitest.toml"

    def task(i, ok, classification="not classified", note=None):
        t = Task.create(
            id=str(i) * 22,
            label="test-linux/opt-mochitest-1",
            result="passed" if ok else "failed",
            classification=classification,
            classification_note=note,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group=group, ok=ok, duration=1)]
        return t

    # The push is backed out more than MAX_DEPTH pushes later.
    p = create_pushes(MAX_DEPTH + 10)
    backout = p[MAX_DEPTH + 7]
    for push in p:
        push.tasks = [task(1, True)]
    p[2].backedoutby = backout.rev
    # The group failed on the push, and again after MAX_DEPTH children.
    p[2].tasks = [task(2, False, "fixed by commit", backout.rev)]
    p[MAX_DEPTH + 5].tasks = [task(3, False, "fixed by commit", backout.rev)]

    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: (
            any(c == "fixed by commit" for c, n in classifications) or None
        ),
    )
    # The group is flaky, and the failures aren't new.
    monkeypatch.setattr(AttributionAnalysis, "is_flaky_group", lambda *args: True)
    monkeypatch.setattr(AttributionAnalysis, "has_novel_failure", lambda *args: False)

    # Both failures count, so they aren't isolated: the classifications are kept.
    assert p[2].get_regressions("group") == {group: 0}


def test_config_group_failures_on_several_configurations_are_not_isolated(
    create_pushes, monkeypatch
):
    group = "dom/tests/mochitest.toml"

    def task(i, ok, platform, classification="not classified", note=None):
        t = Task.create(
            id=str(i) * 22,
            label=f"test-{platform}/opt-mochitest-plain-1",
            platform=platform,
            suite="mochitest-plain",
            result="passed" if ok else "failed",
            classification=classification,
            classification_note=note,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group=group, ok=ok, duration=1)]
        return t

    p = create_pushes(9)
    for j in list(range(0, 4)) + list(range(6, 9)):
        p[j].tasks = [task(1, True, "linux1804-64"), task(2, True, "windows11-64")]
    p[4].backedoutby = p[7].rev
    p[4].tasks = [task(1, False, "linux1804-64", "fixed by commit", p[7].rev)]

    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: (
            any(c == "fixed by commit" for c, n in classifications) or None
        ),
    )
    # The group is flaky, and the failures aren't new.
    monkeypatch.setattr(AttributionAnalysis, "is_flaky_group", lambda *args: True)
    monkeypatch.setattr(AttributionAnalysis, "has_novel_failure", lambda *args: False)
    monkeypatch.setattr(AttributionAnalysis, "named_culprit", lambda *args: None)

    def regressions():
        for push in p:
            for attr in (
                "_get_regressions",
                "_config_group_summaries",
                "_group_summaries",
                "_failures_until_backout",
            ):
                push.__dict__.pop(attr, None)
                push.attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("config_group")

    # A single failure: considered intermittent.
    assert regressions() == {}

    # The group also failed on another configuration: the classifications are kept.
    p[5].tasks = [task(2, False, "windows11-64", "fixed by commit", p[7].rev)]
    linux = p[4].tasks[0].configuration
    windows = p[5].tasks[0].configuration
    assert regressions() == {(linux, group): 0, (windows, group): 0}


def test_fixed_by_commit_on_one_of_many_job_types_is_intermittent(
    create_pushes, monkeypatch
):
    group = "dom/tests/mochitest.toml"

    def task(i, ok, platform, classification="not classified"):
        t = Task.create(
            id=str(i) * 22,
            label=f"test-{platform}/opt-mochitest-1",
            result="passed" if ok else "failed",
            classification=classification,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group=group, ok=ok, duration=1)]
        return t

    platforms = [f"platform{i}" for i in range(7)]
    p = create_pushes(9)
    for j in list(range(0, 4)) + list(range(5, 9)):
        p[j].tasks = [task(i, True, platform) for i, platform in enumerate(platforms)]
    p[4].backedoutby = p[7].rev
    p[4]._bugs = {123}
    # The group isn't flaky, and wasn't relanded.
    p[4].attribution._group_failure_stats = {}
    monkeypatch.setattr(
        TreeherderClientSource, "get_job_from_task", lambda self, task: {"id": 1}
    )
    monkeypatch.setattr(
        TreeherderClientSource,
        "get_bug_suggestions",
        lambda self, job_id, branch="autoland": [
            {
                "search": "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | timed out",
                "failure_new_in_rev": False,
                "bugs": {"open_recent": [{"id": 1, "summary": "Intermittent"}]},
            }
        ],
    )
    monkeypatch.setattr(
        HgRev, "load_json_pushes_between_ids", staticmethod(lambda *args: None)
    )
    monkeypatch.setattr(
        HgRev,
        "JSON_PUSHES_CACHE",
        {
            p[4].id: {
                "changesets": [{"node": "a", "desc": "Bug 123 - Change", "files": []}]
            },
            p[7].id: {
                "changesets": [
                    {"node": "r", "desc": "Revert 'Bug 123' for bustages", "files": []}
                ]
            },
        },
    )
    # The note points to the backout of the push.
    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: (
            any(c == "fixed by commit" for c, n in classifications) or None
        ),
    )

    def regressions(passing):
        failing = task(0, False, platforms[0], "fixed by commit")
        failing.classification_note = p[7].rev
        p[4].tasks = [failing] + [
            task(i + 1, True, platform)
            for i, platform in enumerate(platforms[1 : 1 + passing])
        ]
        for push in p:
            for attr in (
                "_get_regressions",
                "_failure_lines",
                "_reland_files",
                "_group_summaries",
                "_failures_until_backout",
            ):
                push.__dict__.pop(attr, None)
                push.attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("group")

    # The group passed on 6 other job types on the push: the note is considered wrong.
    assert regressions(6) == {}

    # It passed on 5 other job types only: the classification is trusted.
    assert regressions(5) == {group: 0}


def test_label_failing_before_and_after_the_backout_is_not_a_regression(
    create_pushes, monkeypatch
):
    label = "build-linux64/opt"

    def task(i, ok, classification="not classified", note=None):
        return Task.create(
            id=str(i) * 22,
            label=label,
            result="passed" if ok else "failed",
            classification=classification,
            classification_note=note,
        )

    p = create_pushes(9)
    p[4].backedoutby = p[7].rev
    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: (
            any(c == "fixed by commit" for c, n in classifications) or None
        ),
    )

    def regressions(before, after):
        for j in range(9):
            p[j].tasks = [task(j, True)]
        p[3].tasks = [task(3, before, "intermittent")]
        p[4].tasks = [task(4, False, "fixed by commit", p[7].rev)]
        p[7].tasks = [task(7, after, "intermittent")]
        for push in p:
            for attr in ("_get_regressions", "_label_summaries"):
                push.__dict__.pop(attr, None)
                push.attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("label")

    # The label was already failing, and still failed after the backout.
    assert regressions(before=False, after=False) == {}

    # It passed before the push, or after its backout: the push is the culprit.
    assert regressions(before=True, after=False) == {label: 0}
    assert regressions(before=False, after=True) == {label: 0}


def test_perf_label_is_not_a_regression(create_pushes, monkeypatch):
    p = create_pushes(9)
    p[4].backedoutby = p[7].rev
    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: (
            any(c == "fixed by commit" for c, n in classifications) or None
        ),
    )

    def regressions(label, suite, kind="test"):
        for j in range(9):
            p[j].tasks = [
                Task.create(
                    id=str(j) * 22,
                    label=label,
                    suite=suite,
                    tags={"kind": kind},
                    result="failed" if j == 4 else "passed",
                    classification="fixed by commit" if j == 4 else "not classified",
                    classification_note=p[7].rev if j == 4 else None,
                )
            ]
            for attr in ("_get_regressions", "_label_summaries"):
                p[j].__dict__.pop(attr, None)
                p[j].attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("label")

    assert regressions("test-linux1804-64-shippable/opt-talos-tp5o", "talos") == {}
    assert (
        regressions(
            "test-linux1804-64-shippable/opt-browsertime-tp6", None, kind="perftest"
        )
        == {}
    )
    assert regressions("test-linux1804-64/opt-gtest-1proc", "gtest") == {
        "test-linux1804-64/opt-gtest-1proc": 0
    }


def test_failure_on_backout_caused_by_another_push(create_pushes, monkeypatch):
    group = "dom/tests/mochitest.toml"

    def task(i, ok, note=None):
        t = Task.create(
            id=str(i) * 22,
            label=f"test-linux/opt-mochitest-{i}",
            result="passed" if ok else "failed",
            classification="fixed by commit" if note else "not classified",
            classification_note=note,
            tags={"tests_grouped": "1"},
        )
        t._results = [GroupResult(group=group, ok=ok, duration=1)]
        return t

    p = create_pushes(11)
    for j in range(11):
        p[j].tasks = [task(j, True)]
        p[j].attribution._reland_files = None
    # p[4] broke the group, and was backed out by p[7]. p[6] broke it too, and was
    # backed out by p[9].
    p[4].backedoutby, p[6].backedoutby = p[7].rev, p[9].rev
    p[5].tasks = [task(5, False, p[7].rev), task(15, False, p[7].rev)]
    p[7].tasks = [task(7, False, p[9].rev)]
    p[4].attribution._group_failure_stats = {}

    monkeypatch.setattr(
        Push,
        "_is_classified_as_cause",
        lambda self, first, classifications: next(
            (
                n == self.backedoutby
                for c, n in classifications
                if c == "fixed by commit"
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        HgRev, "load_json_pushes_between_ids", staticmethod(lambda *args: None)
    )
    monkeypatch.setattr(
        HgRev,
        "JSON_PUSHES_CACHE",
        {
            push.id: {"changesets": [{"node": push.rev, "desc": "Change", "files": []}]}
            for push in p
        },
    )
    monkeypatch.setattr(
        TreeherderClientSource, "get_job_from_task", lambda self, task: {"id": task.id}
    )

    def regressions(backout_line):
        lines = {
            "5" * 22: "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | broken",
            "1" * 11
            + "5" * 11: "TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | broken",
            "7" * 22: backout_line,
        }
        monkeypatch.setattr(
            TreeherderClientSource,
            "get_bug_suggestions",
            lambda self, job_id, branch="autoland": [
                {"search": lines[job_id], "failure_new_in_rev": True, "bugs": {}}
            ],
        )
        for push in p:
            for attr in (
                "_get_regressions",
                "_failure_lines",
                "_group_summaries",
                "_failures_until_backout",
            ):
                push.__dict__.pop(attr, None)
                push.attribution.__dict__.pop(attr, None)
        return p[4].get_regressions("group")

    # The failure on the backout is another failure, caused by p[6].
    assert regressions("TEST-UNEXPECTED-FAIL | dom/tests/test_bar.html | other") == {
        group: 0
    }

    # The failure on the backout is in the same test, but on other subtests: it's
    # another failure too.
    assert regressions("TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | other") == {
        group: 0
    }

    # The failure on the backout is the same: it wasn't caused by p[4].
    assert regressions("TEST-UNEXPECTED-FAIL | dom/tests/test_foo.html | broken") == {}
