import argparse,asyncio,json
from datetime import datetime,timezone
import websockets
def now_iso(): return datetime.now(timezone.utc).isoformat()
async def send_event(ws,event,data=None): await ws.send(json.dumps({"type":"event","event":event,"data":data or {},"timestamp":now_iso()}))
async def receiver(ws):
    async for raw in ws:
        m=json.loads(raw)
        if m.get("type")=="command" and m.get("ability")=="speaker": print(f"\nJARVIS: {m['data'].get('text','')}\n> ",end="",flush=True)
async def main(args):
    u=args.url.rstrip('/').replace('https://','wss://').replace('http://','ws://')+f"/ws?token={args.token}"
    async with websockets.connect(u) as ws:
        await ws.send(json.dumps({"type":"hello","interface_id":args.interface_id,"interface_type":"desktop","capabilities":["speaker","keyboard_activity"]})); print("Connected:",json.loads(await ws.recv())); task=asyncio.create_task(receiver(ws))
        try:
            while True:
                c=(await asyncio.to_thread(input,"> ")).strip()
                if c=="quit":break
                if c=="active":await send_event(ws,"USER_ACTIVE")
                elif c=="idle":await send_event(ws,"USER_IDLE")
                elif c.startswith("say "):await send_event(ws,"USER_SPOKE",{"text":c[4:]})
                elif c.startswith("event "):await send_event(ws,c[6:].strip())
        finally: task.cancel()
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--token",required=True); p.add_argument("--interface-id",default="desktop-home"); asyncio.run(main(p.parse_args()))
