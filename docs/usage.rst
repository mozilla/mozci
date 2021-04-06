Usage Tips
==========

Below are some ways to get the best experience with ``mozci``.


Caching Results
---------------

Gathering the requisite data can sometimes be very expensive. Analyzing many pushes at once can take
hours or even days. Luckily, ``mozci`` can make use of `mozci's caching mechanism`_ so once a result
is computed once, it won't be re-computed (even between runs). See the linked docs for more details,
but a basic file system cache can be set up by modifying ``~/.config/mozci/config.toml`` and adding
the following:

.. code-block:: toml

    [mozci.cache]
    retention = 10080  # minutes

    [mozci.cache.stores]
    file = { driver = "file", path = "/path/to/cache" }


.. _mozci's caching mechanism: https://active-data-recipes.readthedocs.io/en/latest/usage.html#cache


Pre-seeding the Cache via Bugbug
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There's a service called bugbug that runs ``mozci`` against all of the pushes on `autoland`_. This
service uploads its cache publicly for others to use. You can benefit by using this uploaded cache
to "pre-seed" your own local cache. To do so, add the following to your
``~/.config/mozci/config.toml``:

.. code-block:: toml

    [mozci.cache.stores.file]
    driver = "seeded-file"
    path = "/path/to/cache"
    url = "https://s3-us-west-2.amazonaws.com/communitytc-bugbug/data/mozci_cache.tar.zst"
    archive_relpath = "data/mozci_cache"
    reseed_interval = 10080


.. _autoland: https://treeherder.mozilla.org/#/jobs?repo=autoland
