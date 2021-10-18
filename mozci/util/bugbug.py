# -*- coding: utf-8 -*-

import time

from mozci.util.req import get_session

BUGBUG_BASE_URL = "https://bugbug.herokuapp.com"
DEFAULT_API_KEY = "mozci"
DEFAULT_RETRY_TIMEOUT = 9 * 60  # seconds
DEFAULT_RETRY_INTERVAL = 10  # seconds


class BugbugTimeoutException(Exception):
    pass


def get_schedules(branch, rev):
    session = get_session()
    session.headers.update({"X-API-KEY": DEFAULT_API_KEY})

    timeout = DEFAULT_RETRY_TIMEOUT
    interval = DEFAULT_RETRY_INTERVAL
    # On try there is no fallback and pulling is slower, so we allow bugbug more
    # time to compute the results.
    # See https://github.com/mozilla/bugbug/issues/1673.
    if branch == "try":
        timeout += int(timeout / 3)

    attempts = int(round(timeout / interval))
    for _ in range(0, attempts):
        response = session.get(f"{BUGBUG_BASE_URL}/push/{branch}/{rev}/schedules")

        if response.ok and response.status_code != 202:
            return response.json()

        time.sleep(interval)

    # Reaching this code means that either the last attempt ended with an error or timed out
    response.raise_for_status()
    raise BugbugTimeoutException(
        "Timed out waiting for result from Bugbug HTTP Service"
    )
