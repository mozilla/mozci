.. mozci documentation master file, created by
   sphinx-quickstart on Mon Mar 16 09:30:29 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Mozci
=====

Mozci is an object oriented library aimed at making it easier to analyze pushes and tasks in
Mozilla's CI system. Basic usage involves instantiating a ``Push`` object then accessing the
attributes and calling the functions to retrieve the desired data of this push. For example:

.. code-block:: python3

    from mozci.push import Push

    push = Push("79041cab0cc2", branch="autoland")
    print("\n".join([t.label for t in push.tasks if t.failed])

The above snippet prints the failed tasks for a given push. Mozci uses data from a variety of
sources, including `Active Data`_, `hg.mozilla.org`_ and `decision task`_ artifacts.

See the :doc:`API docs <api/mozci>` for more details.

.. _Active Data: https://wiki.mozilla.org/EngineeringProductivity/Projects/ActiveData
.. _hg.mozilla.org: https://hg.mozilla.org/
.. _decision task: https://firefox-source-docs.mozilla.org/taskcluster/taskgraph.html#decision-task


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   usage
   configuration
   regressions
   API <api/modules>


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
