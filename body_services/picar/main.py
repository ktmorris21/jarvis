import argparse
import asyncio
import json
from datetime import datetime, timezone

import websockets

from .abilities import PiCarAbilities
from .hardware import PiCarHardware


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def send_result(ws, command_id: str, ability: str, status: str, result=None, error=None):
    await ws.send(json.dumps({
        "type": "event",
        "event": "COMMAND_RESULT",
        "timestamp": now_iso(),
        "data": {
            "command_id": command_id,
            "ability": ability,
            "status": status,
            "result": result,
            "error": error,
        },
    }))


async def run_connection(args, abilities: PiCarAbilities):
    base = args.url.rstrip("/")
    ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + f"/ws?token={args.token}"

    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({
            "type": "hello",
            "interface_id": args.interface_id,
            "interface_type": "mobile_body",
            "capabilities": ["look", "move", "stop"],
        }))
        ack = json.loads(await ws.recv())
        print(f"Connected to Jarvis Core: {ack}")

        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "command":
                continue

            command_id = msg.get("command_id", "unknown")
            ability = msg.get("ability", "")
            target = msg.get("target")
            if target and target != args.interface_id:
                continue

            try:
                result = await abilities.execute(ability, msg.get("data") or {})
                print(f"Executed {ability}: {result}")
                await send_result(ws, command_id, ability, "complete", result=result)
            except Exception as exc:
                abilities.hardware.stop()
                print(f"Command {ability} failed: {exc}")
                await send_result(ws, command_id, ability, "failed", error=str(exc))


async def main(args):
    hardware = PiCarHardware(mock=args.mock)
    abilities = PiCarAbilities(hardware)

    while True:
        try:
            await run_connection(args, abilities)
        except asyncio.CancelledError:
            hardware.stop()
            raise
        except KeyboardInterrupt:
            hardware.stop()
            return
        except Exception as exc:
            # Network loss must never leave motion active.
            hardware.stop()
            print(f"Core connection lost: {type(exc).__name__}: {exc}")
            print(f"Reconnecting in {args.reconnect_seconds}s...")
            await asyncio.sleep(args.reconnect_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis PiCar-X body service")
    parser.add_argument("--url", required=True, help="Jarvis Core base URL")
    parser.add_argument("--token", required=True, help="Interface token")
    parser.add_argument("--interface-id", default="picar-main")
    parser.add_argument("--reconnect-seconds", type=float, default=3.0)
    parser.add_argument("--mock", action="store_true", help="Do not touch PiCar hardware")
    asyncio.run(main(parser.parse_args()))
