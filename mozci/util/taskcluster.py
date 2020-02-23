# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import functools
import requests
from requests.packages.urllib3.util.retry import Retry

import taskcluster_urls as liburls
from adr.util import memoize

from mozci.util import yaml


PRODUCTION_TASKCLUSTER_ROOT_URL = 'https://firefox-ci-tc.services.mozilla.com'

# the maximum number of parallel Taskcluster API calls to make
CONCURRENCY = 50


@memoize
def get_session():
    session = requests.Session()

    retry = Retry(total=5, backoff_factor=0.1,
                  status_forcelist=[500, 502, 503, 504])

    # Default HTTPAdapter uses 10 connections. Mount custom adapter to increase
    # that limit. Connections are established as needed, so using a large value
    # should not negatively impact performance.
    http_adapter = requests.adapters.HTTPAdapter(
        pool_connections=CONCURRENCY,
        pool_maxsize=CONCURRENCY,
        max_retries=retry)
    session.mount('https://', http_adapter)
    session.mount('http://', http_adapter)

    return session


def _do_request(url, force_get=False, **kwargs):
    session = get_session()
    if kwargs and not force_get:
        response = session.post(url, **kwargs)
    else:
        response = session.get(url, stream=True, **kwargs)
    if response.status_code >= 400:
        # Consume content before raise_for_status, so that the connection can be
        # reused.
        response.content
    response.raise_for_status()
    return response


def _handle_artifact(path, response):
    if path.endswith('.json'):
        return response.json()
    if path.endswith('.yml'):
        return yaml.load_stream(response.text)
    response.raw.read = functools.partial(response.raw.read,
                                          decode_content=True)
    return response.raw


def get_artifact_url(task_id, path):
    return liburls.api(
        PRODUCTION_TASKCLUSTER_ROOT_URL,
        "queue",
        "v1",
        f"task/{task_id}/artifacts/{path}",
    )


def get_artifact(task_id, path):
    """
    Returns the artifact with the given path for the given task id.

    If the path ends with ".json" or ".yml", the content is deserialized as,
    respectively, json or yaml, and the corresponding python data (usually
    dict) is returned.
    For other types of content, a file-like object is returned.
    """
    response = _do_request(get_artifact_url(task_id, path))
    return _handle_artifact(path, response)


def list_artifacts(task_id):
    response = _do_request(get_artifact_url(task_id, '').rstrip('/'))
    return response.json()['artifacts']


def get_index_url(index_path):
    return liburls.api(PRODUCTION_TASKCLUSTER_ROOT_URL, 'index', 'v1', f'task/{index_path}')


def find_task_id(index_path, use_proxy=False):
    try:
        response = _do_request(get_index_url(index_path))
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise KeyError("index path {} not found".format(index_path))
        raise
    return response.json()['taskId']
