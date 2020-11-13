# -*- coding: utf-8 -*-

from dataclasses import dataclass
from textwrap import dedent
from typing import Tuple

from voluptuous import All, Any, Length, Marker, Optional, Required, Schema


@dataclass
class Contract:
    name: str
    description: str
    validate_in: Schema
    validate_out: Schema


_contracts: Tuple[Contract, ...] = (
    Contract(
        name="push_tasks",
        description="Data about the tasks that ran on a given push.",
        validate_in=Schema(
            {
                Required("branch"): str,
                Required("rev"): str,
            }
        ),
        validate_out=Schema(
            [
                {
                    Required("id"): str,
                    Required("label"): str,
                    Required("state"): Any(
                        "completed",
                        "running",
                        "pending",
                        "unscheduled",
                    ),
                    Required("tags"): {
                        Marker(str, description="tag name"): Marker(
                            str, description="tag value"
                        )
                    },
                    Optional("duration"): int,
                    Optional("result"): Any(
                        "passed",
                        "failed",
                        "exception",
                        "canceled",
                        "superseded",
                    ),
                }
            ]
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
        validate_in=Schema(
            {
                Required("branch"): str,
                Required("rev"): str,
            }
        ),
        validate_out=Schema(
            {
                Marker(str, description="task id"): {
                    Required("classification"): Any(
                        "autoclassified intermittent",
                        "infra",
                        "intermittent",
                        "expected fail",
                        "fixed by commit",
                        "not classified",
                    ),
                    Optional("classification_note"): str,
                }
            }
        ),
    ),
    Contract(
        name="push_test_groups",
        description="Data about the test groups that ran on a given push.",
        validate_in=Schema(
            {
                Required("branch"): str,
                Required("rev"): str,
            }
        ),
        validate_out=Schema(
            {
                Marker(All(str, Length(min=22, max=22)), description="task id"): {
                    Marker(All(str, Length(min=1)), description="group name"): Marker(
                        bool, description="group result"
                    )
                }
            }
        ),
    ),
    Contract(
        name="push_revisions",
        description="Data from the VCS about a given push.",
        validate_in=Schema(
            {
                Required("from_date"): str,
                Required("to_date"): str,
                Required("branch"): str,
            }
        ),
        validate_out=Schema(
            [
                {
                    Required("pushid"): int,
                    Required("date"): int,
                    Required("revs"): [str],
                }
            ]
        ),
    ),
)


all_contracts = {c.name: c for c in _contracts}
