import asyncio
from datetime import datetime,timezone
from .attention import attention,Disposition
from .cognition import cognition
from .config import settings
from .memory import memory
from .models import Command,InterfaceEvent
from .persistence.repository import repository
from .state import state

def utc_now(): return datetime.now(timezone.utc)

async def send_command(command:Command):
    if command.target:
        c=state.interfaces.get(command.target)
        if c is None:
            repository.record_action(ability=command.ability,target=command.target,command_id=command.command_id,data=command.data,status="not_sent"); return False,f"Target interface '{command.target}' is not connected."
        if command.ability not in c.capabilities: return False,f"Target '{command.target}' does not advertise '{command.ability}'."
        try:
            await c.websocket.send_json(command.model_dump(mode="json")); repository.record_action(ability=command.ability,target=command.target,command_id=command.command_id,data=command.data,status="sent"); return True,command.target
        except Exception:
            await state.unregister(command.target); return False,f"Target '{command.target}' disconnected while sending."
    for iid,c in list(state.interfaces.items()):
        if command.ability not in c.capabilities: continue
        try:
            await c.websocket.send_json(command.model_dump(mode="json")); repository.record_action(ability=command.ability,target=iid,command_id=command.command_id,data=command.data,status="sent"); return True,iid
        except Exception: await state.unregister(iid)
    return False,f"No connected interface advertises '{command.ability}'."

async def handle_event(event:InterfaceEvent,source="unknown"):
    decision=attention.evaluate(event.event,event.data)
    state.last_attention={"event":event.event,"score":decision.score,"disposition":decision.disposition.value,"reasons":decision.reasons,"matched_goals":decision.matched_goals}

    # DROP is the important anti-boil-the-ocean path: no DB write, no memory, no executive.
    if decision.disposition==Disposition.DROP:
        return {"attention":state.last_attention,"persisted":False}

    enriched=dict(event.data)
    enriched["_attention"]={"score":decision.score,"disposition":decision.disposition.value,"reasons":decision.reasons,"matched_goals":decision.matched_goals}
    source_event_id=repository.record_event(event_type=event.event,source=source,occurred_at=event.timestamp,data=enriched,importance=decision.score)
    state.event_count+=1; state.remember_event(event.event)

    memory_context={}
    if event.event=="USER_ACTIVE":
        was=state.user_present; memory_context["was_present"]=was; state.user_present=True; state.last_user_activity=utc_now(); state.boredom=max(0,state.boredom-.2)
        if not was: state.social_drive=min(1,state.social_drive+.35)
    elif event.event=="USER_IDLE":
        memory_context["was_present"]=state.user_present; state.user_present=False
    elif event.event=="USER_SPOKE":
        state.user_present=True; state.last_user_activity=utc_now(); state.last_interaction=utc_now(); state.social_drive=max(0,state.social_drive-.35); state.boredom=max(0,state.boredom-.25)
    elif event.event=="COMMAND_RESULT":
        state.last_command_result=event.data; cid=event.data.get("command_id");
        if cid: repository.complete_action_by_command(cid,event.data)

    formed=memory.form_from_event(event_type=event.event,source=source,data=event.data,source_event_id=source_event_id,context=memory_context)
    if formed: state.last_formed_memory_ids=formed
    state.persist_runtime()

    # TASK_ROUTE is intentionally cheap: mark the matching goals' observation in state.
    if decision.disposition==Disposition.TASK_ROUTE:
        for gid in decision.matched_goals:
            repository.upsert_state(f"task_observation:{gid}","task_observation",{"last_event":event.event,"source":source,"data":event.data,"observed_at":utc_now().isoformat()})

    # Only events explicitly dispositioned for executive attention are allowed to trigger cognition paths.
    if decision.disposition in {Disposition.EXECUTIVE,Disposition.IMMEDIATE}:
        if event.event=="USER_ACTIVE":
            await consider_return_interaction()
    return {"attention":state.last_attention,"persisted":True}

async def consider_return_interaction():
    now=utc_now(); since=(now-state.last_interaction).total_seconds() if state.last_interaction else None
    memories=memory.retrieve("user return presence greeting prior interaction preference",limit=5); state.last_retrieved_memory_ids=[m["id"] for m in memories]
    d=await cognition.consider_user_return(social_drive=state.social_drive,boredom=state.boredom,seconds_since_last_interaction=since,recent_events=list(state.recent_events),relevant_memories=memories)
    state.last_cognition_action=d.action; state.last_cognition_reason=d.reason; state.last_cognition_at=utc_now()
    if d.action=="SPEAK" and d.speech:
        sent,_=await send_command(Command(ability="speaker",data={"text":d.speech}))
        if sent: state.last_interaction=utc_now(); state.social_drive=.12; state.boredom=max(0,state.boredom-.3)
    else:
        state.last_interaction=utc_now(); state.social_drive=max(0,state.social_drive-.1)
    state.persist_runtime()

async def executive_loop():
    while True:
        await asyncio.sleep(settings.heartbeat_seconds); state.boredom=min(1,state.boredom+.02); state.social_drive=min(1,state.social_drive+.01); state.persist_runtime()
