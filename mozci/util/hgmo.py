# -*- coding: utf-8 -*-
from functools import lru_cache

from mozci.errors import PushNotFound
from mozci.util.req import get_session


class HGMO:
    # urls
    BASE_URL = "https://hg.mozilla.org/"
    AUTOMATION_RELEVANCE_TEMPLATE = BASE_URL + "{branch}/json-automationrelevance/{rev}"
    JSON_TEMPLATE = BASE_URL + "{branch}/rev/{rev}?style=json"
    JSON_PUSHES_TEMPLATE = (
        BASE_URL
        + "{branch}/json-pushes?version=2&startID={push_id_start}&endID={push_id_end}"
    )

    # instance cache
    CACHE = {}

    def __init__(self, rev, branch="autoland"):
        self.context = {
            "branch": "integration/autoland" if branch == "autoland" else branch,
            "rev": rev,
        }

    @staticmethod
    def create(rev, branch="autoland"):
        key = (branch, rev[:12])
        if key in HGMO.CACHE:
            return HGMO.CACHE[key]
        instance = HGMO(rev, branch)
        HGMO.CACHE[key] = instance
        return instance

    @lru_cache(maxsize=None)
    def _get_resource(self, url):
        r = get_session("hgmo").get(url)

        if r.status_code == 404:
            raise PushNotFound(f"{r.status_code} response from {url}", **self.context)

        r.raise_for_status()
        return r.json()

    @property
    def changesets(self):
        url = self.AUTOMATION_RELEVANCE_TEMPLATE.format(**self.context)
        return self._get_resource(url)["changesets"]

    @property
    def data(self):
        url = self.JSON_TEMPLATE.format(**self.context)
        return self._get_resource(url)

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)

    def json_pushes(self, push_id_start, push_id_end):
        url = self.JSON_PUSHES_TEMPLATE.format(
            push_id_start=push_id_start, push_id_end=push_id_end, **self.context,
        )
        return self._get_resource(url)["pushes"]

    @property
    def pushid(self):
        return self.changesets[0]["pushid"]

    @property
    def backouts(self):
        return {
            changeset["node"]: [node["node"] for node in changeset["backsoutnodes"]]
            for changeset in self.changesets
            if len(changeset["backsoutnodes"])
        }
