# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import taskcluster
import taskcluster_urls as liburls

from mozci.util import yaml
from mozci.util.req import get_session

PRODUCTION_TASKCLUSTER_ROOT_URL = "https://firefox-ci-tc.services.mozilla.com"


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
    if path.endswith(".json"):
        return response.json()
    if path.endswith(".yml"):
        return yaml.load_stream(response.text)
    return response


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
    response = _do_request(get_artifact_url(task_id, "").rstrip("/"))
    return response.json()["artifacts"]


def get_index_url(index_path):
    return liburls.api(
        PRODUCTION_TASKCLUSTER_ROOT_URL, "index", "v1", f"task/{index_path}"
    )


def find_task_id(index_path, use_proxy=False):
    response = _do_request(get_index_url(index_path))
    return response.json()["taskId"]


def get_task_url(task_id):
    return liburls.api(
        PRODUCTION_TASKCLUSTER_ROOT_URL, "queue", "v1", f"task/{task_id}"
    )


def get_task(task_id, use_proxy=False):
    response = _do_request(get_task_url(task_id))
    return response.json()


def get_tasks_in_group(group_id):
    tasks = []

    def _save_tasks(response):
        tasks.extend(response["tasks"])

    queue = taskcluster.Queue({"rootUrl": PRODUCTION_TASKCLUSTER_ROOT_URL})
    queue.listTaskGroup(group_id, paginationHandler=_save_tasks)

    return tasks
