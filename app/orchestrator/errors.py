class CommandRejected(Exception):
    """A user command that doesn't make sense in the session's current state (HTTP 409)."""
