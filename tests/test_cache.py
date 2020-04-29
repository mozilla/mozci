# -*- coding: utf-8 -*-
import os

from adr.configuration import Configuration


def obtain_cache(config_file, contents):
    config_file.write_text(contents)
    return Configuration(path=config_file).cache


def test_cache_with_file_store(tmp_path):
    contents = (
        """
[adr]
verbose = 1
[adr.cache]
default = "file"
[adr.cache.stores]
file = { driver = "file", path = "%s" }
"""
        % tmp_path
    )
    config_path = tmp_path / "config.toml"
    cache = obtain_cache(config_path, contents)
    cache.put("foo", "bar", 5)
    assert cache.get("foo") == "bar"
    os.remove(config_path)


def test_cache_with_improper_config(tmp_path):
    contents = """
[adr]
verbose = 1
"""
    config_path = tmp_path / "config.toml"
    cache = obtain_cache(config_path, contents)
    cache.put("foo", "bar", 5)
    assert cache.get("foo") == "bar"
    os.remove(config_path)
