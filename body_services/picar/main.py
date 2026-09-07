import argparse
import asyncio
import json
from datetime import datetime, timezone

import httpx
import websockets

from .abilities import PiCarAbilities
from .audio_io import AudioIO
from .hardware import PiCarHardware
from .camera_io import CameraIO
from .scene_monitor import SceneMonitor, SceneMonitorConfig
from .vad import EnergyVad, VadConfig


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def upload_wav(args, wav: bytes):
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


async def manual_listen(args, audio_io):
    print(f"Listening for {args.record_seconds} seconds...")
    wav = await audio_io.record_once()
    print("Sending utterance to Jarvis Core...")
    await upload_wav(args, wav)



async def upload_frame(args, jpeg: bytes):
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            args.url.rstrip("/") + "/vision/frame",
            content=jpeg,
            headers={
                "Content-Type": "image/jpeg",
                "X-Jarvis-Token": args.token,
                "X-Jarvis-Interface": args.interface_id,
            },
        )
        r.raise_for_status()
        payload = r.json()
        obs = payload.get("observation") or {}
        print("Jarvis sees:", obs.get("summary") or "(no summary)")
        if obs.get("notable"):
            print("Notable:", "; ".join(obs["notable"]))


async def capture_and_observe(args, camera_io):
    print("Capturing camera frame...")
    jpeg = await camera_io.capture_jpeg()
    print(f"Sending {len(jpeg)} bytes to Jarvis Core...")
    await upload_frame(args, jpeg)

async def console_loop(args, audio_io, camera_io):
    print("Commands: listen | see | quit")
    while True:
        command = (await asyncio.to_thread(input, "> ")).strip().lower()
        if command == "listen":
            try:
                await manual_listen(args, audio_io)
            except Exception as e:
                print("Audio capture/upload failed:", e)
        elif command == "see":
            try:
                await capture_and_observe(args, camera_io)
            except Exception as e:
                print("Camera capture/vision failed:", e)
        elif command == "quit":
            return


async def vad_loop(args):
    config = VadConfig(
        end_silence_ms=args.vad_end_silence_ms,
        max_utterance_seconds=args.vad_max_seconds,
        calibration_seconds=args.vad_calibration_seconds,
        threshold_multiplier=args.vad_threshold_multiplier,
        minimum_threshold=args.vad_min_threshold,
    )
    vad = EnergyVad(args.audio_input, config)
    try:
        async for item in vad.utterances():
            if item["type"] == "calibration":
                print(
                    "VAD calibrated:"
                    f" baseline RMS={item['baseline_rms']},"
                    f" threshold={item['threshold_rms']}"
                )
                print("Listening automatically. Speak near Jarvis...")
                continue

            print(
                f"Speech detected: {item['duration_seconds']}s"
                f" ({item['ended_by']}); sending to Core..."
            )
            try:
                await upload_wav(args, item["wav"])
            except Exception as e:
                print("Utterance upload failed:", e)
    finally:
        await vad.close()



async def vision_console_loop(args, camera_io):
    print("Camera test command: type 'see' and press Enter.")
    while True:
        command = (await asyncio.to_thread(input, "> ")).strip().lower()
        if command == "see":
            try:
                await capture_and_observe(args, camera_io)
            except Exception as e:
                print("Camera capture/vision failed:", e)
        elif command == "quit":
            return


async def automatic_vision_loop(args, camera_io):
    config = SceneMonitorConfig(
        width=args.scene_width,
        height=args.scene_height,
        fps=args.scene_fps,
        threshold=args.scene_threshold,
        cooldown_seconds=args.scene_cooldown_seconds,
        sample_stride=args.scene_sample_stride,
    )
    monitor = SceneMonitor(config)

    print(
        "Automatic vision enabled:"
        f" {config.width}x{config.height} @ {config.fps} fps,"
        f" threshold={config.threshold},"
        f" cooldown={config.cooldown_seconds}s"
    )

    while True:
        try:
            change = await monitor.wait_for_change()
            print(
                f"Scene change detected: score={change['score']}"
                f" threshold={change['threshold']}"
            )

            # rpicam/libcamera generally gives one process exclusive camera ownership.
            # Release the tiny monitor stream before capturing the semantic JPEG.
            await monitor.stop()

            jpeg = await camera_io.capture_jpeg()
            print(f"Sending changed scene ({len(jpeg)} bytes) to Jarvis Core...")
            await upload_frame(args, jpeg)

            await asyncio.sleep(config.cooldown_seconds)
            await monitor.start()

        except asyncio.CancelledError:
            await monitor.stop()
            raise
        except Exception as exc:
            await monitor.stop()
            print("Automatic vision error:", exc)
            print("Retrying scene monitor in 3s...")
            await asyncio.sleep(3)


