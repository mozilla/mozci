# -*- coding: utf-8 -*-


class BasePushException(Exception):
    def __init__(self, rev, branch, msg):
        self.rev = rev
        self.branch = branch
        self.msg = f"Error with push '{rev}' on {branch}: {msg}"


class PushNotFound(BasePushException):
    """Raised when the requested push does not exist."""

    def __init__(self, *args, **kwargs):
        kwargs["msg"] = "does not exist!"
        super(PushNotFound, self).__init__(*args, **kwargs)


class ChildPushNotFound(BasePushException):
    """Raised when a suitable child push could not be found."""

    def __init__(self, reason, *args, **kwargs):
        kwargs["msg"] = f"child push not found '{reason}'!"
        super(ParentPushNotFound, self).__init__(*args, **kwargs)


class ParentPushNotFound(BasePushException):
    """Raised when a suitable parent push could not be found."""

    def __init__(self, reason, *args, **kwargs):
        kwargs["msg"] = f"parent push not found '{reason}'!"
        super(ParentPushNotFound, self).__init__(*args, **kwargs)


class BaseTaskException(Exception):
    def __init__(self, id, label, msg):
        self.id = id
        self.label = label
        self.msg = f"Error with task '{id}' ({label}): {msg}"


class ArtifactNotFound(BaseTaskException):
    """Raised when the requested task artifact does not exist."""

    def __init__(self, artifact, *args, **kwargs):
        kwargs["msg"] = f"artifact '{artifact}' does not exist!"
        self.artifact = artifact
        super(ArtifactNotFound, self).__init__(*args, **kwargs)
