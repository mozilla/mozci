# -*- coding: utf-8 -*-
from mozci.push import Push  # noqa: F401 (import order, see mozci.util.test_info)
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
