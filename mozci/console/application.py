# -*- coding: utf-8 -*-

import sys

from cleo import Application

from mozci.console.commands.batch_execution import BatchExecutionCommands
from mozci.console.commands.check_backfills import CheckBackfillsCommand
from mozci.console.commands.decision import DecisionCommand
from mozci.console.commands.push import PushCommands


def cli():
    application = Application()
    application.add(BatchExecutionCommands())
    application.add(CheckBackfillsCommand())
    application.add(PushCommands())
    application.add(DecisionCommand())
    application.run()


if __name__ == "__main__":
    sys.exit(cli())
