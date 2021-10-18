# -*- coding: utf-8 -*-

import requests

from mozci.data.base import DataSource
from mozci.errors import ContractNotFilled
from mozci.util import bugbug


class BugbugSource(DataSource):
    """Queries bugbug.herokuapp.com for schedules data about pushes."""

    name = "bugbug"
    supported_contracts = ("push_test_selection_data",)

    def run_push_test_selection_data(self, branch, rev):
        try:
            results = bugbug.get_schedules(branch, rev)
        except requests.exceptions.HTTPError:
            raise ContractNotFilled(
                self.name,
                "push_test_selection_data",
                "could not retrieve schedules from Bugbug",
            )

        return results
