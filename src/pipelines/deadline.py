"""Shared deadline exception for clean pipeline cancellation."""


class RunDeadlineExceeded(Exception):
    """Raised when the current run's monotonic deadline expires."""
