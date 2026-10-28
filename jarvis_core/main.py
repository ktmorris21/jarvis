import asyncio
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI,Header,HTTPException,Query,Request,WebSocket,WebSocketDisconnect,WebSocketException,status
from pydantic import ValidationError
from .config import settings
from .executive import executive_loop,handle_event,send_command
from .models import Command,DebugCommandRequest,GoalCreateRequest,InterfaceEvent,InterfaceHello,MemoryCreateRequest,MemorySearchRequest,ConversationTranscriptRequest
from .persistence import init_db
from .persistence.repository import repository
from .state import InterfaceConnection,state
from .abilities import tool_schemas, execute_tool

@asynccontextmanager
async def lifespan(app:FastAPI):
    init_db(); state.restore(); task=asyncio.create_task(executive_loop()); yield; task.cancel()
    try: await task
    except asyncio.CancelledError: pass

app=FastAPI(title="Jarvis Core v1 Cognitive Context",lifespan=lifespan)
@app.get("/health")
async def health(): return {"status":"ok","service":"jarvis-core","phase":"v1-cognitive-context"}
@app.get("/state")
async def get_state(): return await state.snapshot()

@app.get("/context")
async def get_context():
    return {
        "engine": "openai-agents-sdk",
        "session": "jarvis-primary",
        "history": "managed by the Agents SDK persistent SQLAlchemy session",
    }

@app.get("/events")
async def get_events(limit:int=50): return {"events":repository.recent_events(min(max(limit,1),200))}
@app.get("/goals")
async def get_goals(status_filter:str|None=None): return {"goals":repository.goals(status_filter)}
@app.post("/goals")
async def create_goal(req:GoalCreateRequest,x_jarvis_token:str=Header(default="")):
    if x_jarvis_token!=settings.interface_token: raise HTTPException(401,"Invalid token")
    data=dict(req.data); data["event_subscriptions"]=req.event_subscriptions
    return {"goal_id":repository.create_goal(req.kind,req.description,req.priority,data)}
@app.get("/actions")
async def get_actions(limit:int=50): return {"actions":repository.recent_actions(min(max(limit,1),200))}
@app.get("/memories")
async def get_memories(limit:int=50,memory_type:str|None=None): return {"memories":repository.memories(min(max(limit,1),200),memory_type)}
@app.post("/memories")
async def create_memory(req:MemoryCreateRequest,x_jarvis_token:str=Header(default="")):
    if x_jarvis_token!=settings.interface_token: raise HTTPException(401,"Invalid token")
    if req.memory_type!="semantic": raise HTTPException(400,"explicit creation only permits semantic memories")
    from .memory import memory
    return {"memory_id":memory.remember_semantic(req.content,tags=req.tags,salience=req.salience,source="api")}
@app.post("/memories/search")
async def search_memories(req:MemorySearchRequest,x_jarvis_token:str=Header(default="")):
    if x_jarvis_token!=settings.interface_token: raise HTTPException(401,"Invalid token")
    from .memory import memory
    return {"memories":memory.retrieve(req.query,limit=req.limit,memory_type=req.memory_type)}
@app.post("/debug/command")
async def debug_command(req:DebugCommandRequest,x_jarvis_token:str=Header(default="")):
    if x_jarvis_token!=settings.interface_token: raise HTTPException(401,"Invalid token")
    cmd=Command(target=req.target,ability=req.ability,data=req.data); sent,route=await send_command(cmd)
    if not sent: raise HTTPException(409,route)
    return {"status":"sent","command_id":cmd.command_id,"target":route,"ability":cmd.ability}

@app.post("/realtime/transcript")
async def capture_realtime_transcript(
    req: ConversationTranscriptRequest,
    x_jarvis_token: str = Header(default=""),
):
    """Persist voice turns without invoking the Agents SDK a second time.

    These are source conversation records, not curated episodic memories.
    """
    if not settings.interface_token or settings.interface_token == "change-me":
        raise HTTPException(503, "Core interface authentication is not configured")
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(401, "Invalid token")
    event_id = repository.record_conversation_turn(
        source="picar:realtime", session_id=req.session_id,
        turn_id=req.turn_id, role=req.role, text=req.text,
        input_mode="realtime_voice",
    )
    return {"stored": True, "event_id": event_id}


@app.get("/realtime/recent-conversation")
async def realtime_recent_conversation(x_jarvis_token: str = Header(default="")):
    """Return a bounded cross-session voice history; read-only, authenticated."""
    if not settings.interface_token or settings.interface_token == "change-me":
        raise HTTPException(503, "Core interface authentication is not configured")
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(401, "Invalid token")
    recent = repository.recent_conversation_turns(limit=12, hours=24)
    # Bound total context in addition to count and age. Prefer newest turns.
    selected = []
    budget = 4000
    for turn in reversed(recent):
        text = turn["text"].strip()
        if not text:
            continue
        remaining = budget - sum(len(t["text"]) for t in selected)
        if remaining <= 0:
            break
        selected.append({**turn, "text": text[:min(900, remaining)]})
    return {"turns": list(reversed(selected)), "lookback_hours": 24}


