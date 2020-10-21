# -*- coding: utf-8 -*-
import pytest
from voluptuous import MultipleInvalid, Required, Schema

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
        validate_in=Schema({Required("label"): str}),
        validate_out=Schema({Required("count"): int}),
    ),
    Contract(
        name="bar",
        description="test",
        validate_in=Schema({Required("desc"): str}),
        validate_out=Schema({Required("amount"): int}),
    ),
    Contract(
        name="baz",
        description="test",
        validate_in=Schema({Required("id"): str}),
        validate_out=Schema({Required("sum"): int}),
    ),
    Contract(
        name="incomplete",
        description="test",
        validate_in=Schema({}),
        validate_out=Schema({}),
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

    with pytest.raises(MultipleInvalid):
        handler.get("baz")

    with pytest.raises(SourcesNotFound):
        handler.get("baz", id="baz")

    with pytest.raises(SourcesNotFound):
        handler.get("incomplete")

    with pytest.raises(ContractNotFound):
        handler.get("fleem")

    with pytest.raises(MultipleInvalid):
        handler.get("foo")

    with pytest.raises(MultipleInvalid):
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
