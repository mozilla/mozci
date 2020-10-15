# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Tuple

from voluptuous import Any, Marker, Optional, Required, Schema


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
                    Required("tags"): {
                        Marker(str, description="tag name"): Marker(
                            str, description="tag value"
                        )
                    },
                }
            ]
        ),
    ),
    Contract(
        name="push_tasks_results",
        description="Data about the results of the tasks that ran on a given push.",
        validate_in=Schema(
            {
                Required("branch"): str,
                Required("rev"): str,
            }
        ),
        validate_out=Schema(
            {
                Marker(str, description="task id"): {
                    Required("result"): str,
                    Required("classification"): Any(
                        "autoclassified intermittent",
                        "infra",
                        "intermittent",
                        "expected fail",
                        "fixed by commit",
                        "not classified",
                    ),
                    Optional("classification_note"): str,
                    Optional("duration"): int,
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
                Marker(str, description="task id"): {
                    Marker(str, description="group name"): Marker(
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
