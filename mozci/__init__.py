# -*- coding: utf-8 -*-
from pathlib import Path

from adr import configuration
from adr.cli import setup_logging

here = Path(__file__).parent.resolve()
configuration.sources.load_source(here)
setup_logging()
