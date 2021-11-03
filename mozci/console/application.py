# -*- coding: utf-8 -*-

import sys

from cleo import Application

from mozci.console.commands.push import PushCommands


def cli():
    application = Application()
    application.add(PushCommands())
    application.run()


if __name__ == "__main__":
    sys.exit(cli())
