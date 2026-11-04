#!/usr/bin/env python3
"""Jarvis voice interface: local wake word -> Core -> spoken reply."""

import argparse
import time
from collections import deque
import asyncio
import base64
import getpass
import io
import json
import os
import subprocess
import tempfile
import wave
from datetime import datetime, timezone

import httpx
import numpy as np
import websockets
from openwakeword.model import Model
from local_commands import LocalCommands
from local_audio import play_local_response


DEVICE = "plughw:CARD=J710,DEV=0"
RATE = 16000
CHUNK = 1280
THRESHOLD = 0.5
COMMAND_SECONDS = 5
INTERFACE_ID = "picar-voice"


class HeadExpressions:
    """Best-effort subprocess bridge to the system-Python camera controller."""

    def __init__(self):
        self.proc = None

    async def start(self):
        if os.environ.get("HEAD_EXPRESSIONS_ENABLED", "1").lower() in ("0", "false", "no"):
            print("[HEAD] Expressions disabled", flush=True)
            return
        path = os.path.join(os.path.dirname(__file__), "head_expressions.py")
        if not os.path.isfile(path):
            print("[HEAD] Controller file not found; voice continues without gestures", flush=True)
            return
        try:
            self.proc = await asyncio.create_subprocess_exec(
                "/usr/bin/python3", "-u", path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await self.set("idle")
        except Exception as exc:
            print(f"[HEAD] Unavailable: {exc!r}", flush=True)
            self.proc = None

    async def set(self, state):
        if self.proc is None or self.proc.returncode is not None:
            return
        try:
            self.proc.stdin.write((state + "\n").encode())
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            print("[HEAD] Controller disconnected; voice remains available", flush=True)
            self.proc = None

    async def close(self):
        if self.proc is None:
            return
        proc = self.proc
        self.proc = None
        try:
            if proc.returncode is None:
                proc.stdin.write(b"quit\n")
                await proc.stdin.drain()
                await asyncio.wait_for(proc.wait(), timeout=3)
        except (OSError, BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def make_wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return output.getvalue()


def start_microphone():
    return subprocess.Popen(
        [
            "arecord", "-q",
            "-D", DEVICE,
            "-f", "S16_LE",
            "-r", str(RATE),
            "-c", "1",
            "-t", "raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=-1,
    )


def stop_microphone(proc):
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()


async def read_chunk(proc):
    data = await asyncio.to_thread(proc.stdout.read, CHUNK * 2)
    if len(data) != CHUNK * 2:
        raise RuntimeError("Microphone stream ended unexpectedly")
    return data



async def listen_for_command(model, head):
    """Capture one natural wake-word-activated utterance."""

    PRE_ROLL_SECONDS = 1.5
    END_SILENCE_SECONDS = 0.9
    MIN_AFTER_WAKE_SECONDS = 1.6
    MAX_AFTER_WAKE_SECONDS = 12.0
    MIN_RMS = 350
    THRESHOLD_MULTIPLIER = 3.0

    frame_seconds = CHUNK / RATE

    pre_roll = deque(
        maxlen=int(PRE_ROLL_SECONDS / frame_seconds)
    )

    ambient_levels = deque(maxlen=60)

    proc = start_microphone()

    try:
        model.reset()
        print("\nListening for 'Hey Jarvis'...", flush=True)

        # Phase 1: Wake-word recognition
        while True:
            data = await read_chunk(proc)
            pre_roll.append(data)

            samples = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(
                np.mean(samples.astype(np.float32) ** 2)
            ))

            ambient_levels.append(rms)

            score = model.predict(samples).get(
                "hey jarvis", 0.0
            )

            if score >= THRESHOLD:
                print(
                    f"Wake word detected! Score: {score:.3f}",
                    flush=True,
                )
                await head.set("listening")
                break

        # Estimate ambient noise from quieter recent frames.
        baseline = float(np.percentile(
            list(ambient_levels), 35
        ))

        vad_threshold = max(
            MIN_RMS,
            baseline * THRESHOLD_MULTIPLIER,
        )

        print(
            f"Recording command automatically "
            f"(VAD threshold: {vad_threshold:.0f} RMS)...",
            flush=True,
        )

        # Preserve audio before the wake-word detection.
        # This allows natural single-utterance speech.
        audio_frames = list(pre_roll)

        elapsed = 0.0
        last_voice = 0.0
        voice_detected = False
        ended_by = "maximum duration"

        # Phase 2: Capture until speech ends.
        while elapsed < MAX_AFTER_WAKE_SECONDS:
            data = await read_chunk(proc)
            audio_frames.append(data)
            elapsed += frame_seconds

            samples = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(
                np.mean(samples.astype(np.float32) ** 2)
            ))

            if rms >= vad_threshold:
                last_voice = elapsed
                voice_detected = True

            # Allow time for the command to begin,
            # even if there's a short pause after wake.
            if elapsed < MIN_AFTER_WAKE_SECONDS:
                continue

            if elapsed - last_voice >= END_SILENCE_SECONDS:
                ended_by = "silence"
                break

        print(
            f"Captured {elapsed:.2f}s after wake "
            f"(ended by {ended_by}, "
            f"speech detected: {voice_detected}).",
            flush=True,
        )

        return make_wav(b"".join(audio_frames))

    finally:
        stop_microphone(proc)


async def play_audio(encoded):
    started = time.monotonic()
    data = base64.b64decode(encoded)
    print(f"[VOICE PROFILE] wav_decode={time.monotonic()-started:.3f}s bytes={len(data)}", flush=True)

    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        prepared = time.monotonic()
        print(f"[VOICE PROFILE] wav_file_prepare={prepared-started:.3f}s", flush=True)
        proc = await asyncio.create_subprocess_exec(
            "aplay", "-q", "-D", DEVICE, path
        )
        rc = await proc.wait()
        print(f"[VOICE PROFILE] aplay_elapsed={time.monotonic()-prepared:.3f}s", flush=True)

        if rc:
            print(f"Speaker playback failed: {rc}")
    finally:
        os.unlink(path)


async def play_piper(text):
    """Render one phrase locally using an installed Piper voice."""
    voice = os.environ.get("JARVIS_PIPER_VOICE", "/home/shadowfax/jarvis/voices/en_GB-alan-medium.onnx")
    if not text.strip():
        raise ValueError("Empty TTS text")
    if not os.path.isfile(voice) or not os.path.isfile(voice + ".json"):
        raise FileNotFoundError("Piper voice model/config missing: " + voice)
    binary = os.environ.get("JARVIS_PIPER_BIN", "/home/shadowfax/jarvis/.venv-voice/bin/piper")
    if not os.path.isfile(binary):
        raise FileNotFoundError("Piper binary not installed: " + binary)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "--model", voice, "--output_file", path,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate((text.strip() + "\n").encode())
        if proc.returncode:
            raise RuntimeError("Piper failed: " + stderr.decode(errors="replace")[:500])
        player = await asyncio.create_subprocess_exec("aplay", "-q", "-D", DEVICE, path)
        if await player.wait():
            raise RuntimeError("Piper audio playback failed")
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def receive_commands(ws, response_finished, head):
    async for raw in ws:
        msg = json.loads(raw)

        if msg.get("type") != "command":
            continue

        ability = msg.get("ability")
        data = msg.get("data") or {}
        command_id = msg.get("command_id", "unknown")

        if ability != "speaker":
            print(f"Ignoring unsupported command: {ability}")
            continue

        print(
            f"[TIMING] Speaker command received "
            f"{time.monotonic() - response_finished.sent_at:.2f}s "
            f"after upload began",
            flush=True,
        )
        print("\nJARVIS:", data.get("text", ""), flush=True)
        print(f"[VOICE PROFILE] speaker_ws_receive={time.monotonic()-response_finished.sent_at:.3f}s", flush=True)

        status = "complete"
        error = None

        try:
            encoded = data.get("audio_wav_base64")
            await head.set("speaking")
            if encoded:
                await play_audio(encoded)
            else:
                await play_piper(data.get("text", ""))

        except Exception as exc:
            status = "failed"
            error = str(exc)
            print("Playback error:", error)
        finally:
            await head.set("idle")

        await ws.send(json.dumps({
            "type": "event",
            "event": "COMMAND_RESULT",
            "timestamp": timestamp(),
            "data": {
                "command_id": command_id,
                "ability": ability,
                "status": status,
                "result": {"played": status == "complete"},
                "error": error,
            },
        }))

        print(
            f"[TIMING] Audio playback completed "
            f"{time.monotonic() - response_finished.sent_at:.2f}s "
            f"after upload began",
            flush=True,
        )
        response_finished.set()


async def send_utterance(url, token, wav):
    print("Sending command to Jarvis Core...", flush=True)

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            url.rstrip("/") + "/audio/utterance",
            content=wav,
            headers={
                "Content-Type": "audio/wav",
                "X-Jarvis-Token": token,
                "X-Jarvis-Interface": INTERFACE_ID,
            },
        )

        response.raise_for_status()
        result = response.json()
        print("CORE:", result, flush=True)
        return result


