# -*- coding: utf-8 -*-

from abc import ABC, abstractproperty
from typing import Any, Dict, Tuple

from mozci.data.contract import all_contracts


class DataSource(ABC):
    def __init__(self) -> None:
        missing = [
            f"run_{c}"
            for c in self.supported_contracts
            if not hasattr(self, f"run_{c}")
        ]
        if missing:
            missing_str = "  \n".join(missing)
            raise Exception(
                f"{self.__class__.__name__} must define the following methods:\n{missing_str}"
            )

    @abstractproperty
    def name(self) -> str:
        pass

    @abstractproperty
    def supported_contracts(self) -> Tuple[str, ...]:
        pass

    def get(self, name: str, **kwargs: Any) -> Dict[Any, Any]:
        fn = getattr(self, f"run_{name}")
        return fn(**kwargs)


class DataHandler:
    ALL_SOURCES: Dict[str, DataSource] = {}

    def __init__(self, *sources: str) -> None:
        self.sources = [self.ALL_SOURCES[sname] for sname in sources]

    def get(self, name: str, **context: Any) -> Dict[Any, Any]:
        """Given a contract, find the first registered source that supports it
        run it and return the results.

        Args:
            name (str): Name of the contract to run.
            context (dict): Context to pass into the contract as defined by `Contract.schema_in`.

        Returns:
            dict: The output of the contract as defined by `Contract.schema_out`.
        """
        if name not in all_contracts:
            raise Exception(f"Contract {name} does not exist!")

        # Validate input.
        contract = all_contracts[name]
        contract.validate_in(context)

        source = None
        for src in self.sources:
            if name in src.supported_contracts:
                source = src
                break
        else:
            raise Exception(f"No registered sources support {name}!")

        result = source.get(name, **context)

        # Validate output.
        contract.validate_out(result)
        return result


def register_sources():
    from mozci.data.sources import activedata, treeherder

    DataHandler.ALL_SOURCES = {
        "treeherder": treeherder.TreeherderSource(),
        "adr": activedata.ActiveDataSource(),
    }
