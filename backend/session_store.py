from dataclasses import dataclass, field
from time import time
from uuid import uuid4


@dataclass
class ChatSession:
    session_id: str
    scenario_id: str
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    def create(self, scenario_id: str = "support") -> ChatSession:
        session = ChatSession(session_id=f"session-{uuid4().hex[:12]}", scenario_id=scenario_id)
        self._sessions[session.session_id] = session
        return session

    def get_or_create(self, session_id: str, scenario_id: str = "support") -> ChatSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = ChatSession(session_id=session_id, scenario_id=scenario_id)
            self._sessions[session_id] = session
        elif session.scenario_id != scenario_id:
            session.scenario_id = scenario_id
            session.history.clear()
        session.updated_at = time()
        return session

    def reset(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.history.clear()
            session.updated_at = time()
