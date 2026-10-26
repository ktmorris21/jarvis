#!/usr/bin/env python3
"""Isolated Jarvis Realtime proof of concept: local wake, one audio turn.

Do not run concurrently with jarvis-voice.service: both require the Jabra.
This deliberately does not replace Core or claim access to its tools/memory.
"""
import argparse
import asyncio
import base64
import getpass
import io
import json
import os
import time
import wave

import numpy as np
import websockets
from openwakeword.model import Model
from voice_interface import HeadExpressions, listen_for_command

MODEL = "gpt-realtime-2.1-mini"
REALTIME_URL = "wss://api.openai.com/v1/realtime?model=" + MODEL
SAMPLE_RATE = 24000
DEVICE = "plughw:CARD=J710,DEV=0"
INSTRUCTIONS = (
    "You are Jarvis, an experimental spoken interface for a PiCar-X robot. "
    "Speak naturally and concisely with dry, understated humor. "
    "You do not yet have access to the robot's Core tools or persistent memory; "
    "never invent live robot status, memories, or actions. "
    "Do not produce stage directions. "
    "This is a temporary audio prototype, not the authoritative Jarvis Core."
)


def convert_wav_to_pcm24(wav_bytes):
    """Convert the existing 16-kHz mono WAV to 24-kHz PCM16 for Realtime."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as f:
        if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, 16000):
            raise ValueError("Expected mono 16-kHz 16-bit WAV from wake client")
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    if len(pcm) == 0:
        raise ValueError("No audio captured")
    # Simple, dependency-free resampling adequate for an initial speech test.
    count = round(len(pcm) * SAMPLE_RATE / 16000)
    x = np.arange(count, dtype=np.float64) * 16000 / SAMPLE_RATE
    return np.interp(x, np.arange(len(pcm)), pcm).astype("<i2").tobytes()


async def run(args):
    key = os.environ.get("OPENAI_API_KEY") or getpass.getpass("OpenAI API key (not Jarvis token): ")
    model = Model(wakeword_models=["hey jarvis"], inference_framework="onnx")
    head = HeadExpressions()
    await head.start()
    try:
        print("[REALTIME POC] Waiting for wake word", flush=True)
        wav = await listen_for_command(model, head)
        await head.set("thinking")
        pcm = convert_wav_to_pcm24(wav)
        start = time.monotonic()
        async with websockets.connect(
            REALTIME_URL,
            additional_headers={"Authorization": "Bearer " + key},
            max_size=16 * 1024 * 1024,
            open_timeout=15,
        ) as ws:
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "model": MODEL,
                    "instructions": INSTRUCTIONS,
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                            "turn_detection": None,
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                            "voice": "cedar",
                        },
                    },
                },
            }))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if event.get("type") == "session.updated":
                    break
                if event.get("type") == "error":
                    raise RuntimeError(str(event.get("error")))
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode(),
            }))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await ws.send(json.dumps({"type": "response.create"}))
            audio_proc = None
            first_audio = True
            try:
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=45))
                    typ = event.get("type")
                    if typ == "error":
                        raise RuntimeError(str(event.get("error")))
                    if typ == "response.output_audio.delta":
                        if first_audio:
                            print(f"[REALTIME POC] First audio after {time.monotonic()-start:.2f}s", flush=True)
                            first_audio = False
                            await head.set("speaking")
                            audio_proc = await asyncio.create_subprocess_exec(
                                "aplay", "-q", "-D", DEVICE,
                                "-t", "raw", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1",
                                stdin=asyncio.subprocess.PIPE,
                            )
                        audio_proc.stdin.write(base64.b64decode(event["delta"]))
                        await audio_proc.stdin.drain()
                    elif typ == "response.output_audio_transcript.done":
                        print("[REALTIME POC] Jarvis:", event.get("transcript", ""), flush=True)
                    elif typ == "response.done":
                        response = event.get("response", {})
                        status = response.get("status")
                        if status != "completed":
                            print("[REALTIME POC] Response status:", status, response.get("status_details"), flush=True)
                        break
            finally:
                if audio_proc:
                    try:
                        audio_proc.stdin.close()
                        await asyncio.wait_for(audio_proc.wait(), timeout=30)
                    except Exception:
                        audio_proc.kill()
                        await audio_proc.wait()
        print(f"[REALTIME POC] Finished after {time.monotonic()-start:.2f}s", flush=True)
    finally:
        await head.set("idle")
        await head.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-turn Realtime test, no Core tools yet")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
