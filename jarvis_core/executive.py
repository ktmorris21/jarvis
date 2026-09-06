import asyncio
from datetime import datetime, timezone

from .cognition import cognition
from .config import settings
from .models import Command, InterfaceEvent
from .persistence.repository import repository
from .state import state


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def send_command(command: Command) -> tuple[bool, str]:
    target = command.target
    if target:
        connection = state.interfaces.get(target)
        if connection is None:
            repository.record_action(ability=command.ability, target=target, command_id=command.command_id, data=command.data, status="not_sent")
            return False, f"Target interface '{target}' is not connected."
        if command.ability not in connection.capabilities:
            return False, f"Target '{target}' does not advertise '{command.ability}'."
        try:
            await connection.websocket.send_json(command.model_dump(mode="json"))
            repository.record_action(ability=command.ability, target=target, command_id=command.command_id, data=command.data, status="sent")
            return True, target
        except Exception:
            await state.unregister(target)
            return False, f"Target '{target}' disconnected while sending."

    for interface_id, connection in list(state.interfaces.items()):
        if command.ability not in connection.capabilities:
            continue
        try:
            await connection.websocket.send_json(command.model_dump(mode="json"))
            repository.record_action(ability=command.ability, target=interface_id, command_id=command.command_id, data=command.data, status="sent")
            return True, interface_id
        except Exception:
            await state.unregister(interface_id)
    return False, f"No connected interface advertises '{command.ability}'."


async def handle_event(event: InterfaceEvent, source: str = "unknown") -> None:
    now = utc_now()
    repository.record_event(event_type=event.event, source=source, occurred_at=event.timestamp, data=event.data)
    state.event_count += 1
    state.remember_event(event.event)

    if event.event == "USER_ACTIVE":
        was_present = state.user_present
        state.user_present = True
        state.last_user_activity = now
        state.boredom = max(0.0, state.boredom - 0.20)
        if not was_present:
            state.social_drive = min(1.0, state.social_drive + 0.35)
    elif event.event == "USER_IDLE":
        state.user_present = False
    elif event.event == "USER_SPOKE":
        state.user_present = True
        state.last_user_activity = now
        state.last_interaction = now
        state.social_drive = max(0.0, state.social_drive - 0.35)
        state.boredom = max(0.0, state.boredom - 0.25)
    elif event.event == "COMMAND_RESULT":
        state.last_command_result = event.data
        command_id = event.data.get("command_id")
        if command_id:
            repository.complete_action_by_command(command_id, event.data)

    state.persist_runtime()


async def consider_return_interaction() -> None:
    now = utc_now()
    since_interaction = (now - state.last_interaction).total_seconds() if state.last_interaction else None
    decision = await cognition.consider_user_return(
        social_drive=state.social_drive,
        boredom=state.boredom,
        seconds_since_last_interaction=since_interaction,
        recent_events=list(state.recent_events),
    )
    state.last_cognition_action = decision.action
    state.last_cognition_reason = decision.reason
    state.last_cognition_at = utc_now()

    if decision.action != "SPEAK" or not decision.speech:
        state.social_drive = max(0.0, state.social_drive - 0.10)
        state.last_interaction = utc_now()
        state.persist_runtime()
        return

    sent, _ = await send_command(Command(ability="speaker", data={"text": decision.speech}))
    if sent:
        state.last_interaction = utc_now()
        state.social_drive = 0.12
        state.boredom = max(0.0, state.boredom - 0.30)
    state.persist_runtime()


async def executive_loop() -> None:
    while True:
        await asyncio.sleep(settings.heartbeat_seconds)
        state.boredom = min(1.0, state.boredom + 0.02)
        state.social_drive = min(1.0, state.social_drive + 0.01)
        if not state.user_present or state.last_user_activity is None:
            state.persist_runtime(); continue
        seconds_since_activity = (utc_now() - state.last_user_activity).total_seconds()
        recently_interacted = state.last_interaction is not None and (utc_now() - state.last_interaction).total_seconds() < settings.social_trigger_seconds
        if seconds_since_activity < settings.heartbeat_seconds * 2.5 and state.social_drive >= 0.40 and not recently_interacted:
            await consider_return_interaction()
        else:
            state.persist_runtime()
