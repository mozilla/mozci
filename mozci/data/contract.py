# -*- coding: utf-8 -*-

from dataclasses import dataclass
from textwrap import dedent
from typing import Tuple, Union

import validx as v

from mozci.task import FailureType, TestTask


@dataclass
class Contract:
    name: str
    description: str
    validate_in: v.Dict
    validate_out: Union[v.Dict, v.List]


_contracts: Tuple[Contract, ...] = (
    Contract(
        name="push_tasks",
        description="Data about the tasks that ran on a given push.",
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "rev": v.Str(),
            }
        ),
        validate_out=v.List(
            v.Dict(
                {
                    "id": v.Str(),
                    "label": v.Str(),
                    "state": v.Str(
                        options=[
                            "completed",
                            "running",
                            "pending",
                            "unscheduled",
                            "exception",
                        ]
                    ),
                    "tags": v.Dict(extra=(v.Str(), v.Str())),
                    "tier": v.Int(),
                    "duration": v.Int(),
                    "result": v.Str(
                        options=[
                            "passed",
                            "failed",
                            "exception",
                            "canceled",
                            "superseded",
                        ]
                    ),
                },
                optional=["duration", "result", "tier"],
            )
        ),
    ),
    Contract(
        name="push_tasks_classifications",
        description=dedent(
            """
            Return classifications on the tasks that ran on a given push. Tasks
            without a classification need not be present.
        """
        ),
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "rev": v.Str(),
            }
        ),
        validate_out=v.Dict(
            extra=(
                v.Str(),
                v.Dict(
                    {
                        "classification": v.Str(
                            options=[
                                "autoclassified intermittent",
                                "infra",
                                "intermittent",
                                "expected fail",
                                "fixed by commit",
                                "not classified",
                            ],
                        ),
                        "classification_note": v.Str(),
                    },
                    optional=["classification_note"],
                ),
            )
        ),
    ),
    Contract(
        name="push_revisions",
        description="Data from the VCS about a given push.",
        validate_in=v.Dict(
            {
                "from_date": v.Str(),
                "to_date": v.Str(),
                "branch": v.Str(),
            }
        ),
        validate_out=v.List(
            v.Dict(
                {
                    "pushid": v.Int(),
                    "date": v.Int(),
                    "revs": v.List(
                        v.Dict(
                            {
                                "author": v.Str(),
                                "branch": v.Str(),
                                "desc": v.Str(),
                                "files": v.List(v.Str()),
                                "node": v.Str(),
                                "parents": v.List(v.Str()),
                                "tags": v.List(v.Str()),
                            }
                        )
                    ),
                }
            )
        ),
    ),
    Contract(
        name="test_task_groups",
        description="A dict of test groups and their results and durations for a given TestTask.",
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "rev": v.Str(),
                "task": v.Type(TestTask),
            }
        ),
        validate_out=v.Dict(
            # TODO: 'minlen=1' can be added to v.Str(), the group name, once we stop seeing groups with empty names.
            # TODO: 'nullable=True' can be removed once https://github.com/mozilla/mozci/issues/662 is fixed.
            extra=(v.Str(), v.Tuple(v.Bool(), v.Int(nullable=True)))
        ),
    ),
    Contract(
        name="test_task_errors",
        description="A list of errors for a given TestTask.",
        validate_in=v.Dict(
            {
                "task": v.Type(TestTask),
            }
        ),
        validate_out=v.List(v.Str(minlen=1)),
    ),
    Contract(
        name="test_task_failure_types",
        description="A list of failures with their associated type grouped by test group for a given TestTask.",
        validate_in=v.Dict(
            {
                "task_id": v.Str(),
            }
        ),
        validate_out=v.Dict(
            extra=(
                v.Str(minlen=1),
                v.List(v.Tuple(v.Str(minlen=1), v.Type(FailureType))),
            )
        ),
    ),
    Contract(
        name="push_test_selection_data",
        description="Test and build CI Tasks that should be scheduled for a given push",
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "rev": v.Str(),
            }
        ),
        validate_out=v.Dict(
            {
                "config_groups": v.Dict(
                    extra=(v.Str(), v.List(v.Str(minlen=1))),
                ),
                "groups": v.Dict(
                    extra=(v.Str(), v.Float()),
                ),
                "known_tasks": v.List(v.Str(minlen=1)),
                "reduced_tasks": v.Dict(
                    extra=(v.Str(), v.Float()),
                ),
                "reduced_tasks_higher": v.Dict(
                    extra=(v.Str(), v.Float()),
                ),
                "tasks": v.Dict(
                    extra=(v.Str(), v.Float()),
                ),
            }
        ),
    ),
    Contract(
        name="pushes",
        description="List available pushes",
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "nb": v.Int(),
            }
        ),
        validate_out=v.List(
            v.Dict(
                {
                    "pushid": v.Int(),
                    "date": v.Int(),
                    "revs": v.List(v.Str()),
                }
            )
        ),
    ),
    Contract(
        name="push_existing_classification",
        description="Retrieve the pre-existing classification status of a given push",
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "rev": v.Str(),
                "environment": v.Str(),
            }
        ),
        validate_out=v.Str(options=["GOOD", "BAD", "UNKNOWN"]),
    ),
)


all_contracts = {c.name: c for c in _contracts}
