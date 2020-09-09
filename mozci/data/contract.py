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
            ]
        ),
    ),
    Contract(
        name="push_tasks_tags",
        description="Data about the tags associated with tasks on a given push.",
        validate_in=Schema(
            {
                Required("branch"): str,
                Required("rev"): str,
            }
        ),
        validate_out=Schema(
            {
                Marker(str, description="task id"): {
                    Marker(str, description="tag name"): Marker(
                        str, description="tag value"
                    )
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
)


all_contracts = {c.name: c for c in _contracts}
