# -*- coding: utf-8 -*-

import pytest

from mozci.errors import ArtifactNotFound
from mozci.task import Task
from mozci.util.taskcluster import get_artifact_url


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
