# -*- coding: utf-8 -*-
import responses

from mozci.util.hgmo import HGMO


def test_hgmo_cache():
    # HGMO.create() uses a cache.
    h1 = HGMO.create('abcdef', 'autoland')
    h2 = HGMO.create('abcdef', 'autoland')
    assert h1 == h2

    # Instantiating directly ignores the cache.
    h1 = HGMO('abcdef', 'autoland')
    h2 = HGMO('abcdef', 'autoland')
    assert h1 != h2


@responses.activate
def test_hgmo_is_backout():
    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/rev/abcdef?style=json",
        json={},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={"changesets": [{"backsoutnodes": []}]},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://hg.mozilla.org/integration/autoland/json-automationrelevance/abcdef",
        json={"changesets": [{"backsoutnodes": ["123456"]}]},
        status=200,
    )

    h = HGMO('abcdef')
    assert h['backsoutnodes'] == []
    assert not h.is_backout

    h = HGMO('abcdef')
    assert h.is_backout
    assert h['backsoutnodes'] == ['123456']
