# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Tuple

import requests

from mozci.errors import PushNotFound
from mozci.util.memoize import memoize, memoized_property
from mozci.util.req import get_session


class HGMO:
    # urls
    BASE_URL = "https://hg.mozilla.org/"
    AUTOMATION_RELEVANCE_TEMPLATE = (
        BASE_URL + "{branch}/json-automationrelevance/{rev}?backouts=1"
    )
    JSON_PUSHES_TEMPLATE_BASE = BASE_URL + "{branch}/json-pushes?version=2"
    JSON_PUSHES_TEMPLATE = (
        JSON_PUSHES_TEMPLATE_BASE + "&startID={push_id_start}&endID={push_id_end}"
    )
    JSON_PUSHES_BETWEEN_DATES_TEMPLATE = (
        JSON_PUSHES_TEMPLATE_BASE + "&startdate={from_date}&enddate={to_date}"
    )

    # instance cache
    CACHE: Dict[Tuple[str, str], HGMO] = {}

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

    def _get_resource(self, url):
        try:
            r = get_session().get(url)
        except requests.exceptions.RetryError as e:
            raise PushNotFound(f"{e} error when getting {url}", **self.context)

        if r.status_code == 404:
            raise PushNotFound(f"{r.status_code} response from {url}", **self.context)

        r.raise_for_status()
        return r.json()

    @memoized_property
    def changesets(self):
        url = self.AUTOMATION_RELEVANCE_TEMPLATE.format(**self.context)
        return self._get_resource(url)["changesets"]

    @memoize
    def json_pushes(self, push_id_start, push_id_end):
        url = self.JSON_PUSHES_TEMPLATE.format(
            push_id_start=push_id_start,
            push_id_end=push_id_end,
            **self.context,
        )
        return self._get_resource(url)["pushes"]

    def json_pushes_between_dates(self, from_date, to_date):
        url = self.JSON_PUSHES_BETWEEN_DATES_TEMPLATE.format(
            from_date=from_date,
            to_date=to_date,
            **self.context,
        )
        return self._get_resource(url)["pushes"]

    def _find_self(self):
        for changeset in self.changesets:
            if changeset["node"].startswith(self.context["rev"]):
                return changeset

        assert False

    @property
    def node(self):
        return self._find_self()["node"]

    @property
    def pushid(self):
        return self.changesets[0]["pushid"]

    @property
    def pushhead(self):
        return self.changesets[0]["pushhead"]

    @property
    def pushdate(self):
        return self.changesets[0]["pushdate"][0]

    @property
    def backedoutby(self):
        self_changeset = self._find_self()
        return (
            self_changeset["backedoutby"] if "backedoutby" in self_changeset else None
        )

    @property
    def backouts(self):
        # Sometimes json-automationrelevance doesn't return all commits of a push.
        # https://bugzilla.mozilla.org/show_bug.cgi?id=1641729
        if self.pushhead not in {changeset["node"] for changeset in self.changesets}:
            return HGMO.create(self.pushhead, branch=self.context["branch"]).backouts

        return {
            changeset["node"]: [node["node"] for node in changeset["backsoutnodes"]]
            for changeset in self.changesets
            if len(changeset["backsoutnodes"])
        }

    @property
    def bugs(self):
        return set(
            bug["no"] for changeset in self.changesets for bug in changeset["bugs"]
        )

    @property
    def bugs_without_backouts(self):
        return {
            bug["no"]: changeset["node"]
            for changeset in self.changesets
            for bug in changeset["bugs"]
            if len(changeset["backsoutnodes"]) == 0
        }
