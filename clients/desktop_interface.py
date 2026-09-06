import argparse
import asyncio
import json
from datetime import datetime, timezone

import websockets


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def receiver(ws):
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("type") == "command" and msg.get("ability") == "speak":
            print(f"\nJARVIS: {msg['data'].get('text', '')}\n> ", end="", flush=True)
        else:
            print(f"\n[CORE] {msg}\n> ", end="", flush=True)


async def send_event(ws, event: str, data: dict | None = None):
    await ws.send(json.dumps({
        "type": "event",
        "event": event,
        "data": data or {},
        "timestamp": now_iso(),
    }))


async def interactive(ws):
    print("Commands: active | idle | say <text> | help | quit")
    print("Try: idle, wait a bit, then active. Core may independently greet you.")
    while True:
        cmd = await asyncio.to_thread(input, "> ")
        cmd = cmd.strip()
        if not cmd:
            continue
        if cmd == "quit":
            return
        if cmd == "help":
            print("active = USER_ACTIVE, idle = USER_IDLE, say TEXT = USER_SPOKE")
        elif cmd == "active":
            await send_event(ws, "USER_ACTIVE")
        elif cmd == "idle":
            await send_event(ws, "USER_IDLE")
        elif cmd.startswith("say "):
            text = cmd[4:].strip()
            await send_event(ws, "USER_SPOKE", {"text": text})
        else:
            print("Unknown command. Type help.")


async def main(args):
    base = args.url.rstrip("/")
    ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + f"/ws?token={args.token}"

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "type": "hello",
            "interface_id": args.interface_id,
            "interface_type": "desktop",
            "capabilities": ["speaker", "keyboard_activity"],
        }))
        ack = json.loads(await ws.recv())
        print(f"Connected: {ack}")
        recv_task = asyncio.create_task(receiver(ws))
        try:
            await interactive(ws)
        finally:
            recv_task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="change-me")
    parser.add_argument("--interface-id", default="desktop-home")
    asyncio.run(main(parser.parse_args()))
