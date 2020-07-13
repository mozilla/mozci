# -*- coding: utf-8 -*-

from mozci import config
from mozci.data.base import DataHandler

handler = DataHandler(*config.data_sources)
