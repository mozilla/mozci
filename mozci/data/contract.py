# -*- coding: utf-8 -*-

from dataclasses import dataclass
from textwrap import dedent
from typing import Tuple, Union

import validx as v

from mozci.task import TestTask


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
                optional=["duration", "result"],
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
                    "revs": v.List(v.Str()),
                }
            )
        ),
    ),
    Contract(
        name="test_task_groups",
        description="A dict of test groups and their results for a given TestTask.",
        validate_in=v.Dict(
            {
                "branch": v.Str(),
                "rev": v.Str(),
                "task": v.Type(TestTask),
            }
        ),
        validate_out=v.Dict(extra=(v.Str(minlen=1), v.Bool())),
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
)


all_contracts = {c.name: c for c in _contracts}
