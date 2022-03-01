# -*- coding: utf-8 -*-

import json

import markdown2
import pytest

from mozci.console.commands.push import ClassifyCommand
from mozci.push import PushStatus, Regressions
from mozci.task import TestTask

EMAIL_EMPTY_TO_BAD = """
# Push 1 evolved from no classification to BAD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- Group [group1](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group1) - Tasks [random-test-task](https://treeherder.mozilla.org/#/jobs?repo=unittest&revision=rev1&selectedTaskRun=taskIdXXX-0)
- Group [group2](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group2) - Tasks No tasks available

"""

EMAIL_UNKNOWN_TO_BAD = """
# Push 1 evolved from UNKNOWN to BAD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- Group [group1](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group1) - Tasks [random-test-task](https://treeherder.mozilla.org/#/jobs?repo=unittest&revision=rev1&selectedTaskRun=taskIdXXX-0)
- Group [group2](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group2) - Tasks No tasks available

"""

EMAIL_BAD_TO_UNKNOWN = """
# Push 1 evolved from BAD to UNKNOWN

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- Group [group1](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group1) - Tasks [random-test-task](https://treeherder.mozilla.org/#/jobs?repo=unittest&revision=rev1&selectedTaskRun=taskIdXXX-0)
- Group [group2](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group2) - Tasks No tasks available

"""

EMAIL_BAD_TO_GOOD = """
# Push 1 evolved from BAD to GOOD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- Group [group1](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group1) - Tasks [random-test-task](https://treeherder.mozilla.org/#/jobs?repo=unittest&revision=rev1&selectedTaskRun=taskIdXXX-0)
- Group [group2](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group2) - Tasks No tasks available

"""

EMAIL_GOOD_TO_BAD = """
# Push 1 evolved from GOOD to BAD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- Group [group1](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group1) - Tasks [random-test-task](https://treeherder.mozilla.org/#/jobs?repo=unittest&revision=rev1&selectedTaskRun=taskIdXXX-0)
- Group [group2](https://treeherder.mozilla.org/#/jobs?repo=unittest&tochange=rev1&test_paths=group2) - Tasks No tasks available

"""


@pytest.mark.parametrize(
    "previous, current, email_content",
    (
        (None, PushStatus.GOOD, None),
        (None, PushStatus.UNKNOWN, None),
        (None, PushStatus.BAD, EMAIL_EMPTY_TO_BAD),
        (PushStatus.GOOD, PushStatus.GOOD, None),
        (PushStatus.GOOD, PushStatus.UNKNOWN, None),
        (PushStatus.GOOD, PushStatus.BAD, EMAIL_GOOD_TO_BAD),
        (PushStatus.BAD, PushStatus.GOOD, EMAIL_BAD_TO_GOOD),
        (PushStatus.BAD, PushStatus.UNKNOWN, EMAIL_BAD_TO_UNKNOWN),
        (PushStatus.BAD, PushStatus.BAD, None),
        (PushStatus.UNKNOWN, PushStatus.GOOD, None),
        (PushStatus.UNKNOWN, PushStatus.UNKNOWN, None),
        (PushStatus.UNKNOWN, PushStatus.BAD, EMAIL_UNKNOWN_TO_BAD),
    ),
)
def test_classification_evolution(
    create_push, responses, previous, current, email_content
):

    # Setup dummy regressions with real failures
    regressions = Regressions(
        real={
            "group1": [TestTask(id="taskIdXXX", label="random-test-task")],
            "group2": [],
        },
        intermittent={},
        unknown={},
    )

    # Create a random push
    push = create_push()

    # Mock Taskcluster email notification service
    responses.add(
        responses.POST,
        "https://community-tc.services.mozilla.com/api/notify/v1/email",
        json={},
        status=200,
    )
    # Mock Taskcluster Matrix notification service
    responses.add(
        responses.POST,
        "https://community-tc.services.mozilla.com/api/notify/v1/matrix",
        json={},
        status=200,
    )

    # Run the notification code from mozci push classify
    cmd = ClassifyCommand()
    cmd.name = "classify"
    cmd.branch = "unittest"
    cmd.send_notifications(
        emails=["test@mozilla.com"],
        matrix_room="!tEsTmAtRIxRooM:mozilla.org",
        push=push,
        previous=previous,
        current=current,
        regressions=regressions,
    )

    if email_content:
        # Check an email and a matrix notification were correctly sent
        assert len(responses.calls) == 2
        email_call = responses.calls[0]
        assert json.loads(email_call.request.body) == {
            "address": "test@mozilla.com",
            "subject": "Mozci | Push status evolution 1 rev1",
            "content": email_content,
        }
        matrix_call = responses.calls[1]
        assert json.loads(matrix_call.request.body) == {
            "roomId": "!tEsTmAtRIxRooM:mozilla.org",
            "body": email_content,
            "formattedBody": markdown2.markdown(email_content),
            "format": "org.matrix.custom.html",
        }
    else:
        # Check no email was sent
        assert len(responses.calls) == 0
