[![Build Status](https://travis-ci.org/mozilla/mozci.svg?branch=master)](https://travis-ci.org/mozilla/mozci)
[![PyPI version](https://badge.fury.io/py/mozci.svg)](https://badge.fury.io/py/mozci)
[![Docs](https://readthedocs.org/projects/mozci/badge/?version=latest)](https://mozci.readthedocs.io/en/latest/?badge=latest)

# mozci
A library for inspecting push and task results in Mozilla's CI.


## Installation

To install, run:

```bash
$ pip install mozci
```


## Usage

Basic usage is to instantiate a ``Push`` object then start accessing properties and call methods.
For example:

```python3
from mozci.push import Push

push = Push("79041cab0cc2", branch="autoland")
print("\n".join([t.label for t in push.tasks if t.failed])
```

This will print all the failing tasks from a given push. See the
[documentation](https://python-poetry.org/docs/) for more usage details and API docs.


## Contributing

Mozci uses [poetry](https://python-poetry.org/) to manage the project. So first make sure that is
installed. Then run:

```bash
$ poetry install
```

This will create a virtualenv and install both project and dev dependencies in it. See the [poetry
documentation](https://python-poetry.org/docs/) to learn how to work within the project.

To execute tests and linters, run:

```bash
$ tox
```

This should run successfully prior to submitting PRs (unless you need help figuring out the
problem).
