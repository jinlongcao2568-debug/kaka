from __future__ import annotations

from storage.db import DatabaseSession, PersistedOperatorAction


class OperatorActionRepository:
    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def append(self, entry: PersistedOperatorAction) -> PersistedOperatorAction:
        return self.session.append_operator_action(entry)

    def list(self, *, work_item_id: str) -> list[PersistedOperatorAction]:
        return self.session.list_operator_actions(work_item_id)


__all__ = ["OperatorActionRepository"]
