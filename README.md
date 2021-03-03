[![Task Status](https://community-tc.services.mozilla.com/api/github/v1/repository/mozilla/coverage-crawler/master/badge.svg)](https://community-tc.services.mozilla.com/api/github/v1/repository/mozilla/coverage-crawler/master/latest)
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

Basic usage is to instantiate a `Push` object then start accessing properties and call methods.
For example:

```python3
from mozci.push import Push

push = Push("79041cab0cc2", branch="autoland")
print("\n".join([t.label for t in push.tasks if t.failed]))
```

This will print all the failing tasks from a given push. See the
[documentation](https://mozci.readthedocs.io/en/latest/) for more usage details and API docs.

## Contributing

Mozci uses [poetry](https://python-poetry.org/) to manage the project. So first make sure that is
installed. Then clone the repo and run:

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

There are also some integration tests that will hit live data sources. These are run in a cron task
and are excluded from the default test run. But if needed, you can run them locally via:

```bash
$ tox -e integration
```

Since `tox` installs packages on every invocation, it's much faster to run tests directly with `pytest`:

```bash
$ poetry run pytest tests
```

or

```bash
$ poetry shell
$ pytest tests
```

Additionally, you can install the `pre-commit` hooks by running:

```bash
$ pre-commit install
```

Linters and formatters will now run every time you commit.
