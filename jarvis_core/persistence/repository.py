from datetime import datetime, timezone

from sqlalchemy import desc, select

from .db import SessionLocal
from .tables import ActionRow, EntityStateRow, EventRow, GoalRow, InterfaceRow, MemoryRow


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Repository:
    def record_event(self, *, event_type: str, source: str, occurred_at: datetime, data: dict) -> str:
        row = EventRow(type=event_type, source=source, occurred_at=occurred_at, received_at=utc_now(), data=data)
        with SessionLocal() as session:
            session.add(row)
            session.commit()
            return row.id

    def recent_events(self, limit: int = 20) -> list[dict]:
        with SessionLocal() as session:
            rows = session.scalars(select(EventRow).order_by(desc(EventRow.received_at)).limit(limit)).all()
            return [{"id": r.id, "type": r.type, "source": r.source, "occurred_at": r.occurred_at.isoformat(), "data": r.data} for r in reversed(rows)]

    def upsert_state(self, entity_id: str, entity_type: str, state: dict) -> None:
        now = utc_now()
        with SessionLocal() as session:
            row = session.get(EntityStateRow, entity_id)
            if row is None:
                row = EntityStateRow(entity_id=entity_id, entity_type=entity_type, state=state, updated_at=now)
                session.add(row)
            else:
                row.entity_type = entity_type
                row.state = state
                row.updated_at = now
            session.commit()

    def get_state(self, entity_id: str) -> dict | None:
        with SessionLocal() as session:
            row = session.get(EntityStateRow, entity_id)
            return None if row is None else row.state

    def all_states(self) -> list[dict]:
        with SessionLocal() as session:
            rows = session.scalars(select(EntityStateRow).order_by(EntityStateRow.entity_id)).all()
            return [{"entity_id": r.entity_id, "entity_type": r.entity_type, "state": r.state, "updated_at": r.updated_at.isoformat()} for r in rows]

    def note_interface(self, interface_id: str, interface_type: str, capabilities: list[str]) -> None:
        now = utc_now()
        with SessionLocal() as session:
            row = session.get(InterfaceRow, interface_id)
            if row is None:
                row = InterfaceRow(interface_id=interface_id, interface_type=interface_type, capabilities=capabilities, enabled=True, first_seen_at=now, last_seen_at=now)
                session.add(row)
            else:
                row.interface_type = interface_type
                row.capabilities = capabilities
                row.last_seen_at = now
            session.commit()

    def interfaces(self) -> list[dict]:
        with SessionLocal() as session:
            rows = session.scalars(select(InterfaceRow).order_by(InterfaceRow.interface_id)).all()
            return [{"interface_id": r.interface_id, "interface_type": r.interface_type, "capabilities": r.capabilities, "enabled": r.enabled, "last_seen_at": r.last_seen_at.isoformat()} for r in rows]

    def create_goal(self, kind: str, description: str, priority: int = 50, data: dict | None = None) -> str:
        now = utc_now()
        row = GoalRow(kind=kind, description=description, priority=priority, status="active", data=data or {}, created_at=now, updated_at=now)
        with SessionLocal() as session:
            session.add(row); session.commit(); return row.id

    def goals(self, status: str | None = None) -> list[dict]:
        with SessionLocal() as session:
            stmt = select(GoalRow).order_by(desc(GoalRow.priority), GoalRow.created_at)
            if status: stmt = stmt.where(GoalRow.status == status)
            rows = session.scalars(stmt).all()
            return [{"id": r.id, "kind": r.kind, "status": r.status, "priority": r.priority, "description": r.description, "data": r.data} for r in rows]

    def record_action(self, *, ability: str, target: str | None, command_id: str | None, data: dict, status: str) -> str:
        now = utc_now()
        row = ActionRow(ability=ability, target=target, command_id=command_id, data=data, status=status, created_at=now, updated_at=now)
        with SessionLocal() as session:
            session.add(row); session.commit(); return row.id

    def complete_action_by_command(self, command_id: str, result: dict) -> None:
        with SessionLocal() as session:
            row = session.scalar(select(ActionRow).where(ActionRow.command_id == command_id).order_by(desc(ActionRow.created_at)))
            if row:
                row.status = "complete" if result.get("status") == "complete" else "failed"
                row.result = result
                row.updated_at = utc_now()
                session.commit()

    def recent_actions(self, limit: int = 20) -> list[dict]:
        with SessionLocal() as session:
            rows = session.scalars(select(ActionRow).order_by(desc(ActionRow.created_at)).limit(limit)).all()
            return [{"id": r.id, "ability": r.ability, "target": r.target, "status": r.status, "command_id": r.command_id, "data": r.data, "result": r.result, "created_at": r.created_at.isoformat()} for r in rows]

    def add_memory(self, memory_type: str, content: str, data: dict | None = None, salience: float = 0.5) -> str:
        row = MemoryRow(memory_type=memory_type, content=content, data=data or {}, salience=salience, created_at=utc_now())
        with SessionLocal() as session:
            session.add(row); session.commit(); return row.id


repository = Repository()
