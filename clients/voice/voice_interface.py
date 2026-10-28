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



async def listen_for_command(model, head, on_wake=None):
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
                if on_wake is not None:
                    on_wake()
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
    data = base64.b64decode(encoded)

    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        proc = await asyncio.create_subprocess_exec(
            "aplay", "-q", "-D", DEVICE, path
        )
        rc = await proc.wait()

        if rc:
            print(f"Speaker playback failed: {rc}")
    finally:
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

        status = "complete"
        error = None

        try:
            encoded = data.get("audio_wav_base64")
            if not encoded:
                raise ValueError("Speaker command has no audio")

            await head.set("speaking")
            await play_audio(encoded)

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


async def conversation_loop(model, head, args, response_finished):
    """Handle wake-word turns until interrupted or the Core socket disconnects."""
    while True:
        wav = await listen_for_command(model, head)
        await head.set("thinking")
        response_finished.clear()
        response_finished.sent_at = time.monotonic()

        try:
            result = await send_utterance(args.url, args.token, wav)
            print(
                f"[TIMING] HTTP acknowledgment: "
                f"{time.monotonic() - response_finished.sent_at:.2f}s",
                flush=True,
            )
            if result.get("status") == "no_speech":
                print("No speech recognized.")
                continue

            print("Waiting for Jarvis's response...", flush=True)
            try:
                await asyncio.wait_for(response_finished.wait(), timeout=45)
            except asyncio.TimeoutError:
                print("No speaker response received within 45 seconds.", flush=True)

        except Exception as exc:
            print("Core request failed:", repr(exc), flush=True)
        finally:
            await head.set("idle")


async def main(args):
    model = Model(
        wakeword_models=["hey jarvis"],
        inference_framework="onnx",
    )
    ws_url = (
        args.url.rstrip("/")
        .replace("https://", "wss://")
        .replace("http://", "ws://")
        + "/ws"
    )
    from urllib.parse import quote
    ws_url += "?token=" + quote(args.token, safe="")

    head = HeadExpressions()
    await head.start()
    try:
        # Reconnect without restarting the Pi or reloading the wake-word model.
        while True:
            await head.set("idle")
            try:
                async with websockets.connect(
                    ws_url,
                    max_size=16 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                    open_timeout=15,
                ) as ws:
                    await ws.send(json.dumps({
                        "type": "hello",
                        "interface_id": INTERFACE_ID,
                        "interface_type": "mobile_body",
                        "capabilities": [
                            "speaker", "audio_input", "audio_output"
                        ],
                    }))
                    hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                    if hello.get("type") != "hello_ack":
                        raise RuntimeError(f"Unexpected Core hello: {hello!r}")
                    print("Connected:", hello, flush=True)

                    response_finished = asyncio.Event()
                    response_finished.sent_at = time.monotonic()
                    receiver = asyncio.create_task(
                        receive_commands(ws, response_finished, head)
                    )
                    conversation = asyncio.create_task(
                        conversation_loop(model, head, args, response_finished)
                    )

                    try:
                        # A Core deployment closes the old WebSocket. Stop
                        # capturing immediately and establish a new session.
                        done, _ = await asyncio.wait(
                            {receiver, conversation},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in done:
                            if task.cancelled():
                                raise RuntimeError("Voice session task cancelled")
                            exc = task.exception()
                            if exc:
                                raise exc
                        print("[VOICE] Core connection closed; reconnecting.", flush=True)
                    finally:
                        receiver.cancel()
                        conversation.cancel()
                        await asyncio.gather(
                            receiver, conversation, return_exceptions=True
                        )
                        await head.set("idle")

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[VOICE] Connection lost: {exc!r}", flush=True)

            print("[VOICE] Reconnecting in 3 seconds...", flush=True)
            await asyncio.sleep(3)
    finally:
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