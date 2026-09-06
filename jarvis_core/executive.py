import asyncio
from datetime import datetime, timezone

from .cognition import cognition
from .config import settings
from .models import Command, InterfaceEvent
from .state import state


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def send_to_capability(capability: str, command: Command) -> bool:
    # Core thinks in abilities, not PiCar-specific operations.
    dead: list[str] = []
    for interface_id, connection in list(state.interfaces.items()):
        if capability not in connection.capabilities:
            continue
        try:
            await connection.websocket.send_json(command.model_dump(mode="json"))
            return True
        except Exception:
            dead.append(interface_id)

    for interface_id in dead:
        await state.unregister(interface_id)
    return False


async def handle_event(event: InterfaceEvent) -> None:
    now = utc_now()
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


async def consider_return_interaction() -> None:
    now = utc_now()
    since_interaction = (
        (now - state.last_interaction).total_seconds()
        if state.last_interaction is not None
        else None
    )

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
        # Thinking itself slightly satisfies the trigger so we don't ask the model
        # the same question every heartbeat.
        state.social_drive = max(0.0, state.social_drive - 0.10)
        state.last_interaction = utc_now()
        return

    sent = await send_to_capability(
        "speaker",
        Command(ability="speak", data={"text": decision.speech}),
    )
    if sent:
        state.last_interaction = utc_now()
        state.social_drive = 0.12
        state.boredom = max(0.0, state.boredom - 0.30)


async def executive_loop() -> None:
    """Agency loop. Deterministic logic decides WHEN cognition is warranted."""
    while True:
        await asyncio.sleep(settings.heartbeat_seconds)

        state.boredom = min(1.0, state.boredom + 0.02)
        state.social_drive = min(1.0, state.social_drive + 0.01)

        if not state.user_present or state.last_user_activity is None:
            continue

        seconds_since_activity = (utc_now() - state.last_user_activity).total_seconds()
        recently_interacted = (
            state.last_interaction is not None
            and (utc_now() - state.last_interaction).total_seconds() < settings.social_trigger_seconds
        )

        # Executive gate: the model is not the heartbeat or scheduler.
        if (
            seconds_since_activity < settings.heartbeat_seconds * 2.5
            and state.social_drive >= 0.40
            and not recently_interacted
        ):
            await consider_return_interaction()
