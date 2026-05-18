import asyncio
from dataclasses import dataclass, field
from typing import Callable

from fastapi import WebSocket


@dataclass
class ActiveCall:
    session_id: str
    call_sid: str
    websocket: WebSocket | None = None
    stream_sid: str | None = None
    is_active: Callable[[], bool] = field(default=lambda: True)
    pipeline_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_processed_at: float = 0.0


class CallRegistry:
    def __init__(self) -> None:
        self._by_call_sid: dict[str, ActiveCall] = {}

    def register(self, call: ActiveCall) -> None:
        self._by_call_sid[call.call_sid] = call

    def register_pending(self, call_sid: str, session_id: str) -> ActiveCall:
        call = self._by_call_sid.get(call_sid)
        if call is None:
            call = ActiveCall(session_id=session_id, call_sid=call_sid)
            self._by_call_sid[call_sid] = call
        else:
            call.session_id = session_id
        return call

    def attach_stream(
        self,
        call_sid: str,
        websocket: WebSocket,
        stream_sid: str | None,
        is_active: Callable[[], bool],
    ) -> ActiveCall | None:
        call = self._by_call_sid.get(call_sid)
        if call is None:
            call = ActiveCall(session_id=call_sid, call_sid=call_sid)
            self._by_call_sid[call_sid] = call
        call.websocket = websocket
        call.stream_sid = stream_sid
        call.is_active = is_active
        return call

    def get(self, call_sid: str) -> ActiveCall | None:
        return self._by_call_sid.get(call_sid)

    def unregister(self, call_sid: str) -> None:
        self._by_call_sid.pop(call_sid, None)


call_registry = CallRegistry()
