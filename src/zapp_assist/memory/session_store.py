"""Session state behind a swappable interface (Constitution I: Scalability).

In-memory now; the `SessionStore` protocol lets this be replaced by Redis/DB with no node changes.
`load`/`save` exchange deep copies so stored state is never mutated by an in-flight turn.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

PendingStatus = Literal["awaiting_confirmation", "confirmed", "executed", "abandoned"]


class SlotValue(BaseModel):
    """A collected onboarding field (deepened by US2)."""

    raw: str
    canonical: str | None = None
    valid: bool = False


class TurnRef(BaseModel):
    """A bounded record of a prior turn, for multi-turn coherence."""

    user_text: str
    reply: str
    intent: str | None = None


class PendingAction(BaseModel):
    """A state-changing operation awaiting HITL confirmation (deepened by US3)."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    status: PendingStatus = "awaiting_confirmation"


class Session(BaseModel):
    """Conversation-scoped state carried across turns (FR-014/015)."""

    session_id: str
    active_lang: str | None = None
    # Sustained-switch accumulator (002): a candidate new language and how many consecutive
    # confident turns have supported it. Reset whenever a turn matches active_lang or is weak.
    pending_switch_lang: str | None = None
    pending_switch_count: int = 0
    slots: dict[str, SlotValue] = Field(default_factory=dict)
    pending_action: PendingAction | None = None
    history: list[TurnRef] = Field(default_factory=list)


@runtime_checkable
class SessionStore(Protocol):
    def load(self, session_id: str) -> Session: ...
    def save(self, session: Session) -> None: ...


class InMemorySessionStore:
    """Process-local session store (the default). Swappable for Redis/DB."""

    def __init__(self) -> None:
        self._data: dict[str, Session] = {}

    def load(self, session_id: str) -> Session:
        existing = self._data.get(session_id)
        if existing is None:
            fresh = Session(session_id=session_id)
            self._data[session_id] = fresh
            return fresh.model_copy(deep=True)
        return existing.model_copy(deep=True)

    def save(self, session: Session) -> None:
        self._data[session.session_id] = session.model_copy(deep=True)
