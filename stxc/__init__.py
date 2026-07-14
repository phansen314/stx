"""stxc — the stx daemon wire client, shared by the TUI and the CLI.

Single source of truth for talking to the daemon over HTTP. Import the client and the typed
row dataclasses from here:

    from stxc import Client, StxError, StxApiError, StxConnError
    from stxc.models import Task, Workspace, build
"""
from .client import Client, StxApiError, StxConnError, StxError
from .models import (
    Kind,
    Segment,
    Status,
    Task,
    Track,
    Transition,
    Workspace,
    build,
)

__all__ = [
    "Client",
    "StxError",
    "StxApiError",
    "StxConnError",
    "Kind",
    "Segment",
    "Status",
    "Task",
    "Track",
    "Transition",
    "Workspace",
    "build",
]
