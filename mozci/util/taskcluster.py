# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import os
from urllib.parse import urlencode

import markdown2
import taskcluster
import taskcluster_urls as liburls
from loguru import logger

from mozci.util import yaml
from mozci.util.req import get_session

PRODUCTION_TASKCLUSTER_ROOT_URL = "https://firefox-ci-tc.services.mozilla.com"
queue = taskcluster.Queue({"rootUrl": PRODUCTION_TASKCLUSTER_ROOT_URL})
COMMUNITY_TASKCLUSTER_ROOT_URL = "https://community-tc.services.mozilla.com"


def _do_request(url, force_get=False, use_put=False, **kwargs):
    session = get_session()
    if kwargs and not force_get:
        if not use_put:
            response = session.post(url, **kwargs)
        else:
            response = session.put(url, **kwargs)
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


def get_artifact_url(task_id, path, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    return liburls.api(
        root_url,
        "queue",
        "v1",
        f"task/{task_id}/artifacts/{path}",
    )


def get_artifact(task_id, path, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    """
    Returns the artifact with the given path for the given task id.

    If the path ends with ".json" or ".yml", the content is deserialized as,
    respectively, json or yaml, and the corresponding python data (usually
    dict) is returned.
    For other types of content, a file-like object is returned.
    """
    response = _do_request(get_artifact_url(task_id, path, root_url=root_url))

    return _handle_artifact(path, response)


def list_artifacts(task_id):
    return queue.listLatestArtifacts(task_id)["artifacts"]


def get_index_url(index_path, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    return liburls.api(
        root_url,
        "index",
        "v1",
        f"task/{index_path}",
    )


def find_task_id(index_path, use_proxy=False, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    response = _do_request(get_index_url(index_path, root_url=root_url))
    return response.json()["taskId"]


def index_current_task(
    index_path,
    rank=0,
    expires=None,
    data={},
    root_url=PRODUCTION_TASKCLUSTER_ROOT_URL,
):
    if expires is None:
        expires = datetime.datetime.now() + datetime.timedelta(days=1 * 365)

    index_service = taskcluster.Index(get_taskcluster_options())
    index_service.insertTask(
        index_path,
        {
            "data": data,
            "expires": expires,
            "rank": rank,
            "taskId": os.environ["TASK_ID"],
        },
    )


def get_indexed_tasks_url(namespace, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    return liburls.api(
        root_url,
        "index",
        "v1",
        f"tasks/{namespace}",
    )


def list_indexed_tasks(namespace, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    url = get_indexed_tasks_url(namespace, root_url=root_url)
    token = False
    # Support pagination using continuation token
    while token is not None:
        extra_params = "?" + urlencode({"continuationToken": token}) if token else ""
        results = _do_request(url + extra_params).json()
        yield from results.get("tasks", [])
        token = results.get("continuationToken")


def get_task_url(task_id):
    return liburls.api(
        PRODUCTION_TASKCLUSTER_ROOT_URL, "queue", "v1", f"task/{task_id}"
    )


def get_task(task_id, use_proxy=False):
    return queue.task(task_id)


def get_dependent_tasks_url(task_id, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    return liburls.api(root_url, "queue", "v1", f"task/{task_id}/dependents")


def list_dependent_tasks(task_id, root_url=PRODUCTION_TASKCLUSTER_ROOT_URL):
    url = get_dependent_tasks_url(task_id, root_url=root_url)
    token = False
    # Support pagination using continuation token
    while token is not None:
        extra_params = "?" + urlencode({"continuationToken": token}) if token else ""
        results = _do_request(url + extra_params).json()
        yield from results.get("tasks", [])
        token = results.get("continuationToken")


def create_task(task_id, task):
    options = taskcluster.optionsFromEnvironment()
    options["rootUrl"] = PRODUCTION_TASKCLUSTER_ROOT_URL
    queue = taskcluster.Queue(options)
    return queue.createTask(task_id, task)


def get_tasks_in_group(group_id):
    tasks = []

    def _save_tasks(response):
        tasks.extend(response["tasks"])

    queue.listTaskGroup(group_id, paginationHandler=_save_tasks)

    return tasks


def get_taskcluster_options():
    """
    Helper to get the Taskcluster setup options
    according to current environment (local or Taskcluster)
    """
    options = taskcluster.optionsFromEnvironment()
    proxy_url = os.environ.get("TASKCLUSTER_PROXY_URL")

    if proxy_url is not None:
        # Always use proxy url when available
        options["rootUrl"] = proxy_url

    if "rootUrl" not in options:
        # Always have a value in root url
        options["rootUrl"] = "https://community-tc.services.mozilla.com"

    return options


def notify_email(subject, content, emails):
    """
    Send an email to all provided email addresses
    using Taskcluster notify service
    """
    if not emails:
        logger.warning("No email address available in configuration")
        return

    notify_service = taskcluster.Notify(get_taskcluster_options())
    for idx, email in enumerate(emails):
        try:
            notify_service.email(
                {
                    "address": email,
                    "subject": f"Mozci | {subject}",
                    "content": content,
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to send the report by email to address n°{idx} ({email}): {e}"
            )
            raise


def notify_matrix(body, room):
    """
    Send a message on the provided Matrix room
    using Taskcluster notify service
    """
    if not room:
        logger.warning("No Matrix room available in configuration")
        return

    formatted_body = markdown2.markdown(body)

    notify_service = taskcluster.Notify(get_taskcluster_options())
    try:
        notify_service.matrix(
            {
                "roomId": room,
                "body": body,
                "format": "org.matrix.custom.html",
                "formattedBody": formatted_body,
                "msgtype": "m.text",
            }
        )
    except Exception as e:
        logger.error(f"Failed to send the report on the Matrix room {room}: {e}")
        raise
