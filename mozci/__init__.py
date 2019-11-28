from pathlib import Path

from adr import sources

here = Path(__file__).parent.resolve()
sources.load_source(here)
