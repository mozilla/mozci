# -*- coding: utf-8 -*-

import json

import pytest

from mozci.console.commands.push import ClassifyCommand
from mozci.push import PushStatus, Regressions
from mozci.task import TestTask

EMAIL_EMPTY_TO_BAD = """
# Push 1 evolved from no classification to BAD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- group1
- group2

"""

EMAIL_UNKNOWN_TO_BAD = """
# Push 1 evolved from UNKNOWN to BAD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- group1
- group2

"""

EMAIL_BAD_TO_UNKNOWN = """
# Push 1 evolved from BAD to UNKNOWN

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- group1
- group2

"""

EMAIL_BAD_TO_GOOD = """
# Push 1 evolved from BAD to GOOD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- group1
- group2

"""

EMAIL_GOOD_TO_BAD = """
# Push 1 evolved from GOOD to BAD

Rev: [rev1](https://treeherder.mozilla.org/jobs?repo=unittest&revision=rev1)

## Real failures

- group1
- group2

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

    # Run the notification code from mozci push classify
    cmd = ClassifyCommand()
    cmd.name = "classify"
    cmd.branch = "unittest"
    cmd.send_emails(
        emails=["test@mozilla.com"],
        push=push,
        previous=previous,
        current=current,
        regressions=regressions,
    )

    if len(responses.calls) > 0:
        print("-" * 20)
        print(previous, current)
        print(json.loads(responses.calls[0].request.body)["content"])
        print("-" * 20)

    if email_content:
        # Check an email was correctly sent
        assert len(responses.calls) == 1
        call = responses.calls[0]
        assert json.loads(call.request.body) == {
            "address": "test@mozilla.com",
            "subject": "Mozci | Push status evolution 1 rev1",
            "content": email_content,
        }
    else:
        # Check no email was sent
        assert len(responses.calls) == 0
