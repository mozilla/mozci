# -*- coding: utf-8 -*-
import copy
import os
from collections.abc import Mapping
from pathlib import Path

import taskcluster
from appdirs import user_config_dir
from cachy import CacheManager
from loguru import logger
from taskcluster.helper import load_secrets
from tomlkit import parse

from mozci.util.cache_stores import (
    CompressedPickleSerializer,
    NullStore,
    RenewingFileStore,
    S3Store,
    SeededFileStore,
)
from mozci.util.taskcluster import get_taskcluster_options


def merge_to(source, dest):
    """
    Merge dict and arrays (override scalar values).

    Keys from source override keys from dest, and elements from lists in source
    are appended to lists in dest.

    Args:
        source (dict): to copy from
        dest (dict): to copy to (modified in place)
    """
    for key, value in source.items():

        if key not in dest:
            dest[key] = value
            continue

        # Merge dict
        if isinstance(value, dict) and isinstance(dest[key], dict):
            merge_to(value, dest[key])
            continue

        if isinstance(value, list) and isinstance(dest[key], list):
            dest[key] = dest[key] + value
            continue

        dest[key] = value

    return dest


def flatten(d, prefix=""):
    if prefix:
        prefix += "."

    result = []
    for key, value in d.items():
        if isinstance(value, dict):
            result.extend(flatten(value, prefix=f"{prefix}{key}"))
        elif isinstance(value, (set, list)):
            vstr = "\n".join([f"    {i}" for i in value])
            result.append(f"{prefix}{key}=\n{vstr}")
        else:
            result.append(f"{prefix}{key}={value}")

    return sorted(result)


class CustomCacheManager(CacheManager):
    def __init__(self, cache_config):
        super_config = {
            k: v
            for k, v in cache_config.items()
            # We can't pass the serializer config to the CacheManager constructor,
            # as it tries to resolve it but we have not had a chance to register it
            # yet.
            if k != "serializer"
        }
        super_config.setdefault("stores", {"null": {"driver": "null"}})
        super(CustomCacheManager, self).__init__(super_config)

        for store, conf in self._config["stores"].items():
            if store != "null":
                logger.debug(f"Active cache store {store} with conf {conf}")

        self.extend("null", lambda driver: NullStore())
        self.extend("seeded-file", SeededFileStore)
        self.extend(
            "renewing-file",
            lambda config: RenewingFileStore(config, cache_config["retention"]),
        )
        self.extend("s3", S3Store)

        self.register_serializer("compressedpickle", CompressedPickleSerializer())

        # Now we can manually set the serializer we wanted.
        self._serializer = self._resolve_serializer(
            cache_config.get("serializer", "pickle")
        )


class Configuration(Mapping):
    DEFAULT_CONFIG_PATH = Path(user_config_dir("mozci")) / "config.toml"
    TASKCLUSTER_CONFIG_SECRET = os.environ.get(
        "TASKCLUSTER_CONFIG_SECRET"
    ) or os.environ.get("TASKCLUSTER_SECRET")
    DEFAULTS = {
        "merge": {
            "retriggerable-backfillable-task-names": [],
            "autoclassification": {
                "enabled": False,
                "test-suite-names": [],
                "failure-types": [],
            },
            "cache": {"retention": 1440},
        },  # minutes
        "replace": {
            "data_sources": [
                "hgmo",
                "taskcluster",
                "treeherder_client",
                "errorsummary",
                "bugbug",
            ],
            "verbose": 0,
            "tier": 2,
        },
    }

    locked = False

    def __init__(self, path=None):
        self.path = Path(
            path or os.environ.get("MOZCI_CONFIG_PATH") or self.DEFAULT_CONFIG_PATH
        )

        self._config = copy.deepcopy(self.DEFAULTS["merge"])
        if self.TASKCLUSTER_CONFIG_SECRET is not None:
            # Load configuration from Taskcluster
            self.merge(self.load_from_secret())
        elif self.path.is_file():
            # Load configuration from local file
            with open(self.path, "r") as fh:
                content = fh.read()
                self.merge(parse(content)["mozci"])
        else:
            logger.warning(f"Configuration path {self.path} is not a file.")

        for k, v in self.DEFAULTS["replace"].items():
            self._config.setdefault(k, v)

        self.cache = CustomCacheManager(self._config["cache"])
        self.locked = True

        # Check auto classification settings
        assert isinstance(self._config["autoclassification"]["enabled"], bool)
        assert isinstance(self._config["autoclassification"]["test-suite-names"], list)

        assert isinstance(self._config["retriggerable-backfillable-task-names"], list)

    def __len__(self):
        return len(self._config)

    def __iter__(self):
        return iter(self._config)

    def __getitem__(self, key):
        return self._config[key]

    def __getattr__(self, key):
        if key in vars(self):
            return vars(self)[key]
        return self.__getitem__(key)

    def __setattr__(self, key, value):
        if self.locked:
            raise AttributeError(
                "Don't set attributes directly, use `config.set(key=value)` instead."
            )
        super(Configuration, self).__setattr__(key, value)

    def set(self, **kwargs):
        """Set data on the config object."""
        self._config.update(kwargs)

    def merge(self, other):
        """Merge data into config (updates dicts and lists instead of
        overwriting them).

        Args:
            other (dict): Dictionary to merge configuration with.
        """
        merge_to(other, self._config)

    def update(self, config):
        """
        Update the configuration object with new parameters
        :param config: dict of configuration
        """
        for k, v in config.items():
            if v is not None:
                self._config[k] = v

        object.__setattr__(self, "cache", CustomCacheManager(self._config["cache"]))

    def dump(self):
        return "\n".join(flatten(self._config))

    def load_from_secret(self):
        """
        Load configuration from a Taskcluster secret
        """
        assert self.TASKCLUSTER_CONFIG_SECRET, "Missing TASKCLUSTER_CONFIG_SECRET"
        logger.info(
            f"Loading configuration from secret {self.TASKCLUSTER_CONFIG_SECRET}"
        )

        return load_secrets(
            secrets_service=taskcluster.Secrets(get_taskcluster_options()),
            secret_name=self.TASKCLUSTER_CONFIG_SECRET,
        )


config = Configuration()
