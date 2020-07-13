# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Tuple

from voluptuous import Schema


@dataclass
class Contract:
    name: str
    validate_in: Schema
    validate_out: Schema


_contracts: Tuple[Contract] = (
    Contract(name="placeholder", validate_in=Schema({}), validate_out=Schema({}),),
)


all_contracts = {c.name: c for c in _contracts}
