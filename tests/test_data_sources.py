# -*- coding: utf-8 -*-
from pprint import pprint
from textwrap import dedent

import pytest
import responses

from mozci.data import DataHandler
from mozci.data.contract import all_contracts
from mozci.data.sources.treeherder import TreeherderClientSource
from mozci.task import Task


class Responses:
    """Simple container to make test cases below more readable."""

    taskcluster_push_tasks = (
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/index/v1/task/gecko.v2.autoland.revision.abcdef.taskgraph.decision",
            "status": 200,
            "json": {
                "taskId": "abc123",
            },
        },
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/abc123",
            "status": 200,
            "json": {
                "taskGroupId": "xyz789",
            },
        },
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task-group/xyz789/list",
            "status": 200,
            "json": {
                "tasks": [
                    {
                        "task": {
                            "extra": {
                                "treeherder": {"tier": 3},
                            },
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                        },
                        "status": {
                            "taskId": "abc123",
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "ActionTask",
                            },
                        },
                        "status": {
                            "taskId": "abc123",
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "task-A",
                            },
                            "tags": {"name": "tag-A"},
                        },
                        "status": {
                            "taskId": "task-id-A",
                            "state": "unscheduled",
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "task-B",
                            },
                            "tags": {},
                        },
                        "status": {
                            "taskId": "task-id-B",
                            "state": "pending",
                            "runs": [{}],
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "task-C",
                            },
                            "tags": {"name": "tag-C"},
                        },
                        "status": {
                            "taskId": "task-id-C",
                            "state": "pending",
                            "runs": [
                                {
                                    "reasonResolved": "claim-expired",
                                    "resolved": "2020-10-28T19:19:27.341Z",
                                }
                            ],
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "task-D",
                            },
                            "tags": {},
                        },
                        "status": {
                            "taskId": "task-id-D",
                            "state": "running",
                            "runs": [
                                {
                                    "started": "2020-10-28T19:18:27.341Z",
                                }
                            ],
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "task-E",
                            },
                            "tags": {},
                        },
                        "status": {
                            "taskId": "task-id-E",
                            "state": "completed",
                            "runs": [
                                {
                                    "started": "2020-10-28T19:18:27.341Z",
                                    "resolved": "2020-10-28T19:19:27.341Z",
                                    "reasonResolved": "failed",
                                }
                            ],
                        },
                    },
                    {
                        "task": {
                            "extra": {},
                            "metadata": {
                                "name": "task-F",
                            },
                            "tags": {},
                        },
                        "status": {
                            "taskId": "task-id-F",
                            "state": "completed",
                            "runs": [
                                {
                                    "started": "2020-10-28T19:18:27.341Z",
                                    "resolved": "2020-10-28T19:19:27.341Z",
                                    "reasonResolved": "completed",
                                }
                            ],
                        },
                    },
                ],  # end tasks
            },  # end json
        },
    )

    treeherder_push_tasks_classifications = (
        {
            "method": responses.GET,
            "url": f"{TreeherderClientSource.base_url}/project/autoland/note/push_notes/?revision=abcdef&format=json",
            "status": 200,
            "json": [
                {
                    "job": {
                        "task_id": "apfcu1KHSVqCHT_3P2QMfQ",
                    },
                    "failure_classification_name": "fixed by commit",
                    "text": "c81c365a9616218b15035c19111a488b51252225",
                },
                {
                    "job": {
                        "task_id": "B87ylZVeTYG4dgrPzeBkhg",
                    },
                    "failure_classification_name": "fixed by commit",
                    "text": "",
                },
            ],
        },
    )

    treeherder_push_test_groups = (
        {
            "method": responses.GET,
            "url": f"{TreeherderClientSource.base_url}/project/autoland/push/group_results/?revision=abcdef&format=json",
            "status": 200,
            "json": {
                "AMHoZy9eRE2_l7xPabtwiw": {"devtools/client/netmonitor/test": True},
                "amn79ZnzQbWAbrSvxJ-GBQ": {"dom/media/test": False},
                "anz5vAGSTqOEDk9pjAxyxg": {
                    "devtools/client/inspector/flexbox/test": True,
                    "devtools/client/netmonitor/src/har/test": False,
                    "devtools/client/application/test/browser": True,
                    "devtools/client/inspector/rules/test": False,
                },
                "a0Lw1AH_T9mSnvHxKKKCBg": {"": True, "default": False},
            },
        },
    )

    errorsummary_test_task_groups = (
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/1111111111111111111111/artifacts",
            "status": 200,
            "json": {
                "artifacts": [{"name": "errorsummary.log"}],
            },
        },
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/1111111111111111111111/artifacts/errorsummary.log",
            "status": 200,
            "body": dedent(
                r"""
                {"action": "test_groups", "line": 3, "groups": ["layout/base/tests/browser.ini", "toolkit/components/certviewer/tests/browser/browser.ini", "browser/base/content/test/general/browser.ini", "toolkit/components/nimbus/test/browser/browser.ini", "browser/components/customizableui/test/browser.ini", "browser/components/urlbar/tests/browser-tips/browser.ini", "toolkit/components/pictureinpicture/tests/browser.ini", "browser/components/shell/test/browser.ini", "toolkit/content/tests/browser/browser.ini", "browser/base/content/test/sanitize/browser.ini", "tools/profiler/tests/browser/browser.ini"]}
                {"status": "FAIL", "subtest": "second value", "group": "toolkit/content/tests/browser/browser.ini", "action": "test_result", "known_intermittent": [], "test": "toolkit/content/tests/browser/browser_findbar_marks.js", "message": "got 1354, expected 1366 epsilon: +/- 10\nStack trace:\nchrome://mochikit/content/tests/SimpleTest/SimpleTest.js:SimpleTest.isfuzzy:513\nchrome://mochitests/content/browser/toolkit/content/tests/browser/browser_findbar_marks.js:test_findmarks:91", "line": 4054, "stack": null, "expected": "PASS"}
                {"status": "FAIL", "subtest": "second value", "group": "toolkit/content/tests/browser/browser.ini", "action": "test_result", "known_intermittent": [], "test": "toolkit/content/tests/browser/browser_findbar_marks.js", "message": "got 1354, expected 1366 epsilon: +/- 10\nStack trace:\nchrome://mochikit/content/tests/SimpleTest/SimpleTest.js:SimpleTest.isfuzzy:513\nchrome://mochitests/content/browser/toolkit/content/tests/browser/browser_findbar_marks.js:test_findmarks:91", "line": 4095, "stack": null, "expected": "PASS"}
                {"status": "FAIL", "subtest": "second value", "group": "toolkit/content/tests/browser/browser.ini", "action": "test_result", "known_intermittent": [], "test": "toolkit/content/tests/browser/browser_findbar_marks.js", "message": "got 1354, expected 1366 epsilon: +/- 10\nStack trace:\nchrome://mochikit/content/tests/SimpleTest/SimpleTest.js:SimpleTest.isfuzzy:513\nchrome://mochitests/content/browser/toolkit/content/tests/browser/browser_findbar_marks.js:test_findmarks:91", "line": 4136, "stack": null, "expected": "PASS"}
                {"status": "OK", "duration": 12430, "line": 4465, "group": "layout/base/tests/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 8906, "line": 4465, "group": "tools/profiler/tests/browser/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 50884, "line": 4465, "group": "toolkit/components/certviewer/tests/browser/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 227333, "line": 4465, "group": "browser/base/content/test/general/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 405460, "line": 4465, "group": "browser/components/shell/test/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 371201, "line": 4465, "group": "browser/components/customizableui/test/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 44998, "line": 4465, "group": "browser/components/urlbar/tests/browser-tips/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 686860, "line": 4465, "group": "toolkit/components/pictureinpicture/tests/browser.ini", "action": "group_result"}
                {"status": "ERROR", "duration": 822508, "line": 4465, "group": "toolkit/content/tests/browser/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 7657, "line": 4465, "group": "browser/base/content/test/sanitize/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 351, "line": 4465, "group": "toolkit/components/nimbus/test/browser/browser.ini", "action": "group_result"}
            """.strip()
            ),
        },
    )


