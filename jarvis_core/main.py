import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI,Header,HTTPException,Query,Request,WebSocket,WebSocketDisconnect,WebSocketException,status
from pydantic import ValidationError
from .config import settings
from .executive import executive_loop,handle_event,send_command
from .models import Command,DebugCommandRequest,GoalCreateRequest,InterfaceEvent,InterfaceHello,MemoryCreateRequest,MemorySearchRequest
from .persistence import init_db
from .persistence.repository import repository
from .state import InterfaceConnection,state

@asynccontextmanager
async def lifespan(app:FastAPI):
    init_db(); state.restore(); task=asyncio.create_task(executive_loop()); yield; task.cancel()
    try: await task
    except asyncio.CancelledError: pass

app=FastAPI(title="Jarvis Core v1 Audio POC",lifespan=lifespan)
@app.get("/health")
async def health(): return {"status":"ok","service":"jarvis-core","phase":"v1-audio-poc"}
@app.get("/state")
async def get_state(): return await state.snapshot()
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
    try:
        text = await audio.transcribe_wav(wav_bytes)
    except Exception as e:
        raise HTTPException(502, f"Transcription failed: {type(e).__name__}")
    if not text:
        return {"status": "no_speech", "text": ""}
    event = InterfaceEvent(event="USER_SPOKE", data={"text": text, "input_mode": "audio"})
    await handle_event(event, source=x_jarvis_interface)
    return {"status": "accepted", "text": text}

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
