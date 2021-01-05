# -*- coding: utf-8 -*-
import os
import pickle
import shutil
import tarfile
import tempfile
import threading
from distutils.dir_util import copy_tree

import boto3
import botocore
import taskcluster
import zstandard
from cachy.contracts.store import Store
from cachy.serializers import Serializer
from cachy.stores import FileStore, NullStore  # noqa
from loguru import logger

from mozci.util.req import get_session


def extract_tar_zst(path, dest):
    import zstandard

    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        with dctx.stream_reader(f) as reader:
            with tarfile.open(mode="r|", fileobj=reader) as tar:
                tar.extractall(dest)


class SeededFileStore(FileStore):
    RESEED_KEY = "mozci:SeededFileStore:reseed"

    def __init__(self, config):
        """A FileStore instance that allows pre-seeding the cache from an archive
        downloaded from a URL.

        Example configuration:

            file = {
                driver = "seeded-file",
                path = "/path/to/cache",
                url = "https://example.com/cache.tar.gz"
            }

        Configuration can include:

            path: Path on the local file system to store the cache.
            url: Where to download the preseed data from.
            archive_relpath: Path within the archive pointing to the root of the cache data.
            reseed_interval: Time in minutes after which the data will be
                              seeded again (defaults to no reseeding).

        Supported archive formats include `.zip`, `.tar`, `.tar.gz`, `.tar.bz2` or `.tar.zst`.
        """
        self._url = config["url"]
        self._reseed_interval = config.get("reseed_interval", 0)
        self._archive_relpath = config.get("archive_relpath")

        self._session = get_session()

        kwargs = {
            "directory": config["path"],
        }
        if "hash_type" in config:
            kwargs["hash_type"] = config["hash_type"]

        super(SeededFileStore, self).__init__(**kwargs)

    def seed(self):
        """Download and extract the seed data to the cache directory."""
        logger.info(
            f"Seeding mozci cache at {self._directory} with contents from {self._url}"
        )
        self._create_cache_directory(self._directory)

        filename = self._url.split("/")[-1]
        with self._session.get(self._url, stream=True) as r:
            r.raise_for_status()

            with tempfile.TemporaryDirectory() as tempdir:
                with tempfile.NamedTemporaryFile(suffix=filename) as fh:
                    shutil.copyfileobj(r.raw, fh)

                    if filename.endswith(".tar.zst"):
                        extract_tar_zst(fh.name, tempdir)
                    else:
                        shutil.unpack_archive(fh.name, tempdir)

                path = tempdir
                if self._archive_relpath:
                    path = os.path.join(tempdir, self._archive_relpath)

                copy_tree(path, self._directory)

        # Make sure we don't reseed again for another 'reseed_interval' minutes.
        self.put(self.RESEED_KEY, False, self._reseed_interval)

    def get(self, key):
        reseed = super(SeededFileStore, self).get(self.RESEED_KEY)
        if reseed is None:
            self.seed()

        return super(SeededFileStore, self).get(key)


class RenewingFileStore(FileStore):
    def __init__(self, config, retention):
        """A FileStore instance that renews items in the cache when they are
        accessed again.
        """
        kwargs = {
            "directory": config["path"],
        }
        if "hash_type" in config:
            kwargs["hash_type"] = config["hash_type"]

        self.retention = retention

        super(RenewingFileStore, self).__init__(**kwargs)

    def get(self, key):
        value = super(RenewingFileStore, self).get(key)
        if value is None:
            return None

        self.put(key, value, self.retention)
        return value


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


def get_s3_credentials(bucket, prefix):
    auth = taskcluster.Auth(get_taskcluster_options())
    response = auth.awsS3Credentials("read-write", bucket, prefix)
    return response["credentials"]


S3_CLIENTS_LOCK = threading.Lock()
S3_CLIENTS = {}


def get_s3_client(bucket, prefix):
    with S3_CLIENTS_LOCK:
        if (bucket, prefix) not in S3_CLIENTS:
            credentials = get_s3_credentials(bucket, prefix)
            S3_CLIENTS[(bucket, prefix)] = boto3.client(
                "s3",
                aws_access_key_id=credentials["accessKeyId"],
                aws_secret_access_key=credentials["secretAccessKey"],
                aws_session_token=credentials["sessionToken"],
            )

        return S3_CLIENTS[(bucket, prefix)]


def destroy_s3_client(bucket, prefix):
    with S3_CLIENTS_LOCK:
        del S3_CLIENTS[(bucket, prefix)]


class S3Store(Store):
    def __init__(self, config):
        """A Store instance that stores items in S3."""
        self._bucket = config["bucket"]
        self._prefix = config["prefix"]

    @property
    def _client(self):
        return get_s3_client(self._bucket, self._prefix)

    def _key(self, key):
        return os.path.join(self._prefix, key)

    def _retry_if_expired(self, op):
        try:
            return op()
        except botocore.exceptions.ClientError:
            destroy_s3_client(self._bucket, self._prefix)
            return op()

    def _forget(self, key):
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))
        # Should return False if the item was not present in the cache, but we
        # don't care.
        return True

    def forget(self, key):
        return self._retry_if_expired(lambda: self._forget(key))

    def _get(self, key):
        # Copy the object onto itself to extend its expiration.
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=self._key(key))

            # Change its metadata, or Amazon will complain.
            metadata = head["Metadata"]
            metadata["id"] = "1" if "id" in metadata and metadata["id"] == "0" else "0"

            self._client.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": self._key(key)},
                Key=self._key(key),
                Metadata=metadata,
                MetadataDirective="REPLACE",
            )
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "404":
                return None
            raise

        response = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        data = response["Body"].read()
        try:
            return self.unserialize(data)
        except Exception:
            # The object is broken, let's delete it.
            self.forget(key)
            return None

    def get(self, key):
        return self._retry_if_expired(lambda: self._get(key))

    def _put(self, key, value):
        self._client.put_object(
            Body=self.serialize(value), Bucket=self._bucket, Key=self._key(key)
        )

    def put(self, key, value, minutes):
        self._retry_if_expired(lambda: self._put(key, value))


class CompressedPickleSerializer(Serializer):
    def __init__(self):
        self.compressor = zstandard.ZstdCompressor(
            level=zstandard.MAX_COMPRESSION_LEVEL
        )
        self.decompressor = zstandard.ZstdDecompressor()

    def serialize(self, data):
        return self.compressor.compress(pickle.dumps(data))

    def unserialize(self, data):
        return pickle.loads(self.decompressor.decompress(data))