@pytest.mark.parametrize(
    "source,contract,rsps,data_in,expected",
    (
        # taskcluster
        pytest.param(
            "taskcluster",
            "push_tasks",
            # responses
            Responses.taskcluster_push_tasks,
            # input
            {"branch": "autoland", "rev": "abcdef"},
            # expected output
            [
                {
                    "id": "task-id-A",
                    "label": "task-A",
                    "state": "unscheduled",
                    "tags": {"name": "tag-A"},
                },
                {"id": "task-id-B", "label": "task-B", "state": "pending", "tags": {}},
                {
                    "id": "task-id-C",
                    "label": "task-C",
                    "result": "exception",
                    "state": "pending",
                    "tags": {"name": "tag-C"},
                },
                {"id": "task-id-D", "label": "task-D", "state": "running", "tags": {}},
                {
                    "duration": 60000,
                    "id": "task-id-E",
                    "label": "task-E",
                    "result": "failed",
                    "state": "completed",
                    "tags": {},
                },
                {
                    "duration": 60000,
                    "id": "task-id-F",
                    "label": "task-F",
                    "result": "passed",
                    "state": "completed",
                    "tags": {},
                },
            ],
            id="taskcluster.push_tasks",
        ),
        # treeherder_client
        pytest.param(
            "treeherder_client",
            "push_tasks_classifications",
            # responses
            Responses.treeherder_push_tasks_classifications,
            # input
            {"branch": "autoland", "rev": "abcdef"},
            # expected output
            {
                "B87ylZVeTYG4dgrPzeBkhg": {"classification": "fixed by commit"},
                "apfcu1KHSVqCHT_3P2QMfQ": {
                    "classification": "fixed by commit",
                    "classification_note": "c81c365a9616218b15035c19111a488b51252225",
                },
            },
            id="treeherder_client.push_tasks_classifications",
        ),
        pytest.param(
            "treeherder_client",
            "push_test_groups",
            # responses
            Responses.treeherder_push_test_groups,
            # input
            {"branch": "autoland", "rev": "abcdef"},
            # expected output
            {
                "AMHoZy9eRE2_l7xPabtwiw": {"devtools/client/netmonitor/test": True},
                "amn79ZnzQbWAbrSvxJ-GBQ": {"dom/media/test": False},
                "anz5vAGSTqOEDk9pjAxyxg": {
                    "devtools/client/inspector/flexbox/test": True,
                    "devtools/client/netmonitor/src/har/test": False,
                    "devtools/client/application/test/browser": True,
                    "devtools/client/inspector/rules/test": False,
                },
            },
            id="treeherder_client.push_tasks_classifications",
        ),
        # errorsummary
        pytest.param(
            "errorsummary",
            "test_task_groups",
            # responses
            Responses.errorsummary_test_task_groups,
            # input
            {"task": Task.create(id="1" * 22, label="test-foo")},
            # expected output
            {
                "browser/base/content/test/general/browser.ini": True,
                "browser/base/content/test/sanitize/browser.ini": True,
                "browser/components/customizableui/test/browser.ini": True,
                "browser/components/shell/test/browser.ini": True,
                "browser/components/urlbar/tests/browser-tips/browser.ini": True,
                "layout/base/tests/browser.ini": True,
                "toolkit/components/certviewer/tests/browser/browser.ini": True,
                "toolkit/components/nimbus/test/browser/browser.ini": True,
                "toolkit/components/pictureinpicture/tests/browser.ini": True,
                "toolkit/content/tests/browser/browser.ini": False,
                "tools/profiler/tests/browser/browser.ini": True,
            },
            id="errorsummary.test_task_groups",
        ),
    ),
)
def test_source(responses, source, contract, rsps, data_in, expected):
    source = DataHandler.ALL_SOURCES[source]
    contract = all_contracts[contract]
    assert contract.validate_in(data_in)  # ensures we remember to update the tests

    func = getattr(source, f"run_{contract.name}")

    for rsp in rsps:
        responses.add(**rsp)

    data_out = func(**data_in)
    print("Dumping result for copy/paste:")
    pprint(data_out, indent=2)
    assert data_out == expected
    contract.validate_out(data_out)
