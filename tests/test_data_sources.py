# -*- coding: utf-8 -*-
from pprint import pprint
from textwrap import dedent

import pytest
import responses

from mozci.data import DataHandler
from mozci.data.contract import all_contracts
from mozci.data.sources.treeherder import TreeherderClientSource
from mozci.task import FailureType, TestTask


def create_task(task_id):
    return TestTask.create(id=task_id, label="test-foo")


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
                                "treeherder": {"tier": 3, "jobKind": "test"},
                                "suite": None,
                                "parent": "root-task",
                            },
                        },
                        "status": {
                            "taskId": "abc123",
                        },
                    },
                    {
                        "task": {
                            "extra": {
                                "treeherder": {},
                                "parent": "root-task",
                            },
                            "suite": None,
                        },
                        "status": {
                            "taskId": "abc123",
                        },
                    },
                    {
                        "task": {
                            "extra": {
                                "treeherder": {},
                                "suite": None,
                                "parent": "root-task",
                            },
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
                            "taskQueueId": "gecko-t/t-linux",
                            "extra": {
                                "treeherder": {"tier": 3, "jobKind": "build"},
                                "suite": "task",
                                "parent": "root-task",
                            },
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
                            "extra": {
                                "treeherder": {"tier": 3},
                                "suite": "task",
                                "parent": "root-task",
                            },
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
                            "extra": {
                                "treeherder": {"tier": 3},
                                "suite": "task",
                                "parent": "root-task",
                            },
                            "metadata": {
                                "name": "task-B-2",
                            },
                            "tags": {},
                        },
                        "status": {
                            "taskId": "task-id-B-2",
                            "state": "exception",
                            "runs": [{}],
                        },
                    },
                    {
                        "task": {
                            "extra": {
                                "treeherder": {"tier": 3},
                                "suite": "task",
                                "parent": "root-task",
                            },
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
                            "extra": {
                                "treeherder": {"tier": 3},
                                "suite": "task",
                                "parent": "root-task",
                            },
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
                            "extra": {
                                "treeherder": {"tier": 3, "jobKind": "build"},
                                "suite": "task",
                                "parent": "root-task",
                            },
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
                            "extra": {
                                "treeherder": {"tier": 3, "jobKind": "test"},
                                "suite": "task",
                                "parent": "root-task",
                            },
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
                    "devtools/client/application/test/browser": True,
                    "devtools/client/inspector/flexbox/test": True,
                    "devtools/client/inspector/rules/test": False,
                    "devtools/client/netmonitor/src/har/test": False,
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
                {"action": "log", "level": "error", "message": "oh no!"}
                {"status": "OK", "duration": 50884, "line": 4465, "group": "toolkit/components/certviewer/tests/browser/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 227333, "line": 4465, "group": "browser/base/content/test/general/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 405460, "line": 4465, "group": "browser/components/shell/test/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 371201, "line": 4465, "group": "browser/components/customizableui/test/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 44998, "line": 4465, "group": "browser/components/urlbar/tests/browser-tips/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 686860, "line": 4465, "group": "toolkit/components/pictureinpicture/tests/browser.ini", "action": "group_result"}
                {"action": "log", "level": "error", "message": "error!"}
                {"status": "ERROR", "duration": 822508, "line": 4465, "group": "toolkit/content/tests/browser/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 7657, "line": 4465, "group": "browser/base/content/test/sanitize/browser.ini", "action": "group_result"}
                {"status": "OK", "duration": 351, "line": 4465, "group": "toolkit/components/nimbus/test/browser/browser.ini", "action": "group_result"}
            """.strip()
            ),
        },
    )

    errorsummary_test_task_failure_types = (
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/2222222222222222222222/artifacts",
            "status": 200,
            "json": {
                "artifacts": [{"name": "errorsummary.log"}],
            },
        },
        {
            "method": responses.GET,
            "url": "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/task/2222222222222222222222/artifacts/errorsummary.log",
            "status": 200,
            "body": dedent(
                r"""
                {"action": "test_groups", "line": 3, "groups": ["toolkit/content/tests/browser/browser.ini", "browser/base/content/test/general/browser.ini", "toolkit/components/nimbus/test/browser/browser.ini"]}
                {"test": "toolkit/content/tests/browser/browser_findbar_marks.js", "group": "toolkit/content/tests/browser/browser.ini", "subtest": null, "status": "TIMEOUT", "expected": "PASS", "message": "Test timed out", "stack": null, "known_intermittent": [], "action": "test_result", "line": 2294}
                {"test": "toolkit/content/tests/browser/browser_findbar_marks.js", "group": "toolkit/content/tests/browser/browser.ini", "subtest": null, "status": "TIMEOUT", "expected": "PASS", "message": "Test timed out", "stack": null, "known_intermittent": [], "action": "test_result", "line": 2383}
                {"test": "toolkit/content/tests/browser/browser_findbar_marks.js", "group": "toolkit/content/tests/browser/browser.ini", "subtest": null, "status": "FAIL", "expected": "PASS", "stack": null, "known_intermittent": [], "action": "test_result", "line": 210}
                {"test": "browser/base/content/test/general/tests1.js", "group": "browser/base/content/test/general/browser.ini", "subtest": null, "status": "TIMEOUT", "expected": "PASS", "message": "Test timed out", "stack": null, "known_intermittent": [], "action": "test_result", "line": 554}
                {"test": "browser/base/content/test/general/tests2.js", "group": "browser/base/content/test/general/browser.ini", "signature": "@ mozilla::dom::IDBTransaction::~IDBTransaction()", "stackwalk_stdout": "(....)", "stackwalk_stderr": null, "action": "crash", "line": 1102}
                {"test": "browser/base/content/test/general/tests3.js", "group": "browser/base/content/test/general/browser.ini", "subtest": null, "status": "FAIL", "expected": "PASS", "stack": null, "known_intermittent": [], "action": "test_result", "line": 210}
                {"status": "ERROR", "duration": 822508, "line": 4465, "group": "toolkit/content/tests/browser/browser.ini", "action": "group_result"}
                {"status": "SKIP", "duration": 2, "line": 4465, "group": "browser/base/content/test/general/browser.ini", "action": "group_result"}
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
                    "suite": "task",
                    "platform": "",
                    "queue_id": "gecko-t/t-linux",
                    "variant": {},
                    "state": "unscheduled",
                    "tags": {"name": "tag-A"},
                    "tier": 3,
                    "job_kind": "build",
                    "action": None,
                    "parent": "root-task",
                },
                {
                    "id": "task-id-B",
                    "label": "task-B",
                    "suite": "task",
                    "platform": "",
                    "queue_id": None,
                    "variant": {},
                    "state": "pending",
                    "tags": {},
                    "tier": 3,
                    "action": None,
                    "parent": "root-task",
                },
                {
                    "id": "task-id-B-2",
                    "label": "task-B-2",
                    "suite": "task",
                    "platform": "",
                    "queue_id": None,
                    "variant": {},
                    "state": "exception",
                    "tags": {},
                    "tier": 3,
                    "action": None,
                    "parent": "root-task",
                },
                {
                    "id": "task-id-C",
                    "label": "task-C",
                    "suite": "task",
                    "platform": "",
                    "queue_id": None,
                    "variant": {},
                    "result": "exception",
                    "state": "pending",
                    "tags": {"name": "tag-C"},
                    "tier": 3,
                    "action": None,
                    "parent": "root-task",
                },
                {
                    "id": "task-id-D",
                    "label": "task-D",
                    "suite": "task",
                    "platform": "",
                    "queue_id": None,
                    "variant": {},
                    "state": "running",
                    "tags": {},
                    "tier": 3,
                    "action": None,
                    "parent": "root-task",
                },
                {
                    "duration": 60000,
                    "id": "task-id-E",
                    "label": "task-E",
                    "suite": "task",
                    "platform": "",
                    "queue_id": None,
                    "variant": {},
                    "result": "failed",
                    "state": "completed",
                    "tags": {},
                    "tier": 3,
                    "job_kind": "build",
                    "action": None,
                    "parent": "root-task",
                },
                {
                    "duration": 60000,
                    "id": "task-id-F",
                    "label": "task-F",
                    "suite": "task",
                    "platform": "",
                    "queue_id": None,
                    "variant": {},
                    "result": "passed",
                    "state": "completed",
                    "tags": {},
                    "tier": 3,
                    "job_kind": "test",
                    "action": None,
                    "parent": "root-task",
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
            "test_task_groups",
            # responses
            Responses.treeherder_push_test_groups,
            # input
            {
                "branch": "autoland",
                "rev": "abcdef",
                "task": create_task("anz5vAGSTqOEDk9pjAxyxg"),
            },
            # expected output
            {
                "devtools/client/application/test/browser": (True, None),
                "devtools/client/inspector/flexbox/test": (True, None),
                "devtools/client/inspector/rules/test": (False, None),
                "devtools/client/netmonitor/src/har/test": (False, None),
            },
            id="treeherder_client.test_task_groups",
        ),
        pytest.param(
            "treeherder_client",
            "test_task_groups",
            # no responses due to cache from previous test
            [],
            # input
            {
                "branch": "autoland",
                "rev": "abcdef",
                "task": create_task("AMHoZy9eRE2_l7xPabtwiw"),
            },
            # expected output
            {"devtools/client/netmonitor/test": (True, None)},
            id="treeherder_client.test_task_groups",
        ),
        # errorsummary
        pytest.param(
            "errorsummary",
            "test_task_groups",
            # responses
            Responses.errorsummary_test_task_groups,
            # input
            {"branch": "autoland", "rev": "abcdef", "task": create_task("1" * 22)},
            # expected output
            {
                "browser/base/content/test/general/browser.ini": (True, 227333),
                "browser/base/content/test/sanitize/browser.ini": (True, 7657),
                "browser/components/customizableui/test/browser.ini": (True, 371201),
                "browser/components/shell/test/browser.ini": (True, 405460),
                "browser/components/urlbar/tests/browser-tips/browser.ini": (
                    True,
                    44998,
                ),
                "layout/base/tests/browser.ini": (True, 12430),
                "toolkit/components/certviewer/tests/browser/browser.ini": (
                    True,
                    50884,
                ),
                "toolkit/components/nimbus/test/browser/browser.ini": (True, 351),
                "toolkit/components/pictureinpicture/tests/browser.ini": (True, 686860),
                "toolkit/content/tests/browser/browser.ini": (False, 822508),
                "tools/profiler/tests/browser/browser.ini": (True, 8906),
            },
            id="errorsummary.test_task_groups",
        ),
        pytest.param(
            "errorsummary",
            "test_task_errors",
            # no responses due to cache
            [],
            # input
            {"task": create_task("1" * 22)},
            # expected output
            ["oh no!", "error!"],
            id="errorsummary.test_task_errors",
        ),
        pytest.param(
            "errorsummary",
            "test_task_failure_types",
            # responses
            Responses.errorsummary_test_task_failure_types,
            # input
            {"task_id": "2" * 22},
            # expected output
            {
                "toolkit/content/tests/browser/browser.ini": [
                    (
                        "toolkit/content/tests/browser/browser_findbar_marks.js",
                        FailureType.TIMEOUT,
                    ),
                    (
                        "toolkit/content/tests/browser/browser_findbar_marks.js",
                        FailureType.TIMEOUT,
                    ),
                    (
                        "toolkit/content/tests/browser/browser_findbar_marks.js",
                        FailureType.GENERIC,
                    ),
                ],
                "browser/base/content/test/general/browser.ini": [
                    (
                        "browser/base/content/test/general/tests1.js",
                        FailureType.TIMEOUT,
                    ),
                    (
                        "browser/base/content/test/general/tests2.js",
                        FailureType.CRASH,
                    ),
                    (
                        "browser/base/content/test/general/tests3.js",
                        FailureType.GENERIC,
                    ),
                ],
            },
            id="errorsummary.test_task_failure_types",
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
