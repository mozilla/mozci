# -*- coding: utf-8 -*-

import sys

from cleo.application import Application

from mozci.console.commands.batch_execution import (
    BatchClassificationCommand,
    BatchEvaluationCommand,
)
from mozci.console.commands.check_backfills import CheckBackfillsCommand
from mozci.console.commands.decision import DecisionCommand
from mozci.console.commands.push import (
    ClassifyCommand,
    ClassifyEvalCommand,
    ClassifyPerfCommand,
    PushTasksCommand,
)


def cli():
    application = Application()
    application.add(BatchClassificationCommand())
    application.add(BatchEvaluationCommand())
    application.add(CheckBackfillsCommand())
    application.add(ClassifyCommand())
    application.add(ClassifyEvalCommand())
    application.add(ClassifyPerfCommand())
    application.add(PushTasksCommand())
    application.add(DecisionCommand())
    application.run()


if __name__ == "__main__":
    sys.exit(cli())
