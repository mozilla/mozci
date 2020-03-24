# -*- coding: utf-8 -*-
from functools import lru_cache

import requests
from requests.packages.urllib3.util.retry import Retry


@lru_cache(maxsize=None)
def get_session(name, concurrency=50):
    session = requests.Session()

    retry = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])

    # Default HTTPAdapter uses 10 connections. Mount custom adapter to increase
    # that limit. Connections are established as needed, so using a large value
    # should not negatively impact performance.
    http_adapter = requests.adapters.HTTPAdapter(
        pool_connections=concurrency, pool_maxsize=concurrency, max_retries=retry
    )
    session.mount("https://", http_adapter)
    session.mount("http://", http_adapter)

    return session
