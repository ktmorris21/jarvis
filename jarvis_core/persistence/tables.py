from datetime import datetime
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def new_id(prefix: str): return f"{prefix}_{uuid4().hex}"

class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda:new_id("evt"))
    type: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    importance: Mapped[float|None] = mapped_column(Float, nullable=True)

class EntityStateRow(Base):
    __tablename__ = "entity_states"
    entity_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class InterfaceRow(Base):
    __tablename__ = "interfaces"
    interface_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    interface_type: Mapped[str] = mapped_column(String(80))
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class GoalRow(Base):
    __tablename__ = "goals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda:new_id("goal"))
    kind: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True, default="active")
    priority: Mapped[int] = mapped_column(Integer, default=50)
    description: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class ActionRow(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda:new_id("act"))
    ability: Mapped[str] = mapped_column(String(100), index=True)
    target: Mapped[str|None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    command_id: Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict|None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class MemoryRow(Base):
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda:new_id("mem"))
    memory_type: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    salience: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
