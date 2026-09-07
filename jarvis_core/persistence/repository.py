from datetime import datetime, timezone
from sqlalchemy import desc, select
from .db import SessionLocal
from .tables import ActionRow, EntityStateRow, EventRow, GoalRow, InterfaceRow, MemoryRow

def utc_now(): return datetime.now(timezone.utc)

class Repository:
    def record_event(self, *, event_type, source, occurred_at, data, importance=None):
        row=EventRow(type=event_type,source=source,occurred_at=occurred_at,received_at=utc_now(),data=data,importance=importance)
        with SessionLocal() as s: s.add(row); s.commit(); return row.id
    def recent_events(self, limit=20):
        with SessionLocal() as s:
            rows=s.scalars(select(EventRow).order_by(desc(EventRow.received_at)).limit(limit)).all()
            return [{"id":r.id,"type":r.type,"source":r.source,"occurred_at":r.occurred_at.isoformat(),"data":r.data,"importance":r.importance} for r in reversed(rows)]
    def upsert_state(self, entity_id, entity_type, state):
        now=utc_now()
        with SessionLocal() as s:
            row=s.get(EntityStateRow,entity_id)
            if row is None: s.add(EntityStateRow(entity_id=entity_id,entity_type=entity_type,state=state,updated_at=now))
            else: row.entity_type=entity_type; row.state=state; row.updated_at=now
            s.commit()
    def get_state(self, entity_id):
        with SessionLocal() as s:
            r=s.get(EntityStateRow,entity_id); return None if r is None else r.state
    def all_states(self):
        with SessionLocal() as s:
            rows=s.scalars(select(EntityStateRow).order_by(EntityStateRow.entity_id)).all()
            return [{"entity_id":r.entity_id,"entity_type":r.entity_type,"state":r.state,"updated_at":r.updated_at.isoformat()} for r in rows]
    def note_interface(self, interface_id, interface_type, capabilities):
        now=utc_now()
        with SessionLocal() as s:
            r=s.get(InterfaceRow,interface_id)
            if r is None: s.add(InterfaceRow(interface_id=interface_id,interface_type=interface_type,capabilities=capabilities,enabled=True,first_seen_at=now,last_seen_at=now))
            else: r.interface_type=interface_type; r.capabilities=capabilities; r.last_seen_at=now
            s.commit()
    def interfaces(self):
        with SessionLocal() as s:
            rows=s.scalars(select(InterfaceRow).order_by(InterfaceRow.interface_id)).all()
            return [{"interface_id":r.interface_id,"interface_type":r.interface_type,"capabilities":r.capabilities,"enabled":r.enabled,"last_seen_at":r.last_seen_at.isoformat()} for r in rows]
    def create_goal(self, kind, description, priority=50, data=None):
        now=utc_now(); row=GoalRow(kind=kind,description=description,priority=priority,status="active",data=data or {},created_at=now,updated_at=now)
        with SessionLocal() as s: s.add(row); s.commit(); return row.id
    def goals(self,status=None):
        with SessionLocal() as s:
            stmt=select(GoalRow).order_by(desc(GoalRow.priority),GoalRow.created_at)
            if status: stmt=stmt.where(GoalRow.status==status)
            rows=s.scalars(stmt).all()
            return [{"id":r.id,"kind":r.kind,"status":r.status,"priority":r.priority,"description":r.description,"data":r.data or {}} for r in rows]
    def record_action(self, *, ability,target,command_id,data,status):
        now=utc_now(); row=ActionRow(ability=ability,target=target,command_id=command_id,data=data,status=status,created_at=now,updated_at=now)
        with SessionLocal() as s: s.add(row); s.commit(); return row.id
    def complete_action_by_command(self, command_id,result):
        with SessionLocal() as s:
            r=s.scalar(select(ActionRow).where(ActionRow.command_id==command_id).order_by(desc(ActionRow.created_at)))
            if r: r.status="complete" if result.get("status")=="complete" else "failed"; r.result=result; r.updated_at=utc_now(); s.commit()
    def recent_actions(self,limit=20):
        with SessionLocal() as s:
            rows=s.scalars(select(ActionRow).order_by(desc(ActionRow.created_at)).limit(limit)).all()
            return [{"id":r.id,"ability":r.ability,"target":r.target,"status":r.status,"command_id":r.command_id,"data":r.data,"result":r.result,"created_at":r.created_at.isoformat()} for r in rows]
    def add_memory(self,memory_type,content,data=None,salience=0.5):
        r=MemoryRow(memory_type=memory_type,content=content,data=data or {},salience=salience,created_at=utc_now())
        with SessionLocal() as s: s.add(r); s.commit(); return r.id
    def memories(self,limit=50,memory_type=None):
        with SessionLocal() as s:
            stmt=select(MemoryRow)
            if memory_type: stmt=stmt.where(MemoryRow.memory_type==memory_type)
            rows=s.scalars(stmt.order_by(desc(MemoryRow.created_at)).limit(limit)).all()
            return [{"id":r.id,"memory_type":r.memory_type,"content":r.content,"data":r.data or {},"salience":r.salience,"created_at":r.created_at.isoformat()} for r in rows]
    def get_memory(self,memory_id):
        with SessionLocal() as s:
            r=s.get(MemoryRow,memory_id)
            return None if r is None else {"id":r.id,"memory_type":r.memory_type,"content":r.content,"data":r.data or {},"salience":r.salience,"created_at":r.created_at.isoformat()}

    def memory_exists_exact(self, content):
        normalized=(content or "").strip().lower()
        if not normalized: return False
        with SessionLocal() as s:
            rows=s.scalars(select(MemoryRow).order_by(desc(MemoryRow.created_at)).limit(500)).all()
            return any((r.content or "").strip().lower()==normalized for r in rows)

    def note_memories_retrieved(self,ids):
        if not ids:return
        with SessionLocal() as s:
            rows=s.scalars(select(MemoryRow).where(MemoryRow.id.in_(ids))).all()
            now=utc_now().isoformat()
            for r in rows:
                d=dict(r.data or {}); d["retrieval_count"]=int(d.get("retrieval_count",0))+1; d["last_retrieved_at"]=now; r.data=d
            s.commit()
repository=Repository()
