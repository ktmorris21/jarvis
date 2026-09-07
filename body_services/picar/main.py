import argparse
import asyncio
import json
from datetime import datetime, timezone

import httpx
import websockets

from .abilities import PiCarAbilities
from .audio_io import AudioIO
from .hardware import PiCarHardware


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def upload_utterance(args, audio_io):
    print(f"Listening for {args.record_seconds} seconds...")
    wav = await audio_io.record_once()
    print("Sending utterance to Jarvis Core...")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            args.url.rstrip("/") + "/audio/utterance",
            content=wav,
            headers={
                "Content-Type": "audio/wav",
                "X-Jarvis-Token": args.token,
                "X-Jarvis-Interface": args.interface_id,
            },
        )
        r.raise_for_status()
        payload = r.json()
        print("Heard:", payload.get("text") or "(no speech)")


async def console_loop(args, audio_io):
    print("Audio test ready. Type 'listen' and press Enter.")
    while True:
        command = await asyncio.to_thread(input, "> ")
        if command.strip().lower() == "listen":
            try:
                await upload_utterance(args, audio_io)
            except Exception as e:
                print("Audio capture/upload failed:", e)


async def websocket_loop(args, hw, abilities):
    while True:
        try:
            u = args.url.rstrip("/").replace("https://","wss://").replace("http://","ws://") + f"/ws?token={args.token}"
            async with websockets.connect(u) as ws:
                await ws.send(json.dumps({
                    "type":"hello",
                    "interface_id":args.interface_id,
                    "interface_type":"mobile_body",
                    "capabilities":["look","move","stop","speaker","audio_input","audio_output"],
                }))
                print("Connected:", json.loads(await ws.recv()))
                async for raw in ws:
                    m = json.loads(raw)
                    if m.get("type") != "command":
                        continue
                    cid=m.get("command_id","unknown"); ability=m.get("ability","")
                    try:
                        result=await abilities.execute(ability,m.get("data") or {})
                        status="complete"; error=None
                    except Exception as e:
                        hw.stop(); result=None; status="failed"; error=str(e)
                    await ws.send(json.dumps({
                        "type":"event","event":"COMMAND_RESULT","timestamp":now_iso(),
                        "data":{"command_id":cid,"ability":ability,"status":status,"result":result,"error":error}
                    }))
        except Exception as e:
            hw.stop()
            print("Connection lost:", e)
            await asyncio.sleep(3)


async def run(args):
    hw = PiCarHardware(args.mock)
    audio_io = AudioIO(args.audio_input, args.audio_output, args.record_seconds)
    abilities = PiCarAbilities(hw, audio_io)
    await asyncio.gather(
        websocket_loop(args, hw, abilities),
        console_loop(args, audio_io),
    )


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--url",required=True)
    p.add_argument("--token",required=True)
    p.add_argument("--interface-id",default="picar-main")
    p.add_argument("--mock",action="store_true")
    p.add_argument("--audio-input",default="plughw:2,0")
    p.add_argument("--audio-output",default="plughw:2,0")
    p.add_argument("--record-seconds",type=int,default=5)
    asyncio.run(run(p.parse_args()))
