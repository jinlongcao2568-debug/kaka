from __future__ import annotations

from storage.db import DatabaseSession, PersistedWorkItem


class WorkItemRepository:
    def __init__(self, *, session: DatabaseSession | None = None) -> None:
        self.session = session or DatabaseSession.default()

    def save(self, entry: PersistedWorkItem) -> PersistedWorkItem:
        return self.session.upsert_work_item(entry)

    def get(
        self,
        *,
        stage_scope: int,
        surface_id: str,
        primary_object_type: str,
        primary_record_id: str,
    ) -> PersistedWorkItem | None:
        return self.session.find_work_item(
            stage_scope=stage_scope,
            surface_id=surface_id,
            primary_object_type=primary_object_type,
            primary_record_id=primary_record_id,
        )

    def list(self, *, stage_scope: int | None = None) -> list[PersistedWorkItem]:
        return self.session.list_work_items(stage_scope)


__all__ = ["WorkItemRepository"]
