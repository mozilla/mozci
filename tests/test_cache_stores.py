# -*- coding: utf-8 -*-

import copy
import platform
import time
from pathlib import Path

import boto3
import botocore
import pytest
import responses

import mozci
from mozci.util.cache_stores import RenewingFileStore, S3Store, SeededFileStore

here = Path(__file__).resolve().parent
IS_WINDOWS = "windows" in platform.system().lower()


@pytest.fixture
def archive_response():
    archive_dir = here / "files" / "cache_archives"

    def callback(resp):
        resp.callback_processd = True

        name = resp.url.split("/")[-1]
        fh = open(archive_dir / name, "rb")
        resp.raw = fh

        return resp

    with responses.RequestsMock(response_callback=callback) as rsps:
        yield rsps


@pytest.mark.parametrize("archive_name", ["cache.tar"])
@pytest.mark.skipif(IS_WINDOWS, reason="Does not pass on windows")
def test_seeded_file_store_download_and_extract(tmpdir, archive_response, archive_name):
    archive_response.add(responses.GET, f"https://example.com/{archive_name}")

    path = tmpdir.mkdir("cache")
    config = {
        "path": path.strpath,
        "url": f"https://example.com/{archive_name}",
        "reseed_interval": 1440,
        "archive_relpath": "cache",
    }
    fs = SeededFileStore(config)
    assert fs.get("foo") is None
    assert path.join("foo").check()
    assert path.join("bar").check()


def test_renewing_file_store(tmpdir, monkeypatch):
    path = tmpdir.mkdir("cache")
    config = {
        "path": path.strpath,
    }
    fs = RenewingFileStore(config, 1)

    cur_time = time.time()

    def mock_time():
        return cur_time

    monkeypatch.setattr(time, "time", mock_time)

    # The cache is empty at first.
    assert fs.get("foo") is None

    # Store an element in the cache with a retention of one minute.
    fs.put("foo", "bar", 1)
    assert fs.get("foo") == "bar"

    # Mock time to make the cache think one minute has passed.
    cur_time += 60

    # The item expired, so it won't be in the cache anymore.
    assert fs.get("foo") is None

    # Store an element in the cache with a retention of one minute.
    fs.put("foo", "bar", 1)
    assert fs.get("foo") == "bar"

    # Mock time to make the cache think thirty seconds have passed.
    cur_time += 30

    # The item is still in the cache, since only thirty seconds have passed.
    assert fs.get("foo") == "bar"

    # Mock time to make the cache think fourty-five seconds have passed.
    cur_time += 45

    # The item is still in the cache, as we renewed its expiration when we
    # accessed it after 30 seconds.
    assert fs.get("foo") == "bar"

    # Mock time to make the cache think one minute has passed.
    cur_time += 60

    # The item expired, so it won't be in the cache anymore.
    assert fs.get("foo") is None


def test_s3_store(monkeypatch):
    s3_data = {}
    s3_metadata = {}
    copy_calls = 0
    get_credentials_calls = 0
    delete_calls = 0
    expire_token = False

    def mock_client(t, aws_access_key_id, aws_secret_access_key, aws_session_token):
        assert t == "s3"
        assert aws_access_key_id == "aws_access_key_id"
        assert aws_secret_access_key == "aws_secret_access_key"
        assert aws_session_token == "aws_session_token"

        class Response:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

        class Client:
            def head_object(self, Bucket, Key):
                nonlocal s3_data, s3_metadata, expire_token
                assert Bucket == "myBucket"
                assert Key == "data/mozci_cache/foo"

                if expire_token:
                    expire_token = False
                    raise botocore.exceptions.ClientError(
                        {"Error": {"Code": "ExpiredToken"}}, "HeadObject"
                    )

                if (Bucket, Key) in s3_data:
                    if (Bucket, Key) in s3_metadata:
                        return {"Metadata": copy.deepcopy(s3_metadata[(Bucket, Key)])}
                    else:
                        return {"Metadata": {}}
                else:
                    raise botocore.exceptions.ClientError(
                        {"Error": {"Code": "404"}}, "head"
                    )

            def put_object(self, Body, Bucket, Key):
                nonlocal s3_data
                assert Bucket == "myBucket"
                assert Key == "data/mozci_cache/foo"
                s3_data[(Bucket, Key)] = Body

            def copy_object(self, Bucket, CopySource, Key, Metadata, MetadataDirective):
                nonlocal s3_metadata, copy_calls
                assert Bucket == "myBucket"
                assert Key == "data/mozci_cache/foo"
                assert CopySource["Bucket"] == "myBucket"
                assert CopySource["Key"] == "data/mozci_cache/foo"
                if (Bucket, Key) in s3_metadata:
                    assert Metadata != s3_metadata[(Bucket, Key)]
                assert MetadataDirective == "REPLACE"
                s3_metadata[(Bucket, Key)] = copy.deepcopy(Metadata)

                copy_calls += 1

            def get_object(self, Bucket, Key):
                nonlocal s3_data
                assert Bucket == "myBucket"
                assert Key == "data/mozci_cache/foo"
                return {"Body": Response(s3_data[(Bucket, Key)])}

            def delete_object(self, Bucket, Key):
                nonlocal delete_calls
                assert Bucket == "myBucket"
                assert Key == "data/mozci_cache/foo"

                del s3_data[(Bucket, Key)]
                del s3_metadata[(Bucket, Key)]

                delete_calls += 1

                return {}

        return Client()

    monkeypatch.setattr(boto3, "client", mock_client)

    def mock_get_s3_credentials(bucket, prefix):
        nonlocal get_credentials_calls
        get_credentials_calls += 1

        assert bucket == "myBucket"
        assert prefix == "data/mozci_cache/"
        return {
            "accessKeyId": "aws_access_key_id",
            "secretAccessKey": "aws_secret_access_key",
            "sessionToken": "aws_session_token",
        }

    monkeypatch.setattr(
        mozci.util.cache_stores, "get_s3_credentials", mock_get_s3_credentials
    )

    config = {
        "bucket": "myBucket",
        "prefix": "data/mozci_cache/",
    }
    fs = S3Store(config)

    assert get_credentials_calls == 0

    # The cache is empty at first.
    assert fs.get("foo") is None
    assert get_credentials_calls == 1

    # Store an element in the cache.
    fs.put("foo", "bar", 1)
    assert fs.get("foo") == "bar"
    assert copy_calls == 1
    assert get_credentials_calls == 1

    # Ensure we update the metadata to renew the item expiration.
    assert fs.get("foo") == "bar"
    assert copy_calls == 2
    assert get_credentials_calls == 1

    # Re-request AWS credentials if they expired.
    expire_token = True
    assert fs.get("foo") == "bar"
    assert copy_calls == 3
    assert get_credentials_calls == 2

    # Delete object if the stored data is broken.
    s3_data[("myBucket", "data/mozci_cache/foo")] = "goo"
    assert fs.get("foo") is None
    assert delete_calls == 1

    # Store an element in the cache.
    fs.put("foo", "bar", 1)
    assert fs.get("foo") == "bar"
    assert copy_calls == 5
    assert get_credentials_calls == 2

    # Forget an element.
    fs.forget("foo")
    assert delete_calls == 2
    assert fs.get("foo") is None
