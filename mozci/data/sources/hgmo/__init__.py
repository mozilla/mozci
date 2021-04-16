# -*- coding: utf-8 -*-

from mozci.data.base import DataSource
from mozci.util.hgmo import HgRev


class HGMOSource(DataSource):
    """Queries hg.mozilla.org for revision data about pushes."""

    name = "hgmo"
    supported_contracts = ("push_revisions",)

    def run_push_revisions(self, from_date, to_date, branch):
        result = HgRev.load_json_pushes_between_dates(branch, from_date, to_date)

        return [
            {
                "pushid": int(push_id),
                "date": push_data["date"],
                "revs": push_data["changesets"][::-1],
            }
            for push_id, push_data in result.items()
        ]
