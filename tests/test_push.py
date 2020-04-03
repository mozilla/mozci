# -*- coding: utf-8 -*-

import pytest

from mozci.errors import PushNotFound
from mozci.push import Push
from mozci.util.hgmo import HGMO


def test_create_push(responses):
    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-pushes?version=2&startID=122&endID=123",
        json={
            "pushes": {
                "123": {
                    "changesets": ["123456"],
                    "date": 1213174092,
                    "user": "user@example.org",
                },
            },
        },
        status=200,
    )
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev="abcdef"),
        json={"node": "abcdef"},
        status=200,
    )
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev="123456"),
        json={"node": "123456"},
        status=200,
    )

    p1 = Push("abcdef")
    p2 = p1.create_push(123)
    assert p2.rev == "123456"
    assert p2.id == 123
    assert p2.date == 1213174092


def test_push_does_not_exist(responses):
    # We hit hgmo when 'rev' is less than 40 characters.
    rev = "foobar"
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev=rev),
        json={f"error": "unknown revision '{rev}'"},
        status=404,
    )

    with pytest.raises(PushNotFound):
        Push(rev)

    # Otherwise we need to hit hgmo some other way.
    rev = "a" * 40
    responses.add(
        responses.GET,
        HGMO.JSON_TEMPLATE.format(branch="integration/autoland", rev=rev),
        json={f"error": "unknown revision '{rev}'"},
        status=404,
    )
    p = Push(rev)
    with pytest.raises(PushNotFound):
        p.id


def test_push_bugs(responses):
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"bugs": [{"no": "1624503"}]},
                {"bugs": [{"no": "1624503"}]},
            ]
        },
        status=200,
    )

    p = Push(rev)
    assert p.bugs == {"1624503"}


def test_push_bugs_different(responses):
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"bugs": [{"no": "1617050"}]},
                {"bugs": [{"no": "1625220"}]},
                {"bugs": [{"no": "1625220"}]},
                {"bugs": [{"no": "1625220"}]},
                {"bugs": [{"no": "1595768"}]},
                {"bugs": [{"no": "1595768"}]},
            ]
        },
        status=200,
    )

    p = Push(rev)
    assert p.bugs == {"1617050", "1625220", "1595768"}


def test_push_bugs_multiple(responses):
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    responses.add(
        responses.GET,
        f"https://hg.mozilla.org/integration/autoland/json-automationrelevance/{rev}",
        json={
            "changesets": [
                {"bugs": [{"no": "1617050"}, {"no": "123"}]},
                {"bugs": [{"no": "1617050"}]},
                {"bugs": [{"no": "456"}]},
            ]
        },
        status=200,
    )

    p = Push(rev)
    assert p.bugs == {"123", "456", "1617050"}
