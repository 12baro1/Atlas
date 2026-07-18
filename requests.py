"""Minimal local requests compatibility layer for offline Atlas tests."""


class Response:
    """Small response object matching the attributes used by TelegramBot."""

    def __init__(self, status_code=200, text="offline request skipped"):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 300


def post(url, data=None, timeout=None):
    """Return a successful offline response without performing network I/O."""
    return Response()
