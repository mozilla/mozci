# -*- coding: utf-8 -*-
import os
import sys

from loguru import logger

from mozci import config


class LogFormatter:
    """Formatter to handle padding of variable length module names."""

    def __init__(self):
        self.padding = 0
        self.fmt = (
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "{extra[padding]}<cyan>{name}</cyan>:<cyan>{line: <3}</cyan> - "
            "<level>{extra[prefix]}{message}</level>\n"
        )

    def format(self, record):
        length = len("{name}".format(**record))
        self.padding = max(self.padding, length)
        record["extra"]["padding"] = " " * (self.padding - length)
        record["extra"].setdefault("prefix", "")
        return self.fmt


def setup_logging():
    # Configure logging.
    logger.remove()
    if config.verbose >= 2:
        level = "TRACE"
    elif config.verbose >= 1:
        level = "DEBUG"
    else:
        level = "INFO"
    fmt = os.environ.get("LOGURU_FORMAT", LogFormatter().format)
    logger.add(sys.stderr, level=level, format=fmt)