@app.post("/realtime/client-secret")
async def realtime_client_secret(x_jarvis_token: str = Header(default="")):
    """Issue a short-lived Realtime credential; never expose the permanent key."""
    if not settings.interface_token or settings.interface_token == "change-me":
        raise HTTPException(503, "Core interface authentication is not configured")
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(401, "Invalid token")
    if not settings.openai_api_key:
        raise HTTPException(503, "OpenAI key is not configured on Core")

    import httpx
    payload = {
        "expires_after": {"anchor": "created_at", "seconds": 60},
        "session": {
            "type": "realtime",
            "model": "gpt-realtime-2.1-mini",
            "audio": {"output": {"voice": "ash"}},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        raise HTTPException(502, "Could not create Realtime credential")
    # Do not log or persist the short-lived credential.
    return {"value": data["value"], "expires_at": data["expires_at"],
            "model": "gpt-realtime-2.1-mini"}


@app.get("/realtime/context")
async def realtime_context(x_jarvis_token: str = Header(default="")):
    """Read-only Core identity and instructions for the experimental voice client."""
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(401, "Invalid token")
    from .agent_runtime import baseline_context
    from pathlib import Path
    voice_path = Path(__file__).with_name("jarvis_voice.md")
    return {"instructions": baseline_context(), "voice_instructions": voice_path.read_text(encoding="utf-8").strip(), "tools": tool_schemas()}


@app.post("/realtime/tool")
async def realtime_tool(request: Request, x_jarvis_token: str = Header(default="")):
    """Strictly allowlisted, read-only Core tools for the Realtime model."""
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(401, "Invalid token")
    payload = await request.json()
    name = payload.get("name")
    args = payload.get("arguments", {})
    if not isinstance(args, dict):
        raise HTTPException(400, "Tool arguments must be an object")
    return await execute_tool(name, args)

@app.post("/audio/utterance")
async def audio_utterance(
    request: Request,
    x_jarvis_token: str = Header(default=""),
    x_jarvis_interface: str = Header(default="picar-main"),
):
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(401, "Invalid token")
    wav_bytes = await request.body()
    if not wav_bytes or len(wav_bytes) > 5_000_000:
        raise HTTPException(400, "Expected a WAV body between 1 byte and 5 MB")
    from .audio import audio
    request_start = time.perf_counter()
    try:
        text = await audio.transcribe_wav(wav_bytes)
    except Exception as e:
        raise HTTPException(502, f"Transcription failed: {type(e).__name__}")
    if not text:
        return {"status": "no_speech", "text": ""}
    event = InterfaceEvent(event="USER_SPOKE", data={"text": text, "input_mode": "audio"})
    stt_end = time.perf_counter()
    try:
        await handle_event(event, source=x_jarvis_interface)
    finally:
        request_end = time.perf_counter()
        print(
            f"[VOICE TIMING] STT+request handling: "
            f"{stt_end - request_start:.2f}s | "
            f"Core event handling incl. TTS: "
            f"{request_end - stt_end:.2f}s | "
            f"Total: {request_end - request_start:.2f}s",
            flush=True,
        )
    return {"status": "accepted", "text": text}


@app.post("/vision/frame")
async def vision_frame(
    request: Request,
    x_jarvis_token: str = Header(default=""),
    x_jarvis_interface: str = Header(default="picar-main"),
):
    if x_jarvis_token != settings.interface_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    jpeg_bytes = await request.body()
    if not jpeg_bytes or len(jpeg_bytes) > 8_000_000:
        raise HTTPException(status_code=400, detail="Expected JPEG body between 1 byte and 8 MB")

    from .vision import vision
    try:
        obs = await vision.observe_jpeg(jpeg_bytes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vision failed: {type(exc).__name__}")

    observation_data = obs.model_dump()
    state.last_visual_observation = observation_data

    event = InterfaceEvent(
        event="VISUAL_OBSERVATION",
        data={
            **observation_data,
            "input_mode": "camera_still",
        },
    )
    await handle_event(event, source=x_jarvis_interface)

    return {
        "status": "observed",
        "observation": observation_data,
    }

@app.websocket("/ws")
async def ws_endpoint(ws:WebSocket,token:str=Query(default="")):
    if token!=settings.interface_token: raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    await ws.accept(); iid=None
    try:
        hello=InterfaceHello.model_validate(await ws.receive_json()); iid=hello.interface_id
        await state.register(InterfaceConnection(iid,hello.interface_type,hello.capabilities,ws)); await ws.send_json({"type":"hello_ack","interface_id":iid,"core":"jarvis"})
        while True:
            payload=await ws.receive_json()
            try: event=InterfaceEvent.model_validate(payload)
            except ValidationError as e: await ws.send_json({"type":"error","detail":str(e)}); continue
            await handle_event(event,source=iid or "unknown")
    except WebSocketDisconnect: pass
    finally:
        if iid: await state.unregister(iid)
