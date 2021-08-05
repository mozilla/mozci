Usage Tips
==========

Below are some ways to get the best experience with ``mozci``.


Caching Results
---------------

Gathering the requisite data can sometimes be very expensive. Analyzing many pushes at once can take
hours or even days. Luckily, ``mozci`` can make use of `adr's caching mechanism`_ so once a result
is computed once, it won't be re-computed (even between runs). See the linked docs for more details,
but a basic file system cache can be set up by modifying ``~/.config/adr/config.toml`` and adding
the following:

.. code-block:: toml

    [adr.cache]
    retention = 10080  # minutes

    [adr.cache.stores]
    file = { driver = "file", path = "/path/to/cache" }


.. _adr's caching mechanism: https://active-data-recipes.readthedocs.io/en/latest/usage.html#cache


Pre-seeding the Cache via Bugbug
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There's a service called bugbug that runs ``mozci`` against all of the pushes on `autoland`_. This
service uploads its cache on S3 for others to use. You can benefit by using this uploaded cache
to "pre-seed" your own local cache, if you have the necessary scopes. To do so, add the following to your
``~/.config/mozci/config.toml``:

.. code-block:: toml

    [mozci.cache]
    serializer = "compressedpickle"

    [mozci.cache.stores]
    s3 = { driver = "s3", bucket = "communitytc-bugbug", prefix = "data/adr_cache/" }


.. _autoland: https://treeherder.mozilla.org/#/jobs?repo=autoland