async def websocket_loop(args, hw, abilities):
    while True:
        try:
            u = (
                args.url.rstrip("/")
                .replace("https://", "wss://")
                .replace("http://", "ws://")
                + f"/ws?token={args.token}"
            )
            async with websockets.connect(u, max_size=4 * 1024 * 1024) as ws:
                await ws.send(json.dumps({
                    "type": "hello",
                    "interface_id": args.interface_id,
                    "interface_type": "mobile_body",
                    "capabilities": [
                        "look", "look_around", "move", "stop",
                        "speaker", "audio_input", "audio_output"
                    ],
                }))
                print("Connected:", json.loads(await ws.recv()))

                async for raw in ws:
                    m = json.loads(raw)
                    if m.get("type") != "command":
                        continue

                    cid = m.get("command_id", "unknown")
                    ability = m.get("ability", "")
                    try:
                        result = await abilities.execute(ability, m.get("data") or {})
                        status = "complete"
                        error = None
                    except Exception as e:
                        hw.stop()
                        result = None
                        status = "failed"
                        error = str(e)

                    await ws.send(json.dumps({
                        "type": "event",
                        "event": "COMMAND_RESULT",
                        "timestamp": now_iso(),
                        "data": {
                            "command_id": cid,
                            "ability": ability,
                            "status": status,
                            "result": result,
                            "error": error,
                        },
                    }))
        except Exception as e:
            hw.stop()
            print("Connection lost:", e)
            await asyncio.sleep(3)


async def run(args):
    hw = PiCarHardware(args.mock)
    audio_io = AudioIO(args.audio_input, args.audio_output, args.record_seconds)
    abilities = PiCarAbilities(hw, audio_io)
    camera_io = CameraIO(args.camera_width, args.camera_height)

    tasks = [websocket_loop(args, hw, abilities)]
    if args.auto_vision:
        tasks.append(automatic_vision_loop(args, camera_io))
    if args.vad:
        tasks.append(vad_loop(args))
        tasks.append(vision_console_loop(args, camera_io))
    else:
        tasks.append(console_loop(args, audio_io, camera_io))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--interface-id", default="picar-main")
    p.add_argument("--mock", action="store_true")

    p.add_argument("--audio-input", default="plughw:2,0")
    p.add_argument("--audio-output", default="plughw:2,0")
    p.add_argument("--record-seconds", type=int, default=5)
    p.add_argument("--camera-width", type=int, default=640)
    p.add_argument("--camera-height", type=int, default=480)
    p.add_argument("--auto-vision", action="store_true")
    p.add_argument("--scene-width", type=int, default=160)
    p.add_argument("--scene-height", type=int, default=120)
    p.add_argument("--scene-fps", type=float, default=2.0)
    p.add_argument("--scene-threshold", type=float, default=12.0)
    p.add_argument("--scene-cooldown-seconds", type=float, default=8.0)
    p.add_argument("--scene-sample-stride", type=int, default=4)

    p.add_argument("--vad", action="store_true")
    p.add_argument("--vad-end-silence-ms", type=int, default=750)
    p.add_argument("--vad-max-seconds", type=float, default=12.0)
    p.add_argument("--vad-calibration-seconds", type=float, default=1.5)
    p.add_argument("--vad-threshold-multiplier", type=float, default=3.0)
    p.add_argument("--vad-min-threshold", type=int, default=350)

    asyncio.run(run(p.parse_args()))
