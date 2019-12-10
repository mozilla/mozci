from pathlib import Path

from adr import sources
from adr.cli import setup_logging

here = Path(__file__).parent.resolve()
sources.load_source(here)
setup_logging()
