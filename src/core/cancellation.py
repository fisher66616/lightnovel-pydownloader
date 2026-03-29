from __future__ import annotations

from threading import Event
from typing import Optional


class TaskCancelled(Exception):
    def __init__(self, message: str = "任务已取消"):
        super().__init__(message)


def raise_if_cancelled(cancel_event: Optional[Event]):
    if cancel_event and cancel_event.is_set():
        raise TaskCancelled()