async def core_socket_worker(args, head, response_finished, connection_state):
    """Keep Core connectivity independent of the local wake-word loop."""
    from urllib.parse import quote
    ws_url = (args.url.rstrip("/").replace("https://", "wss://")
              .replace("http://", "ws://") + "/ws?token="
              + quote(args.token, safe=""))
    while True:
        try:
            async with websockets.connect(
                ws_url, max_size=16 * 1024 * 1024,
                ping_interval=20, ping_timeout=20, open_timeout=15
            ) as ws:
                await ws.send(json.dumps({
                    "type": "hello", "interface_id": INTERFACE_ID,
                    "interface_type": "mobile_body",
                    "capabilities": ["speaker", "audio_input", "audio_output"],
                }))
                hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if hello.get("type") != "hello_ack":
                    raise RuntimeError(f"Unexpected Core hello: {hello!r}")
                connection_state["ready"] = True
                print("[VOICE] Core connected", flush=True)
                await receive_commands(ws, response_finished, head)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[VOICE] Core unavailable: {exc!r}", flush=True)
        finally:
            connection_state["ready"] = False
            response_finished.set()
        await asyncio.sleep(3)


async def conversation_loop(model, head, args, response_finished, connection_state, local):
    """Listen continuously; intercept known commands before Core upload."""
    while True:
        wav = await listen_for_command(model, head)
        try:
            handled, reply, power_action = await local.act(wav)
            if handled:
                print("[LOCAL]", reply, flush=True)
                await head.set("speaking")
                try:
                    await play_local_response(reply, device=DEVICE, fallback=play_piper)
                except Exception as exc:
                    print("[LOCAL] Audio playback failed:", repr(exc), flush=True)
                    power_action = None
                finally:
                    await head.set("idle")
                if power_action:
                    try:
                        await local.system_action(power_action)
                    except Exception as exc:
                        print("[LOCAL] System action failed:", repr(exc), flush=True)
                        try:
                            await play_local_response("Power command failed.", device=DEVICE, fallback=play_piper)
                        except Exception:
                            pass
                continue
        except Exception as exc:
            print("[LOCAL] Recognition failed:", repr(exc), flush=True)

        if not connection_state["ready"]:
            print("[VOICE] Core offline; ordinary conversation unavailable", flush=True)
            await head.set("idle")
            continue

        await head.set("thinking")
        response_finished.clear()
        response_finished.sent_at = time.monotonic()
        try:
            result = await send_utterance(args.url, args.token, wav)
            print(f"[TIMING] HTTP acknowledgment: "
                  f"{time.monotonic()-response_finished.sent_at:.2f}s", flush=True)
            if result.get("status") == "no_speech":
                print("No speech recognized.")
                continue
            try:
                await asyncio.wait_for(response_finished.wait(), timeout=45)
            except asyncio.TimeoutError:
                print("No speaker response received within 45 seconds.", flush=True)
        except Exception as exc:
            print("Core request failed:", repr(exc), flush=True)
        finally:
            await head.set("idle")


async def main(args):
    model = Model(wakeword_models=["hey jarvis"], inference_framework="onnx")
    local = LocalCommands()
    head = HeadExpressions()
    await head.start()
    response_finished = asyncio.Event()
    response_finished.sent_at = time.monotonic()
    connection_state = {"ready": False}
    socket_task = asyncio.create_task(
        core_socket_worker(args, head, response_finished, connection_state)
    )
    try:
        await conversation_loop(model, head, args, response_finished, connection_state, local)
    finally:
        socket_task.cancel()
        await asyncio.gather(socket_task, return_exceptions=True)
        await head.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://jarvis-production-110e.up.railway.app",
    )
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    if not args.token:
        args.token = (
            os.environ.get("JARVIS_INTERFACE_TOKEN")
            or getpass.getpass("Jarvis interface token: ")
        )

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nJarvis voice interface stopped.")