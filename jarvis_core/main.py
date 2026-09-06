import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, WebSocketException, status
from pydantic import ValidationError

from .config import settings
from .executive import executive_loop, handle_event, send_command
from .models import Command, DebugCommandRequest, InterfaceEvent, InterfaceHello
from .state import InterfaceConnection, state
from .persistence import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    state.restore()
    task = asyncio.create_task(executive_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Jarvis Core POC", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "jarvis-core"}


@app.get("/state")
async def get_state():
    return await state.snapshot()


@app.post("/debug/command")
async def debug_command(
    request: DebugCommandRequest,
    x_jarvis_token: str = Header(default=""),
):
    """POC-only manual capability exerciser. Delete when no longer useful."""
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    command = Command(
        target=request.target,
        ability=request.ability,
        data=request.data,
    )
    sent, route = await send_command(command)
    if not sent:
        raise HTTPException(status_code=409, detail=route)
    return {
        "status": "sent",
        "command_id": command.command_id,
        "target": route,
        "ability": command.ability,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    if token != settings.interface_token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    await websocket.accept()
    interface_id: str | None = None

    try:
        first = await websocket.receive_json()
        hello = InterfaceHello.model_validate(first)
        interface_id = hello.interface_id

        await state.register(
            InterfaceConnection(
                interface_id=hello.interface_id,
                interface_type=hello.interface_type,
                capabilities=hello.capabilities,
                websocket=websocket,
            )
        )

        await websocket.send_json({
            "type": "hello_ack",
            "interface_id": interface_id,
            "core": "jarvis",
        })

        while True:
            payload = await websocket.receive_json()
            try:
                event = InterfaceEvent.model_validate(payload)
            except ValidationError as exc:
                await websocket.send_json({"type": "error", "detail": str(exc)})
                continue
            await handle_event(event, source=interface_id or "unknown")

    except WebSocketDisconnect:
        pass
    finally:
        if interface_id:
            await state.unregister(interface_id)

@app.get("/events")
async def get_events(limit: int = 50):
    from .persistence.repository import repository
    return {"events": repository.recent_events(min(max(limit, 1), 200))}


@app.get("/goals")
async def get_goals(status_filter: str | None = None):
    from .persistence.repository import repository
    return {"goals": repository.goals(status_filter)}


@app.get("/actions")
async def get_actions(limit: int = 50):
    from .persistence.repository import repository
    return {"actions": repository.recent_actions(min(max(limit, 1), 200))}
