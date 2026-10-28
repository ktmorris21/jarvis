"""Restricted Pi management bridge: no arbitrary commands or shell execution.

Connects to Core as a separate interface so stopping mapping does not sever
remote control. All operations are exact allowlisted subprocess argv arrays.
"""
import asyncio
import json
import os
import re
import math
from datetime import datetime, timezone

import websockets

CAPABILITIES = ["get_audio_levels", "set_audio_level", "get_lidar_service",
                "set_lidar_service", "reboot_pi", "drive_timed", "stop_driving"]
MAPPING_UNIT = "jarvis-mapping@shadowfax.service"
ALLOWED_CONTROLS = {"speaker": "JARVIS_SPEAKER_CONTROL",
                    "microphone": "JARVIS_MIC_CONTROL"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


async def run_fixed(*args, timeout=8):
    """No shell, no external model-supplied executable, no variable service."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("Pi command timed out")
    if proc.returncode:
        detail = stderr.decode(errors="replace").strip()[:240]
        raise RuntimeError(detail or f"Pi command exited {proc.returncode}")
    return stdout.decode(errors="replace").strip()


def mixer_args():
    # Config is set by local administrator only, never sent by an LLM.
    return ("/usr/bin/amixer", "-D", os.environ.get("JARVIS_ALSA_DEVICE", "default"))


def control_name(kind):
    if kind not in ALLOWED_CONTROLS:
        raise ValueError("Audio device must be 'speaker' or 'microphone'")
    name = os.environ.get(ALLOWED_CONTROLS[kind],
                          "Speaker" if kind == "speaker" else "Capture")
    if not name or len(name) > 80:
        raise ValueError("Invalid locally configured mixer control")
    return name


async def read_level(kind):
    name = control_name(kind)
    output = await run_fixed(*mixer_args(), "sget", name)
    levels = re.findall(r"\[(\d{1,3})%\]", output)
    if not levels:
        raise RuntimeError(f"ALSA control {name!r} has no percentage level")
    return {"device": kind, "percent": int(levels[-1]), "control": name}


async def execute(ability, data):
    if not isinstance(data, dict):
        raise ValueError("Command data must be an object")
    if ability == "get_audio_levels":
        if data:
            raise ValueError("get_audio_levels takes no parameters")
        result = {}
        for kind in ALLOWED_CONTROLS:
            try:
                result[kind] = await read_level(kind)
            except (RuntimeError, OSError, ValueError) as exc:
                result[kind] = {"available": False, "error": str(exc)[:200]}
        return result

    if ability == "set_audio_level":
        if set(data) != {"device", "percent"}:
            raise ValueError("Expected device and percent")
        kind = data["device"]
        percent = data["percent"]
        if kind not in ALLOWED_CONTROLS or type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("Audio device must be speaker/microphone and percent integer 0-100")
        name = control_name(kind)
        await run_fixed(*mixer_args(), "sset", name, f"{percent}%")
        result = await read_level(kind)
        result["requested_percent"] = percent
        return result

    if ability == "get_lidar_service":
        if data:
            raise ValueError("get_lidar_service takes no parameters")
        active = await run_fixed("/usr/bin/systemctl", "show", "-p",
                                 "ActiveState", "--value", MAPPING_UNIT)
        return {"unit": MAPPING_UNIT, "service_state": active,
                "controls_entire_mapping_stack": True}

    if ability == "set_lidar_service":
        if set(data) != {"running"} or type(data["running"]) is not bool:
            raise ValueError("Expected boolean running")
        operation = "start" if data["running"] else "stop"
        await run_fixed("/usr/bin/sudo", "-n", "/usr/bin/systemctl",
                        operation, MAPPING_UNIT, timeout=25)
        return {"requested": operation, "unit": MAPPING_UNIT,
                "controls_entire_mapping_stack": True,
                "note": "Status may take a few seconds to update"}

    if ability == "reboot_pi":
        if set(data) != {"confirmation"} or data["confirmation"] != "REBOOT JARVIS NOW":
            raise ValueError("Reboot requires explicit confirmation phrase")
        if os.environ.get("JARVIS_ALLOW_REMOTE_REBOOT") != "1":
            raise RuntimeError("Remote reboot disabled by local administrator")
        # Schedule after acknowledging the command, allowing Core to receive
        # the result before SSH/network disappear. No command injection.
        asyncio.create_task(schedule_reboot())
        return {"scheduled": True, "note": "Pi will disconnect and reboot shortly"}
    raise ValueError("Unsupported Pi control ability")


async def schedule_reboot():
    await asyncio.sleep(3)
    try:
        await run_fixed("/usr/bin/sudo", "-n", "/usr/bin/systemctl", "reboot", timeout=8)
    except Exception as exc:
        print("Reboot failed:", repr(exc), flush=True)



# Only this bridge owns the motor while enabled. Never run another PiCar-X
# motor-controlling process concurrently. Stop in finally on disconnect.
_motion_task = None
_motion_hardware = None

def _motor():
    global _motion_hardware
    if os.environ.get("JARVIS_ENABLE_MOTION") != "1":
        raise RuntimeError("Motion disabled; enable JARVIS_ENABLE_MOTION=1 on the Pi")
    if _motion_hardware is None:
        from .hardware import PiCarHardware
        _motion_hardware = PiCarHardware()
    return _motion_hardware

async def stop_motion():
    global _motion_task
    task = _motion_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _motion_task = None
    if _motion_hardware is not None:
        _motion_hardware.stop()
    return {"stopped": True}

async def timed_motion(data):
    if (set(data) != {"direction", "duration_seconds"}
            or data.get("direction") not in {"forward", "backward", "left", "right"}
            or type(data.get("duration_seconds")) not in (int, float)
            or not math.isfinite(data["duration_seconds"])
            or not 0.1 <= data["duration_seconds"] <= 5):
        raise ValueError("direction and duration_seconds (0.1–5) required")
    direction, seconds = data["direction"], float(data["duration_seconds"])
    hw = _motor()
    # Steering sign is calibrated on the PiCar-X; verify with wheels lifted.
    steering = {"forward": 0, "backward": 0, "left": -25, "right": 25}[direction]
    physical_direction = "backward" if direction == "backward" else "forward"
    try:
        hw.set_steering(steering)
        hw.drive(physical_direction, 20)
        await asyncio.sleep(seconds)
        return {"direction": direction, "duration_seconds": seconds, "stopped": True}
    finally:
        hw.stop()

async def _motion_result(ws, command):
    global _motion_task
    ability = command["ability"]
    try:
        result = await timed_motion(command["data"])
        status, error = "complete", None
    except asyncio.CancelledError:
        result, status, error = {"stopped": True}, "failed", "movement interrupted"
    except Exception as exc:
        result, status, error = None, "failed", str(exc)[:300]
    finally:
        if _motion_hardware is not None:
            _motion_hardware.stop()
    await ws.send(json.dumps({
        "type": "event", "event": "COMMAND_RESULT", "timestamp": utc_now(),
        "data": {"command_id": command.get("command_id"), "ability": ability,
                 "status": status, "result": result, "error": error},
    }))


async def serve():
    url = os.environ["JARVIS_URL"].rstrip("/")
    token = os.environ["JARVIS_TOKEN"]
    if not url.startswith("https://") and not url.startswith("http://localhost:"):
        raise RuntimeError("Pi control requires HTTPS Core URL")
    ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + "/ws?token=" + token
    while True:
        try:
            async with websockets.connect(ws_url, max_size=1024 * 1024) as ws:
                await ws.send(json.dumps({
                    "type": "hello", "interface_id": "picar-control",
                    "interface_type": "pi_control",
                    "capabilities": CAPABILITIES,
                }))
                ack = json.loads(await ws.recv())
                if ack.get("type") != "hello_ack":
                    raise RuntimeError("Core rejected management bridge")
                print("Pi control bridge connected", flush=True)
                try:
                    async for raw in ws:
                        command = json.loads(raw)
                        if command.get("type") != "command":
                            continue
                        ability = command.get("ability")
                        try:
                            if ability not in CAPABILITIES:
                                raise ValueError("Unsupported Pi control ability")
                            if ability == "stop_driving":
                                if command.get("data"):
                                    raise ValueError("stop_driving takes no arguments")
                                result = await stop_motion()
                            elif ability == "drive_timed":
                                if _motion_task is not None and not _motion_task.done():
                                    raise RuntimeError("Drive in progress; stop first")
                                # Validate and check local enablement before accepting.
                                data = command.get("data") or {}
                                if (set(data) != {"direction", "duration_seconds"}
                                        or data.get("direction") not in {"forward", "backward", "left", "right"}
                                        or type(data.get("duration_seconds")) not in (int, float)
                                        or not math.isfinite(data["duration_seconds"])
                                        or not 0.1 <= data["duration_seconds"] <= 5):
                                    raise ValueError("Invalid drive parameters")
                                _motor()
                                _motion_task = asyncio.create_task(
                                    _motion_result(ws, {**command, "data": data}))
                                continue
                            else:
                                result = await execute(ability, command.get("data") or {})
                            status, error = "complete", None
                        except Exception as exc:
                            result, status, error = None, "failed", str(exc)[:300]
                        await ws.send(json.dumps({
                            "type": "event", "event": "COMMAND_RESULT",
                            "timestamp": utc_now(),
                            "data": {"command_id": command.get("command_id"),
                                     "ability": ability, "status": status,
                                     "result": result, "error": error},
                        }))
                finally:
                    await stop_motion()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("Pi control bridge disconnected:", repr(exc), flush=True)
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(serve())
