# -*- coding: utf-8 -*-
from pathlib import Path

from adr import sources

from mozci.configuration import config  # noqa
from mozci.util.logging import setup_logging

here = Path(__file__).parent.resolve()
sources.load_source(here)
setup_logging()
