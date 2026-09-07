import argparse,asyncio,json
from datetime import datetime,timezone
import websockets
from .abilities import PiCarAbilities
from .hardware import PiCarHardware
def now_iso():return datetime.now(timezone.utc).isoformat()
async def run(args):
    hw=PiCarHardware(args.mock); abilities=PiCarAbilities(hw)
    while True:
        try:
            u=args.url.rstrip('/').replace('https://','wss://').replace('http://','ws://')+f"/ws?token={args.token}"
            async with websockets.connect(u) as ws:
                await ws.send(json.dumps({"type":"hello","interface_id":args.interface_id,"interface_type":"mobile_body","capabilities":["look","move","stop"]})); print("Connected:",json.loads(await ws.recv()))
                async for raw in ws:
                    m=json.loads(raw)
                    if m.get("type")!="command":continue
                    cid=m.get("command_id","unknown"); ability=m.get("ability","")
                    try:
                        result=await abilities.execute(ability,m.get("data") or {}); status="complete"; error=None
                    except Exception as e:
                        hw.stop(); result=None; status="failed"; error=str(e)
                    await ws.send(json.dumps({"type":"event","event":"COMMAND_RESULT","timestamp":now_iso(),"data":{"command_id":cid,"ability":ability,"status":status,"result":result,"error":error}}))
        except Exception as e:
            hw.stop(); print("Connection lost:",e); await asyncio.sleep(3)
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--token",required=True); p.add_argument("--interface-id",default="picar-main"); p.add_argument("--mock",action="store_true"); asyncio.run(run(p.parse_args()))
