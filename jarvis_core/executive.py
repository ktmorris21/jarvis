import asyncio
from uuid import uuid4
from datetime import datetime,timezone
from .attention import attention,Disposition
from .audio import audio
from .config import settings
from .memory import memory
from .models import Command,InterfaceEvent
from .persistence.repository import repository
from .state import state

def utc_now(): return datetime.now(timezone.utc)

def record_self_action_event(command:Command,routed_target=None):
    event_type="JARVIS_SPOKE" if command.ability=="speaker" else "JARVIS_ACTED"
    data={"ability":command.ability,"target":routed_target or command.target,"command_id":command.command_id,"data":command.data}
    source_event_id=repository.record_event(event_type=event_type,source="jarvis:core",occurred_at=utc_now(),data=data,importance=.8 if event_type=="JARVIS_SPOKE" else .5)
    formed=memory.form_from_event(event_type=event_type,source="jarvis:core",data=data,source_event_id=source_event_id,context={})
    if formed: state.last_formed_memory_ids=formed
    return source_event_id

async def send_command(command:Command):
    if command.target:
        c=state.interfaces.get(command.target)
        if c is None:
            repository.record_action(ability=command.ability,target=command.target,command_id=command.command_id,data=command.data,status="not_sent"); return False,f"Target interface '{command.target}' is not connected."
        if command.ability not in c.capabilities: return False,f"Target '{command.target}' does not advertise '{command.ability}'."
        try:
            await c.websocket.send_json(command.model_dump(mode="json")); repository.record_action(ability=command.ability,target=command.target,command_id=command.command_id,data=command.data,status="sent"); record_self_action_event(command,command.target); return True,command.target
        except Exception:
            await state.unregister(command.target); return False,f"Target '{command.target}' disconnected while sending."
    for iid,c in list(state.interfaces.items()):
        if command.ability not in c.capabilities: continue
        try:
            await c.websocket.send_json(command.model_dump(mode="json")); repository.record_action(ability=command.ability,target=iid,command_id=command.command_id,data=command.data,status="sent"); record_self_action_event(command,iid); return True,iid
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
        state.curiosity=max(0,state.curiosity-.15); state.user_present=True; state.last_user_activity=utc_now(); state.last_interaction=utc_now(); state.social_drive=max(0,state.social_drive-.35); state.boredom=max(0,state.boredom-.25)
    elif event.event=="VISUAL_OBSERVATION":
        state.curiosity=max(0,state.curiosity-.20)
    elif event.event=="COMMAND_RESULT":
        state.last_command_result=event.data; cid=event.data.get("command_id");
        if cid: repository.complete_action_by_command(cid,event.data)
        from .agent_runtime import deliver_status_result
        if source == "picar-ros":
            deliver_status_result(event.data)
        # ROS status is operational world state, not long-term memory.
        connection = state.interfaces.get(source)
        if (connection is not None
                and connection.interface_type == "ros_status"
                and event.data.get("ability") == "get_robot_status"
                and event.data.get("status") == "complete"
                and isinstance(event.data.get("result"), dict)):
            result = event.data["result"]
            if result.get("robot_id") and result.get("observed_at"):
                repository.upsert_state(
                    f"robot_status:{source}", "robot_status",
                    {"source": source, "received_at": utc_now().isoformat(), **result},
                )

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
            # Presence updates state; no secondary cognition pathway.
            pass
        elif event.event=="USER_SPOKE" and event.data.get("text"):
            await respond_to_user_speech(event.data["text"], source)
    return {"attention":state.last_attention,"persisted":True}


async def respond_to_user_speech(text: str, source: str):
    """Agents SDK is the only conversational engine; errors stay visible."""
    # Keep Core's interface-neutral transcript separate from SDK session history.
    # The SDK still manages reasoning turns, tools and persistent agent state.
    try:
        repository.record_conversation_turn(
            source=source + ":agents", session_id="jarvis-primary",
            turn_id=uuid4().hex, role="user", text=text, input_mode="text",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not record desktop user turn")

    try:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from .agent_runtime import agent_reply
        reply = await agent_reply(text)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Agent conversation failed")
        reply = "My OpenAI agent is unavailable. Please check my Core logs; I did not use a backup cognition system."
    try:
        repository.record_conversation_turn(
            source=source + ":agents", session_id="jarvis-primary",
            turn_id=uuid4().hex, role="assistant", text=reply, input_mode="text",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not record desktop assistant turn")
    await deliver_agent_speech(reply, source)


async def deliver_agent_speech(reply: str, source: str):
    connection = state.interfaces.get(source)
    data = {"text": reply}
    if connection and "audio_output" in connection.capabilities:
        try:
            data["audio_wav_base64"] = await audio.synthesize_wav_base64(reply)
        except Exception:
            pass
    target = source if connection and ("speaker" in connection.capabilities or "audio_output" in connection.capabilities) else None
    await send_command(Command(target=target, ability="speaker", data=data))
    state.last_interaction = utc_now()
    state.persist_runtime()



def _curiosity_body():
    """Return any connected mobile body capable of curiosity actions."""
    for iid, connection in state.interfaces.items():
        if connection.interface_type != "mobile_body":
            continue
        if "look_around" in connection.capabilities or "move" in connection.capabilities:
            return iid, connection
    return None, None


async def maybe_explore_from_curiosity():
    """Initiate one tiny exploratory behavior when Jarvis is idle."""
    now = utc_now()

    if not settings.autonomous_curiosity_enabled:
        return False
    if state.curiosity < settings.curiosity_trigger:
        return False

    # Goal-directed behavior outranks idle curiosity.
    if repository.goals("active"):
        return False

    if state.last_curiosity_action_at is not None:
        elapsed = (now - state.last_curiosity_action_at).total_seconds()
        if elapsed < settings.curiosity_cooldown_seconds:
            return False

    interface_id, body = _curiosity_body()
    if not body:
        return False

    # Alternate head exploration and tiny motion when possible.
    if state.last_curiosity_ability != "look_around" and "look_around" in body.capabilities:
        command = Command(
            target=interface_id,
            ability="look_around",
            data={"amplitude_deg": 28, "pause_ms": 350},
        )
    elif "move" in body.capabilities:
        command = Command(
            target=interface_id,
            ability="move",
            data={
                "direction": "forward",
                "speed": 18,
                "duration_ms": 350,
                "steering_deg": 0,
            },
        )
    elif "look_around" in body.capabilities:
        command = Command(
            target=interface_id,
            ability="look_around",
            data={"amplitude_deg": 28, "pause_ms": 350},
        )
    else:
        return False

    sent, _ = await send_command(command)
    if sent:
        state.last_curiosity_action_at = now
        state.last_curiosity_ability = command.ability
        state.curiosity = 0.18
        state.persist_runtime()
        return True

    return False


async def executive_loop():
    while True:
        await asyncio.sleep(settings.heartbeat_seconds)
        state.boredom = min(1.0, state.boredom + 0.02)
        state.social_drive = min(1.0, state.social_drive + 0.01)
        state.curiosity = min(
            1.0,
            state.curiosity + settings.curiosity_increment,
        )
        await maybe_explore_from_curiosity()
        state.persist_runtime()
