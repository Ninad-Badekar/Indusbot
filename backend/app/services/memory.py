import re
from collections import defaultdict

_CONFIRMATION = re.compile(
    r"\b(done|completed|finished|i am done|i did it|i did|i'm done|im done|good to go|proceed)\b",
    re.IGNORECASE,
)

_NEGATED_CONFIRMATION = re.compile(
    r"\b(?:not|never|neither|nor|cannot|no)\s+(?:\S+\s+){0,2}(?:done|completed|finished|proceed)\b|"
    r"\w+n't\s+(?:\S+\s+){0,2}(?:done|completed|finished|proceed)\b",
    re.IGNORECASE,
)

_MAX_STEP = 8


class SessionMemory:
    def __init__(self):
        self._sessions: dict[str, list[dict]] = defaultdict(list)
        self._step: dict[str, int] = defaultdict(lambda: 1)
        self._bot_speaking: dict[str, bool] = defaultdict(bool)
        self._processing: dict[str, bool] = defaultdict(bool)
        self._completed: dict[str, bool] = defaultdict(bool)

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        self._sessions[session_id].append({"role": role, "content": content})

    def get_history(self, session_id: str) -> list[dict]:
        return self._sessions.get(session_id, [])

    def get_step(self, session_id: str) -> int:
        return self._step.get(session_id, 1)

    def advance_step(self, session_id: str) -> int:
        current = self._step.get(session_id, 1)
        if current < _MAX_STEP:
            self._step[session_id] = current + 1
        return self._step[session_id]

    def is_confirmation(self, text: str) -> bool:
        if not _CONFIRMATION.search(text):
            return False
        cleaned = _NEGATED_CONFIRMATION.sub("", text)
        return bool(_CONFIRMATION.search(cleaned))

    def set_bot_speaking(self, session_id: str, speaking: bool) -> None:
        self._bot_speaking[session_id] = speaking

    def is_bot_speaking(self, session_id: str) -> bool:
        return self._bot_speaking.get(session_id, False)

    def set_processing(self, session_id: str, processing: bool) -> None:
        self._processing[session_id] = processing

    def is_processing(self, session_id: str) -> bool:
        return self._processing.get(session_id, False)

    def mark_completed(self, session_id: str) -> None:
        self._completed[session_id] = True

    def is_completed(self, session_id: str) -> bool:
        return self._completed.get(session_id, False)

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._step.pop(session_id, None)
        self._bot_speaking.pop(session_id, None)
        self._processing.pop(session_id, None)
        self._completed.pop(session_id, None)


session_memory = SessionMemory()
