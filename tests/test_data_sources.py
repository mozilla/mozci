# -*- coding: utf-8 -*-
from pprint import pprint

import pytest
import responses

from mozci.data import DataHandler
from mozci.data.contract import all_contracts
from mozci.data.sources.treeherder import TreeherderClientSource


@pytest.mark.parametrize(
    "source,contract,rsps,data_in,expected",
    (
        pytest.param(
            "treeherder_client",
            "push_tasks_classifications",
            # responses
            (
                {
                    "method": responses.GET,
                    "url": f"{TreeherderClientSource.base_url}/project/autoland/note/push_notes/?revision=abcdef&format=json",
                    "status": 200,
                    "json": [
                        {
                            "job": {
                                "task_id": "apfcu1KHSVqCHT_3P2QMfQ",
                            },
                            "failure_classification_name": "fixed by commit",
                            "text": "c81c365a9616218b15035c19111a488b51252225",
                        },
                        {
                            "job": {
                                "task_id": "B87ylZVeTYG4dgrPzeBkhg",
                            },
                            "failure_classification_name": "fixed by commit",
                            "text": "",
                        },
                    ],
                },
            ),
            # input
            {"branch": "autoland", "rev": "abcdef"},
            # expected output
            {
                "B87ylZVeTYG4dgrPzeBkhg": {"classification": "fixed by commit"},
                "apfcu1KHSVqCHT_3P2QMfQ": {
                    "classification": "fixed by commit",
                    "classification_note": "c81c365a9616218b15035c19111a488b51252225",
                },
            },
            id="treeherder_client.push_tasks_classifications",
        ),
    ),
)
def test_source(responses, source, contract, rsps, data_in, expected):
    source = DataHandler.ALL_SOURCES[source]
    contract = all_contracts[contract]
    assert contract.validate_in(data_in)  # ensures we remember to update the tests

    func = getattr(source, f"run_{contract.name}")

    for rsp in rsps:
        responses.add(**rsp)

    data_out = func(**data_in)
    print("Dumping result for copy/paste:")
    pprint(data_out, indent=2)
    assert data_out == expected
    contract.validate_out(data_out)
