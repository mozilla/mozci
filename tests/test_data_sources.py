# -*- coding: utf-8 -*-
from pprint import pprint

import pytest
import responses

from mozci.data import DataHandler
from mozci.data.contract import all_contracts
from mozci.data.sources.treeherder import TreeherderClientSource


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
