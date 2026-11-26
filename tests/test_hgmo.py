# -*- coding: utf-8 -*-
from mozci.util.hgmo import HgRev


def test_hgmo_cache():
    # HgRev.create() uses a cache.
    h1 = HgRev.create("abcdef", "autoland")
    h2 = HgRev.create("abcdef", "autoland")
    assert h1 == h2

    # Instantiating directly ignores the cache.
    h1 = HgRev("abcdef", "autoland")
    h2 = HgRev("abcdef", "autoland")
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

    h = HgRev("abcdef")
    assert h.backouts == {}
    assert h.changesets[0]["backsoutnodes"] == []

    h = HgRev("abcdef")
    assert h.backouts == {"789": ["123456"]}
    assert h.changesets[0]["backsoutnodes"] == [{"node": "123456"}]

    h = HgRev("abcdef")
    assert h.backouts == {"789": ["123456"], "jkl": ["asd", "fgh"]}
    assert h.changesets[0]["backsoutnodes"] == [{"node": "123456"}]
    assert h.changesets[1]["backsoutnodes"] == [{"node": "asd"}, {"node": "fgh"}]

    h = HgRev("abcdef")
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

    h = HgRev("abcdef")
    assert h.backedoutby is None

    h = HgRev("123456")
    assert h.backedoutby == "abcdef"


def test_load_json_pushes_between_dates_splits_range(responses):
    base = "https://hg.mozilla.org/integration/autoland/json-pushes?version=2&full=1"
    too_many = {
        "error": "query matches more than 10000 pushes; narrow it with endID, tochange or enddate"
    }

    responses.add(
        responses.GET,
        f"{base}&startdate=2026-01-01&enddate=2026-01-03",
        json=too_many,
        status=400,
        match_querystring=True,
    )
    responses.add(
        responses.GET,
        f"{base}&startdate=2026-01-01&enddate=2026-01-02 00:00:00",
        json={"lastpushid": 3, "pushes": {"1": {"changesets": ["a"], "date": 1}}},
        status=200,
        match_querystring=True,
    )
    responses.add(
        responses.GET,
        f"{base}&startdate=2026-01-01 23:59:59&enddate=2026-01-03",
        json=too_many,
        status=400,
        match_querystring=True,
    )
    responses.add(
        responses.GET,
        f"{base}&startdate=2026-01-01 23:59:59&enddate=2026-01-02 11:59:59",
        json={"lastpushid": 3, "pushes": {"2": {"changesets": ["b"], "date": 2}}},
        status=200,
        match_querystring=True,
    )
    responses.add(
        responses.GET,
        f"{base}&startdate=2026-01-02 11:59:58&enddate=2026-01-03",
        json={"lastpushid": 3, "pushes": {"3": {"changesets": ["c"], "date": 3}}},
        status=200,
        match_querystring=True,
    )

    pushes = HgRev.load_json_pushes_between_dates(
        "autoland", "2026-01-01", "2026-01-03"
    )
    assert list(pushes) == ["1", "2", "3"]
