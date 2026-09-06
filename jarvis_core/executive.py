import asyncio
from datetime import datetime, timezone

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


async def executive_loop() -> None:
    """Tiny deterministic agency loop for architectural validation."""
    while True:
        await asyncio.sleep(settings.heartbeat_seconds)

        # Artificial drives slowly rise with time.
        state.boredom = min(1.0, state.boredom + 0.02)
        state.social_drive = min(1.0, state.social_drive + 0.01)

        if not state.user_present or state.last_user_activity is None:
            continue

        seconds_since_activity = (utc_now() - state.last_user_activity).total_seconds()
        recently_interacted = (
            state.last_interaction is not None
            and (utc_now() - state.last_interaction).total_seconds() < settings.social_trigger_seconds
        )

        # POC agency: after a return, Jarvis can independently decide to speak.
        if (
            seconds_since_activity < settings.heartbeat_seconds * 2.5
            and state.social_drive >= 0.40
            and not recently_interacted
        ):
            sent = await send_to_capability(
                "speaker",
                Command(
                    ability="speak",
                    data={"text": "There you are. I was beginning to wonder where you went."},
                ),
            )
            if sent:
                state.last_interaction = utc_now()
                state.social_drive = 0.12
                state.boredom = max(0.0, state.boredom - 0.30)
