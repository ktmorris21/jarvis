import asyncio
from dataclasses import dataclass,field
from datetime import datetime,timezone
from fastapi import WebSocket
from .config import settings
from .persistence.repository import repository

def utc_now(): return datetime.now(timezone.utc)
@dataclass
class InterfaceConnection:
    interface_id:str; interface_type:str; capabilities:list[str]; websocket:WebSocket; connected_at:datetime=field(default_factory=utc_now)
class JarvisState:
    def __init__(self):
        self.started_at=utc_now(); self.interfaces={}; self.user_present=False; self.last_user_activity=None; self.last_interaction=None; self.social_drive=.10; self.boredom=0; self.curiosity=.20; self.last_curiosity_action_at=None; self.last_curiosity_ability=None; self.event_count=0; self.recent_events=[]; self.last_cognition_action=None; self.last_cognition_reason=None; self.last_cognition_at=None; self.last_command_result=None; self.last_formed_memory_ids=[]; self.last_retrieved_memory_ids=[]; self.last_attention=None; self.last_context=None; self._lock=asyncio.Lock()
    def restore(self):
        u=repository.get_state("person:user") or {}; j=repository.get_state("jarvis:core") or {}; self.user_present=bool(u.get("present",False)); self.social_drive=float(j.get("social_drive",.1)); self.boredom=float(j.get("boredom",0)); self.curiosity=float(j.get("curiosity",.20)); self.last_curiosity_ability=j.get("last_curiosity_ability"); self.recent_events=[x["type"] for x in repository.recent_events(20)]
    def persist_runtime(self):
        repository.upsert_state("person:user","person",{"present":self.user_present,"last_user_activity":self.last_user_activity.isoformat() if self.last_user_activity else None,"last_interaction":self.last_interaction.isoformat() if self.last_interaction else None})
        repository.upsert_state("jarvis:core","jarvis",{"social_drive":round(self.social_drive,4),"boredom":round(self.boredom,4),"curiosity":round(self.curiosity,4),"last_curiosity_ability":self.last_curiosity_ability,"last_curiosity_action_at":self.last_curiosity_action_at.isoformat() if self.last_curiosity_action_at else None,"last_cognition_action":self.last_cognition_action,"last_cognition_reason":self.last_cognition_reason})
    async def register(self,c):
        async with self._lock:self.interfaces[c.interface_id]=c
        repository.note_interface(c.interface_id,c.interface_type,c.capabilities)
    async def unregister(self,i):
        async with self._lock:self.interfaces.pop(i,None)
    def remember_event(self,e): self.recent_events=(self.recent_events+[e])[-20:]
    async def snapshot(self):
        async with self._lock:
            return {"started_at":self.started_at.isoformat(),"live_interfaces":[{"interface_id":c.interface_id,"interface_type":c.interface_type,"capabilities":c.capabilities,"connected_at":c.connected_at.isoformat()} for c in self.interfaces.values()],"known_interfaces":repository.interfaces(),"world_state":repository.all_states(),"user_present":self.user_present,"social_drive":round(self.social_drive,3),"boredom":round(self.boredom,3),"curiosity":round(self.curiosity,3),"last_curiosity_ability":self.last_curiosity_ability,"last_curiosity_action_at":self.last_curiosity_action_at.isoformat() if self.last_curiosity_action_at else None,"recent_events":repository.recent_events(8),"active_goals":repository.goals("active"),"recent_actions":repository.recent_actions(8),"attention":{"last":self.last_attention},"context":{"last":self.last_context or repository.get_state("context:last"),"working_memory":repository.get_state("conversation:primary")},"memory":{"count":len(repository.memories(10000)),"last_formed_ids":self.last_formed_memory_ids,"last_retrieved_ids":self.last_retrieved_memory_ids,"recent":repository.memories(5)},"cognition":{"enabled":bool(settings.openai_api_key),"last_action":self.last_cognition_action,"last_reason":self.last_cognition_reason,"last_at":self.last_cognition_at.isoformat() if self.last_cognition_at else None}}
state=JarvisState()
