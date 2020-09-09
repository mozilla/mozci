# -*- coding: utf-8 -*-
from functools import lru_cache

import requests
from requests.packages.urllib3.util.retry import Retry

# https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html#module-urllib3.util.retry
DEFAULT_RETRIES = 5
DEFAULT_BACKOFF_FACTOR = 0.1
DEFAULT_STATUS_FORCELIST = [500, 502, 503, 504]


@lru_cache(maxsize=None)
def get_session(concurrency=50):
    session = requests.Session()

    retry = Retry(
        total=DEFAULT_RETRIES,
        backoff_factor=DEFAULT_BACKOFF_FACTOR,
        status_forcelist=DEFAULT_STATUS_FORCELIST,
    )

    # Default HTTPAdapter uses 10 connections. Mount custom adapter to increase
    # that limit. Connections are established as needed, so using a large value
    # should not negatively impact performance.
    http_adapter = requests.adapters.HTTPAdapter(
        pool_connections=concurrency, pool_maxsize=concurrency, max_retries=retry
    )
    session.mount("https://", http_adapter)
    session.mount("http://", http_adapter)

    return session
