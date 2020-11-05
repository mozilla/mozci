# -*- coding: utf-8 -*-
from mozci.util.hgmo import HGMO


def test_hgmo_cache():
    # HGMO.create() uses a cache.
    h1 = HGMO.create("abcdef", "autoland")
    h2 = HGMO.create("abcdef", "autoland")
    assert h1 == h2

    # Instantiating directly ignores the cache.
    h1 = HGMO("abcdef", "autoland")
    h2 = HGMO("abcdef", "autoland")
    assert h1 != h2


def test_hgmo_backouts(responses):
    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={"changesets": [{"node": "789", "backsoutnodes": [], "pushhead": "789"}]},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={
            "changesets": [
                {
                    "node": "789",
                    "backsoutnodes": [{"node": "123456"}],
                    "pushhead": "789",
                }
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={
            "changesets": [
                {
                    "node": "789",
                    "backsoutnodes": [{"node": "123456"}],
                    "pushhead": "789",
                },
                {"node": "jkl", "backsoutnodes": [{"node": "asd"}, {"node": "fgh"}]},
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={
            "changesets": [
                {
                    "node": "789",
                    "backsoutnodes": [{"node": "123456"}],
                    "pushhead": "ghi",
                },
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/ghi",
        json={
            "changesets": [
                {"node": "ghi", "backsoutnodes": [{"node": "789"}], "pushhead": "ghi"},
                {
                    "node": "789",
                    "backsoutnodes": [{"node": "123456"}],
                    "pushhead": "ghi",
                },
            ]
        },
        status=200,
    )

    h = HGMO("abcdef")
    assert h.backouts == {}
    assert h.changesets[0]["backsoutnodes"] == []

    h = HGMO("abcdef")
    assert h.backouts == {"789": ["123456"]}
    assert h.changesets[0]["backsoutnodes"] == [{"node": "123456"}]

    h = HGMO("abcdef")
    assert h.backouts == {"789": ["123456"], "jkl": ["asd", "fgh"]}
    assert h.changesets[0]["backsoutnodes"] == [{"node": "123456"}]
    assert h.changesets[1]["backsoutnodes"] == [{"node": "asd"}, {"node": "fgh"}]

    h = HGMO("abcdef")
    assert h.backouts == {"789": ["123456"], "ghi": ["789"]}
    assert h.changesets[0]["backsoutnodes"] == [{"node": "123456"}]


def test_hgmo_backedoutby(responses):
    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={
            "changesets": [
                {
                    "node": "abcdef",
                    "backsoutnodes": [{"node": "123456"}],
                    "pushhead": "abcdef",
                }
            ]
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/123456",
        json={
            "changesets": [
                {
                    "node": "123456",
                    "backedoutby": "abcdef",
                    "backsoutnodes": [],
                    "pushhead": "123456",
                },
            ]
        },
        status=200,
    )

    h = HGMO("abcdef")
    assert h.backedoutby is None

    h = HGMO("123456")
    assert h.backedoutby == "abcdef"
