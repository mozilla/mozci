# -*- coding: utf-8 -*-
from mozci.push import Push  # noqa: F401 (import order, see mozci.util.test_info)
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
