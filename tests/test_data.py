# -*- coding: utf-8 -*-
import pytest
import validx as v

from mozci import data
from mozci.data.base import DataHandler, DataSource
from mozci.data.contract import Contract
from mozci.errors import (
    ContractNotFilled,
    ContractNotFound,
    InvalidSource,
    SourcesNotFound,
)

FAKE_CONTRACTS = (
    Contract(
        name="foo",
        description="test",
        validate_in=v.Dict({"label": v.Str()}),
        validate_out=v.Dict({"count": v.Int()}),
    ),
    Contract(
        name="bar",
        description="test",
        validate_in=v.Dict({"desc": v.Str()}),
        validate_out=v.Dict({"amount": v.Int()}),
    ),
    Contract(
        name="baz",
        description="test",
        validate_in=v.Dict({"id": v.Str()}),
        validate_out=v.Dict({"sum": v.Int()}),
    ),
    Contract(
        name="incomplete",
        description="test",
        validate_in=v.Dict({}),
        validate_out=v.Dict({}),
    ),
)


class FakeSource(DataSource):
    name = "fake"
    supported_contracts = ("foo", "bar", "incomplete")

    def run_foo(self, **context):
        return {"count": "1"}

    def run_bar(self, **context):
        return {"amount": 1}

    def run_incomplete(self, **context):
        raise ContractNotFilled(self.name, "incomplete", "testing")


class BadSource(DataSource):
    name = "invalid"
    supported_contracts = ("foo",)


def test_data_handler(monkeypatch):
    with pytest.raises(Exception):
        DataHandler("nonexistent")

    monkeypatch.setattr(data.base, "all_contracts", {c.name: c for c in FAKE_CONTRACTS})
    monkeypatch.setattr(DataHandler, "ALL_SOURCES", {"fake": FakeSource()})
    handler = DataHandler("fake")

    with pytest.raises(v.exc.SchemaError):
        handler.get("baz")

    with pytest.raises(SourcesNotFound):
        handler.get("baz", id="baz")

    with pytest.raises(SourcesNotFound):
        handler.get("incomplete")

    with pytest.raises(ContractNotFound):
        handler.get("fleem")

    with pytest.raises(v.exc.SchemaError):
        handler.get("foo")

    with pytest.raises(v.exc.SchemaError):
        handler.get("foo", label="foo")

    assert handler.get("bar", desc="tada") == {"amount": 1}


def test_data_source():
    with pytest.raises(InvalidSource):
        BadSource()

    source = FakeSource()

    with pytest.raises(AttributeError):
        source.get("baz")

    assert source.get("foo") == {"count": "1"}
    assert source.get("bar") == {"amount": 1}
