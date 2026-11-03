# -*- coding: utf-8 -*-
from mozci import config

# The maximum number of parents or children to look for previous/next task runs,
# when the task did not run on the currently considered push.
MAX_DEPTH = config.get("maxdepth", 20)


FAILURE_CLASSES = ("not classified", "new failure not classified", "fixed by commit")
INTERMITTENT_CLASSES = (
    "intermittent",
    "autoclassified intermittent",
    "intermittent needs bugid",
)
TASK_FINAL_STATES = ("completed", "failed", "exception")
