from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from .persistence.repository import repository

class Disposition(str, Enum):
    DROP = "DROP"
    PERSIST_ONLY = "PERSIST_ONLY"
    TASK_ROUTE = "TASK_ROUTE"
    EXECUTIVE = "EXECUTIVE"
    IMMEDIATE = "IMMEDIATE"

@dataclass
class AttentionDecision:
    score: float
    disposition: Disposition
    reasons: list[str] = field(default_factory=list)
    matched_goals: list[str] = field(default_factory=list)

class AttentionService:
    HIGH_FREQUENCY_NOISE = {"LIDAR_SCAN","AUDIO_LEVEL","CAMERA_FRAME","HEARTBEAT","SENSOR_TICK"}
    IMMEDIATE_EVENTS = {"EMERGENCY_STOP","COLLISION_RISK","BATTERY_CRITICAL"}
    EXECUTIVE_EVENTS = {"USER_SPOKE","USER_ACTIVE"}
    PERSIST_EVENTS = {"USER_IDLE","COMMAND_RESULT","INTERFACE_CONNECTED","INTERFACE_DISCONNECTED"}

    def evaluate(self, event_type: str, data: dict[str,Any] | None = None) -> AttentionDecision:
        data = data or {}
        reasons=[]; matched=[]

        # Goal/task relevance outranks normal boringness.
        for goal in repository.goals("active"):
            subs = set(goal.get("data",{}).get("event_subscriptions",[]))
            if event_type in subs:
                matched.append(goal["id"])
        if matched:
            return AttentionDecision(0.95,Disposition.TASK_ROUTE,["matches active goal/task subscription"],matched)

        if event_type in self.IMMEDIATE_EVENTS:
            return AttentionDecision(1.0,Disposition.IMMEDIATE,["safety/critical event"])

        if event_type in self.HIGH_FREQUENCY_NOISE:
            return AttentionDecision(0.05,Disposition.DROP,["high-frequency routine sensor traffic"])

        if event_type == "COMMAND_RESULT" and data.get("status") == "failed":
            return AttentionDecision(0.85,Disposition.EXECUTIVE,["command failure"])

        if event_type == "VISUAL_OBSERVATION":
            hint = str(data.get("attention_hint", "routine"))
            if hint == "important":
                return AttentionDecision(score=0.9, disposition=Disposition.IMMEDIATE, reasons=["vision marked important"])
            if hint == "interesting" or data.get("people_visible"):
                return AttentionDecision(score=0.65, disposition=Disposition.EXECUTIVE, reasons=["visual observation may merit attention"])
            return AttentionDecision(score=0.25, disposition=Disposition.PERSIST_ONLY, reasons=["routine visual observation"])

        if event_type == "USER_SPOKE":
            return AttentionDecision(0.90,Disposition.EXECUTIVE,["direct user communication"])
        if event_type == "USER_ACTIVE":
            return AttentionDecision(0.65,Disposition.EXECUTIVE,["user presence/return may warrant action"])
        if event_type in self.PERSIST_EVENTS:
            return AttentionDecision(0.30,Disposition.PERSIST_ONLY,["useful history/state, no executive attention required"])

        return AttentionDecision(0.40,Disposition.PERSIST_ONLY,["unknown event defaults to persistence without cognition"])

attention = AttentionService()
