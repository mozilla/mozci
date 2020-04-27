# -*- coding: utf-8 -*-

import json

import pytest

from mozci.errors import ArtifactNotFound, TaskNotFound
from mozci.task import Task
from mozci.util.taskcluster import get_artifact_url, get_index_url


@pytest.fixture
def create_task():
    id = 0

    def inner(**kwargs):
        nonlocal id
        task = Task.create(id=id, **kwargs)
        id += 1
        return task

    return inner


def test_missing_artifacts(responses, create_task):
    artifact = "public/artifact.txt"
    task = create_task(label="foobar")

    # First we'll check the new deployment.
    responses.add(
        responses.GET, get_artifact_url(task.id, artifact), status=404,
    )

    # Then we'll check the old deployment.
    responses.add(
        responses.GET,
        get_artifact_url(task.id, artifact, old_deployment=True),
        status=404,
    )

    with pytest.raises(ArtifactNotFound):
        task.get_artifact(artifact)


def test_create(responses):
    # Creating a task with just a label doesn't work.
    with pytest.raises(TypeError):
        Task.create(label="foobar")

    # Specifying an id works with or without label.
    assert Task.create(id=1, label="foobar").label == "foobar"
    assert Task.create(id=1).label is None

    # Can also specify an index.
    index = "index.path"
    responses.add(
        responses.GET, get_index_url(index), json={"taskId": 1}, status=200,
    )
    assert Task.create(index=index, label="foobar").label == "foobar"
    assert Task.create(index=index).label is None

    # Specifying non-existent task index raises.
    responses.replace(responses.GET, get_index_url(index), status=404)
    with pytest.raises(TaskNotFound):
        Task.create(index=index)


def test_to_json():
    kwargs = {
        "id": 1,
        "label": "foobar",
        "result": "pass",
        "duration": 100,
    }
    task = Task.create(**kwargs)
    result = task.to_json()
    json.dumps(result)  # assert doesn't raise

    for k, v in kwargs.items():
        assert k in result
        assert result[k] == v


def test_configuration():
    assert (
        Task.create(
            id=1, label="test-windows7-32/debug-reftest-gpu-e10s-1"
        ).configuration
        == "test-windows7-32/debug-*-gpu-e10s"
    )
    assert (
        Task.create(
            id=1, label="test-linux1804-64/debug-mochitest-plain-gpu-e10s"
        ).configuration
        == "test-linux1804-64/debug-*-e10s"
    )
    assert (
        Task.create(
            id=1,
            label="test-macosx1014-64-shippable/opt-web-platform-tests-wdspec-headless-e10s-1",
        ).configuration
        == "test-macosx1014-64-shippable/opt-*-headless-e10s"
    )
    assert (
        Task.create(
            id=1, label="test-linux1804-64-asan/opt-web-platform-tests-e10s-3"
        ).configuration
        == "test-linux1804-64-asan/opt-*-e10s"
    )
    assert (
        Task.create(
            id=1,
            label="test-linux1804-64-qr/debug-web-platform-tests-wdspec-fis-e10s-1",
        ).configuration
        == "test-linux1804-64-qr/debug-*-fis-e10s"
    )
    assert (
        Task.create(
            id=1,
            label="test-windows7-32-shippable/opt-firefox-ui-functional-remote-e10s",
        ).configuration
        == "test-windows7-32-shippable/opt-*-e10s"
    )
