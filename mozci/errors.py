# -*- coding: utf-8 -*-


class BasePushException(Exception):
    def __init__(self, rev, branch, msg):
        self.rev = rev
        self.branch = branch
        self.msg = f"Error processing push '{rev}' on {branch}: {msg}"


class PushNotFound(BasePushException):
    """Raised when the requested push does not exist."""

    def __init__(self, *args, **kwargs):
        kwargs["msg"] = "does not exist!"
        super(PushNotFound, self).__init__(*args, **kwargs)
