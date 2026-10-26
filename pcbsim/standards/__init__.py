"""Closed-form design rules from public standards (IPC-2221, IPC-2152, IPC-2141)."""

from __future__ import annotations

from pcbsim.standards.ipc import (
    allowed_current_density,
    ipc2152_current,
    ipc2152_width,
    ipc2221_current,
)

__all__ = ["allowed_current_density", "ipc2152_current", "ipc2152_width", "ipc2221_current"]
