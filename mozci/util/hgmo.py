# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, NewType, Tuple

import requests
from lru import LRU

from mozci.errors import PushNotFound
from mozci.util.memoize import memoized_property
from mozci.util.req import get_session

HgPush = NewType("HgPush", Dict[str, Any])


class HgRev:
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
    CACHE: Dict[Tuple[str, str], HgRev] = LRU(1000)
    JSON_PUSHES_CACHE: Dict[int, HgPush] = LRU(1000)

    def __init__(self, rev, branch="autoland"):
        self.context = {
            "branch": "integration/autoland" if branch == "autoland" else branch,
            "rev": rev,
        }

    @staticmethod
    def create(rev, branch="autoland"):
        key = (branch, rev[:12])
        if key in HgRev.CACHE:
            return HgRev.CACHE[key]
        instance = HgRev(rev, branch)
        HgRev.CACHE[key] = instance
        return instance

    @staticmethod
    def _get_and_cache_pushes(branch: str, url: str) -> List[HgPush]:
        pushes = HgRev._get_resource(url, context={"branch": branch})["pushes"]
        for push_id, value in pushes.items():
            HgRev.JSON_PUSHES_CACHE[int(push_id)] = value
        return pushes

    @staticmethod
    def load_json_pushes_between_ids(
        branch: str, push_id_start: int, push_id_end: int
    ) -> List[HgPush]:
        url = HgRev.JSON_PUSHES_TEMPLATE.format(
            push_id_start=push_id_start,
            push_id_end=push_id_end,
            branch=f"integration/{branch}" if branch == "autoland" else branch,
        )
        return HgRev._get_and_cache_pushes(branch, url)

    @staticmethod
    def load_json_pushes_between_dates(
        branch: str, from_date: str, to_date: str
    ) -> List[HgPush]:
        url = HgRev.JSON_PUSHES_BETWEEN_DATES_TEMPLATE.format(
            from_date=from_date,
            to_date=to_date,
            branch=f"integration/{branch}" if branch == "autoland" else branch,
        )
        return HgRev._get_and_cache_pushes(branch, url)

    @staticmethod
    def load_json_push(branch: str, push_id: int) -> HgPush:
        if push_id not in HgRev.JSON_PUSHES_CACHE:
            url = HgRev.JSON_PUSHES_TEMPLATE.format(
                push_id_start=push_id - 1,
                push_id_end=push_id,
                branch=f"integration/{branch}" if branch == "autoland" else branch,
            )
            HgRev._get_and_cache_pushes(branch, url)

        if push_id not in HgRev.JSON_PUSHES_CACHE:
            raise PushNotFound(
                f"push id {push_id} does not exist", rev="unknown", branch=branch
            )
        return HgRev.JSON_PUSHES_CACHE[push_id]

    @classmethod
    def _get_resource(cls, url, context=None):
        context = context or getattr(cls, "context", {})
        context.setdefault("branch", "unknown branch")
        context.setdefault("rev", "unknown")

        try:
            r = get_session().get(url)
        except requests.exceptions.RetryError as e:
            raise PushNotFound(f"{e} error when getting {url}", **context)

        if r.status_code == 404:
            raise PushNotFound(f"{r.status_code} response from {url}", **context)

        r.raise_for_status()
        return r.json()

    @memoized_property
    def changesets(self):
        url = self.AUTOMATION_RELEVANCE_TEMPLATE.format(**self.context)
        return self._get_resource(url)["changesets"]

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
            return HgRev.create(self.pushhead, branch=self.context["branch"]).backouts

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
