Configuration
-------------

Mozci looks for a configuration file in your user config dir (e.g
``~/.config/mozci/config.toml``):

The config is a `TOML`_ file, which looks something like:

.. code-block:: toml

    [mozci]
    verbose = true


List of Options
~~~~~~~~~~~~~~~

The following keys are valid config options.

cache
`````
This value allows you to set up a cache to store the results for future use.
This avoids the penalty of hitting expensive data sources.

The ``mozci`` module uses `cachy`_ to handle caching. Therefore the following stores are supported:

* database
* file system
* memcached
* redis

To enable caching, you'll need to configure at least one store using the ``cache.stores`` key.
Follow `cachy's configuration format`_ identically. In addition to the options ``cachy`` supports,
you can set the ``adr.cache.retention`` key to the time in minutes before stored queries are
invalidated.

For example:

.. code-block:: toml

    [mozci.cache]
    retention = 10080  # minutes

    [mozci.cache.stores]
    file = { driver = "file", path = "/path/to/dir/to/keep/cache" }

In addition, ``mozci`` defines several custom cache stores:

* a ``seeded-file`` store. This is the same as the "file system" store,
  except you can specify a URL to initially seed your cache on creation:

.. code-block:: toml

    [adr.cache.stores]
    file = {
        driver = "seeded-file",
        path = "/path/to/dir/to/keep/cache",
        url = "https://example.com/adr_cache.tar.gz"
    }

Supported archive formats include ``.zip``, ``.tar``, ``.tar.gz``, ``.tar.bz2`` and ``.tar.zst``.

The config also accepts a ``reseed_interval`` (in minutes) which will re-seed the cache after the
interval expires. This assumes the URL is automatically updated by some other process.

As well as an ``archive_relpath`` config, which specifies the path to the cache data "within" the
archive. Otherwise the cache data is assumed to be right at the root of the archive.

* a ``renewing-file`` store. This is the same as the "file system" store,
  except it renews items in the cache when they are retrieved.

* an ``s3`` store, which allows caching items in a S3 bucket. With this store,
  items are renewed on access like ``renewing-file``. It's suggested to use a S3 Object Expiration
  policy to clean up items which are not accessed for a long time. Example configuration:

.. code-block:: toml

    [adr.cache.stores]
    s3 = {
        driver = "s3",
        bucket = "myBucket",
        prefix = "data/adr_cache/"
    }

data_sources
````````````

Mozci can retrieve data from many different sources, e.g treeherder, taskcluster, hg.mozilla.org, etc.
Often these sources can provide the same data, but may have different runtime characteristics. For
example, some may not have realtime data, might require authentication or might take a really long
time.

You can choose which sources you want to use with this key. For example:

.. code-block:: toml

    [mozci]
    data_sources = ["treeherder_client", "taskcluster"]

The above will first try to fulfill any data requirements using the
``treeherder_client`` source. But if that source is unable to fulfill the
contract, the ``taskcluster`` source will be used as a backup.

Available sources are defined in the :class:`~mozci.data.DataHandler` class.

verbose
```````

Enable verbose mode (default: ``false``). This enables debug logging.

.. _TOML: http://github.com/toml-lang/toml
.. _cachy: https://github.com/sdispater/cachy
.. _cachy's configuration format: https://cachy.readthedocs.io/en/latest/configuration.html
