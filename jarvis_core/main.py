import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, WebSocketException, status
from pydantic import ValidationError

from .config import settings
from .executive import executive_loop, handle_event
from .models import InterfaceEvent, InterfaceHello
from .state import InterfaceConnection, state


@asynccontextmanager
async def lifespan(app: FastAPI):
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
            await handle_event(event)

    except WebSocketDisconnect:
        pass
    finally:
        if interface_id:
            await state.unregister(interface_id)
