# -*- coding: utf-8 -*-

from mozci import config
from mozci.data.base import DataHandler, register_sources

register_sources()
handler = DataHandler(*config.data_sources)
