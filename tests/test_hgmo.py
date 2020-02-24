# -*- coding: utf-8 -*-
import pytest
import requests

from mozci.util.hgmo import HGMO


class MockResponse(object):
    def __init__(self, url, data):
        self.status_code = 200
        self.url = url
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


@pytest.fixture
def patch_requests(monkeypatch):

    def inner(data, fmt=None):
        if fmt == 'automation_relevance':
            data = {
                'changesets': [
                    data
                ]
            }

        def mock_get(url):
            return MockResponse(url, data)

        monkeypatch.setattr(requests, 'get', mock_get)

    return inner


def test_hgmo_cache():
    # HGMO.create() uses a cache.
    h1 = HGMO.create('abcdef', 'autoland')
    h2 = HGMO.create('abcdef', 'autoland')
    assert h1 == h2

    # Instantiating directly ignores the cache.
    h1 = HGMO('abcdef', 'autoland')
    h2 = HGMO('abcdef', 'autoland')
    assert h1 != h2


def test_hgmo_is_backout(patch_requests):
    patch_requests({'backsoutnodes': []}, fmt='automation_relevance')
    h = HGMO('abcdef')
    assert h['backsoutnodes'] == []
    assert not h.is_backout

    patch_requests({'backsoutnodes': ['123456']}, fmt='automation_relevance')
    h = HGMO('abcdef')
    assert h.is_backout
    assert h['backsoutnodes'] == ['123456']
