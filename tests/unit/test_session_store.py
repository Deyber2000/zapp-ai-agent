"""FileSessionStore — JSON-per-session persistence so `turn` is multi-turn across processes."""

from __future__ import annotations

from pathlib import Path

from zapp_assist.memory.session_store import (
    FileSessionStore,
    PendingAction,
    SlotValue,
)


def test_persists_across_store_instances(tmp_path: Path) -> None:
    first = FileSessionStore(tmp_path)
    session = first.load("abc")
    session.active_lang = "es"
    session.slots["name"] = SlotValue(raw="Ana", canonical="Ana", valid=True)
    session.pending_action = PendingAction(name="cancel_order", params={"order_id": "A1001"})
    first.save(session)

    # A brand-new store instance (i.e. a new process) sees the persisted state.
    reloaded = FileSessionStore(tmp_path).load("abc")
    assert reloaded.active_lang == "es"
    assert reloaded.slots["name"].canonical == "Ana"
    assert reloaded.pending_action is not None and reloaded.pending_action.name == "cancel_order"


def test_unknown_id_starts_fresh(tmp_path: Path) -> None:
    loaded = FileSessionStore(tmp_path).load("never-seen")
    assert loaded.session_id == "never-seen"
    assert loaded.active_lang is None and not loaded.slots and loaded.pending_action is None


def test_session_id_is_sanitised_no_traversal(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    session = store.load("../../evil")  # path-traversal attempt
    session.active_lang = "pt"
    store.save(session)

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and files[0].parent == tmp_path  # written inside the dir, never escaped
    assert store.load("../../evil").active_lang == "pt"  # same id round-trips


def test_corrupt_file_starts_fresh(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{ not valid json", encoding="utf-8")
    loaded = FileSessionStore(tmp_path).load("bad")
    assert loaded.session_id == "bad" and loaded.active_lang is None
