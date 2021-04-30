# -*- coding: utf-8 -*-

from abc import ABC, abstractproperty
from typing import Any, Dict, List, Tuple, Union

import validx
from loguru import logger

from mozci.data.contract import all_contracts
from mozci.errors import (
    ContractNotFilled,
    ContractNotFound,
    InvalidSource,
    SourcesNotFound,
)


class DataSource(ABC):
    def __init__(self) -> None:
        missing = [
            f"run_{c}"
            for c in self.supported_contracts
            if not hasattr(self, f"run_{c}")
        ]
        if missing:
            missing_str = "  \n".join(missing)
            raise InvalidSource(
                self.name.__class__.__name__,
                f"must define the following methods:\n{missing_str}",
            )

    @abstractproperty
    def name(self) -> str:
        pass

    @abstractproperty
    def supported_contracts(self) -> Tuple[str, ...]:
        pass

    def get(self, name: str, **kwargs: Any) -> Union[Dict[Any, Any], List[Any]]:
        fn = getattr(self, f"run_{name}")
        return fn(**kwargs)


class DataHandler:
    ALL_SOURCES: Dict[str, DataSource] = {}

    def __init__(self, *sources: str) -> None:
        self.sources = [self.ALL_SOURCES[sname] for sname in sources]
        logger.info(f"Sources selected, in order of priority: {sources}.")

    def get(self, name: str, **context: Any) -> Union[Dict[Any, Any], List[Any]]:
        """Given a contract, find the first registered source that supports it
        run it and return the results.

        Args:
            name (str): Name of the contract to run.
            context (dict): Context to pass into the contract as defined by `Contract.schema_in`.

        Returns:
            dict: The output of the contract as defined by `Contract.schema_out`.
        """
        if name not in all_contracts:
            raise ContractNotFound(name)

        # Validate input.
        contract = all_contracts[name]
        contract.validate_in(context)

        for src in self.sources:
            if name in src.supported_contracts:
                try:
                    result = src.get(name, **context)
                except ContractNotFilled as e:
                    logger.trace(f"{e.msg}.. trying next source.")
                    continue
                break
        else:
            raise SourcesNotFound(name, context)

        # Validate output.
        try:
            contract.validate_out(result)
        except validx.exc.SchemaError:
            print(f"Result from contract '{name}' does not conform to schema!")
            raise
        return result


def register_sources():
    from mozci.data.sources import artifact, hgmo, taskcluster, treeherder

    sources = [
        artifact.ErrorSummarySource(),
        hgmo.HGMOSource(),
        taskcluster.TaskclusterSource(),
        treeherder.TreeherderClientSource(),
        treeherder.TreeherderDBSource(),
    ]

    DataHandler.ALL_SOURCES = {src.name: src for src in sources}
    # XXX Create an alias for backwards compatibility. Remove with the next major release.
    DataHandler.ALL_SOURCES["treeherder"] = DataHandler.ALL_SOURCES["treeherder_db"]
