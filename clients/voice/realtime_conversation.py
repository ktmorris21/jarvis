#!/usr/bin/env python3
"""Jarvis Realtime Sprint 2: wake-word session, follow-ups, silent dismissal.

Standalone experimental client; never run alongside jarvis-voice.service.
Core/memory/tools are intentionally NOT integrated yet.
"""
import argparse
import asyncio
import base64
import getpass
import httpx
import json
import os
import re
import time

import numpy as np
import websockets

from openwakeword.model import Model
from realtime_poc import (DEVICE, MODEL, REALTIME_URL, SAMPLE_RATE,
                          convert_wav_to_pcm24)
from voice_interface import (CHUNK, RATE, HeadExpressions, listen_for_command,
                             make_wav, read_chunk, start_microphone, stop_microphone)

DISMISSAL_PATTERNS = [
    r"(?:thanks|thank you)(?: jarvis)?",
    r"(?:okay|ok|alright|right)(?: thanks| thank you)?(?: jarvis)?",
    r"(?:goodbye|goodnight|bye)(?: jarvis)?",
    r"(?:jarvis )?(?:that's|that is|that'll be|that will be) all",
    r"(?:jarvis )?(?:we're|we are) (?:done|good)",
    r"(?:jarvis )?(?:that will do|that'll do|we're all set|i'm all set)",
    r"(?:jarvis )?(?:stop listening|end the conversation)",
]


def is_dismissal(transcript):
    """Recognize complete farewells, not phrases embedded in real questions."""
    cleaned = transcript.lower().replace("’", "'")
    cleaned = re.sub(r"[^a-z0-9' ]", " ", cleaned)
    cleaned = re.sub(r"\\s+", " ", cleaned).strip()
    # Permit common polite lead-ins and trailing conversational particles.
    cleaned = re.sub(r"^(?:okay|ok|alright|well|so|right)\\s+", "", cleaned)
    cleaned = re.sub(r"\\s+(?:please|for now|then)$", "", cleaned)
    if re.fullmatch(r"(?:thanks|thank you)(?: jarvis)?(?: (?:that'll be|that will be|that's|that is) all)?", cleaned):
        return True
    return any(re.fullmatch(pattern, cleaned) for pattern in DISMISSAL_PATTERNS)


async def capture_followup(head, window):
    """Local RMS/VAD gate; do not send ambient silence to Realtime.

    Start each follow-up after playback, listen for initial speech until window
    expires, then capture until 0.9s of silence or 12s maximum.
    """
    proc = start_microphone()
    await head.set("listening")
    threshold = 350.0
    samples_seen = 0
    frames = []
    started = False
    last_voice = 0.0
    started_at = 0.0
    deadline = time.monotonic() + window
    try:
        while True:
            timeout = min(1.0, max(0.0, deadline - time.monotonic())) if not started else 2.0
            if not started and timeout <= 0:
                return None
            try:
                chunk = await asyncio.wait_for(read_chunk(proc), timeout=timeout)
            except asyncio.TimeoutError:
                if not started and time.monotonic() >= deadline:
                    return None
                raise
            audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(audio * audio)))
            if not started:
                samples_seen += 1
                # Demand multiple loud frames to reduce accidental activation.
                if rms < threshold:
                    frames.clear()
                    continue
                frames.append(chunk)
                if len(frames) < 3:
                    continue
                started = True
                started_at = time.monotonic()
                last_voice = started_at
                print("[REALTIME] Follow-up speech detected", flush=True)
            else:
                frames.append(chunk)
                now = time.monotonic()
                if rms >= threshold:
                    last_voice = now
                if now - started_at >= 1.2 and now - last_voice >= 0.9:
                    break
                if now - started_at >= 12:
                    break
        return make_wav(b"".join(frames))
    finally:
        stop_microphone(proc)


async def receive_until(ws, wanted, timeout=20):
    until = time.monotonic() + timeout
    while True:
        left = until - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"No {wanted} event")
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
        if event.get("type") == "error":
            raise RuntimeError(str(event.get("error")))
        if event.get("type") == wanted:
            return event


CORE_TOOLS = [
 {"type":"function","name":"get_robot_status","description":"Get current robot, ROS, LiDAR and map health.","parameters":{"type":"object","properties":{}}},
 {"type":"function","name":"finish_conversation","description":"End the voice session silently when the user is clearly dismissing you or saying they are done; call this instead of speaking any farewell.","parameters":{"type":"object","properties":{}}},
 {"type":"function","name":"search_memories","description":"Search Jarvis Core's persistent memories.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}
]

async def core_call(url, token, path, payload=None):
    async with httpx.AsyncClient(timeout=25) as client:
        if payload is None:
            response = await client.get(url.rstrip("/") + path, headers={"X-Jarvis-Token":token})
        else:
            response = await client.post(url.rstrip("/") + path, headers={"X-Jarvis-Token":token}, json=payload)
        response.raise_for_status()
        return response.json()


async def speak_turn(ws, head):
    first = True
    audio_proc = None
    started_at = time.monotonic()
    await ws.send(json.dumps({"type": "response.create"}))
    calls = []
    try:
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            kind = event.get("type")
            if kind == "error":
                raise RuntimeError(str(event.get("error")))
            if kind == "response.output_audio.delta":
                if first:
                    first = False
                    print(f"[REALTIME] First audio: {time.monotonic()-started_at:.2f}s after response request",
                          flush=True)
                    await head.set("speaking")
                    audio_proc = await asyncio.create_subprocess_exec(
                        "aplay", "-q", "-D", DEVICE,
                        "-t", "raw", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1",
                        stdin=asyncio.subprocess.PIPE,
                    )
                audio_proc.stdin.write(base64.b64decode(event["delta"]))
                await audio_proc.stdin.drain()
            elif kind == "response.output_audio_transcript.done":
                print("[REALTIME] Jarvis:", event.get("transcript", ""), flush=True)
            elif kind == "response.done":
                calls = [item for item in event.get("response", {}).get("output", []) if item.get("type") == "function_call"]
                status = event.get("response", {}).get("status")
                if status != "completed":
                    print("[REALTIME] Response status:", status, flush=True)
                break
    finally:
        if audio_proc:
            try:
                audio_proc.stdin.close()
                await asyncio.wait_for(audio_proc.wait(), timeout=35)
            except Exception:
                if audio_proc.returncode is None:
                    audio_proc.kill()
                    await audio_proc.wait()
        await head.set("idle")
    if calls:
        for call in calls:
            if call.get("name") == "finish_conversation":
                print("[REALTIME] Dismissal requested by model.", flush=True)
                return False
            try:
                arguments = json.loads(call.get("arguments") or "{}")
                result = await core_call(CORE_URL, CORE_TOKEN, "/realtime/tool",
                                         {"name": call["name"], "arguments": arguments})
                output = json.dumps(result)
            except Exception as exc:
                output = json.dumps({"error": "Core tool failed: " + type(exc).__name__})
                print("[REALTIME] Tool error:", repr(exc), flush=True)
            print("[REALTIME] Tool:", call["name"], flush=True)
            await ws.send(json.dumps({"type": "conversation.item.create",
                                      "item": {"type": "function_call_output",
                                               "call_id": call["call_id"], "output": output}}))
        return await speak_turn(ws, head)
    return True


async def send_turn(ws, wav):
    await ws.send(json.dumps({
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(convert_wav_to_pcm24(wav)).decode(),
    }))
    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    # Gate the response until we see the transcript, so a clear farewell
    # cannot elicit the unwanted "You're welcome, anything else?" reply.
    # Note: transcription is a separate model and adds latency/cost.
    event = await receive_until(ws, "conversation.item.input_audio_transcription.completed", timeout=20)
    transcript = event.get("transcript", "")
    print("[REALTIME] Heard:", transcript, flush=True)
    if is_dismissal(transcript):
        print("[REALTIME] Dismissed: close silently.", flush=True)
        return False
    return await speak_turn(ws, HEAD)


async def main(args):
    global HEAD, CORE_URL, CORE_TOKEN
    key = os.environ.get("OPENAI_API_KEY") or getpass.getpass("OpenAI API key: ")
    CORE_URL = args.core_url
    CORE_TOKEN = os.environ.get("JARVIS_INTERFACE_TOKEN") or getpass.getpass("Jarvis Core token: ")
    context = await core_call(CORE_URL, CORE_TOKEN, "/realtime/context")
    instructions = (context["instructions"] +
        "\\nVOICE IDENTITY — HIGHEST PRIORITY FOR SPOKEN DELIVERY:\\n"
        "You ARE Jarvis. Your PiCar-X is your physical body; ROS, LiDAR, camera, "
        "motors, and mapping belong to your robot embodiment. The Railway Core "
        "maintains your continuing identity and memories across interfaces. "
        "Never describe yourself as a chatbot, an assistant helping someone with "
        "their robot, or an independent voice plugged into a third-party robot. "
        "Say 'my LiDAR', 'my sensors', and 'my map' naturally. "
        "Be candid about which physical abilities are available right now. "
        "You can inspect live status and search memories using your Core tools; "
        "you cannot command movement yet. Never invent data.\\n"
        "SPOKEN STYLE:\\n"
        "Understated, mature, composed, dryly witty on occasion. "
        "A restrained, intelligent robotic companion—not a chirpy assistant. "
        "No flattery, sales pitches, cheerleading, overly helpful sign-offs, "
        "self-conscious jokes, nervous hedging, or descriptions of your own charm. "
        "Don't repeatedly announce limitations; answer the question directly. "
        "Usually speak one short sentence, two if needed. For 2+2 say 'Four.' "
        "Be silent when nothing needs saying. Never force a joke. "
        "If the user is ending the interaction, call finish_conversation; "
        "do not respond with a farewell or an invitation for more questions. "
        "Check your real Core tools for live sensor status or relevant memories. "
        "Keep the humor subtle and leave it out entirely for simple queries.")

    wake = Model(wakeword_models=["hey jarvis"], inference_framework="onnx")
    HEAD = HeadExpressions()
    await HEAD.start()
    try:
        while True:
            await HEAD.set("idle")
            initial_wav = await listen_for_command(wake, HEAD)
            await HEAD.set("thinking")
            opened = time.monotonic()
            try:
                async with websockets.connect(
                    REALTIME_URL,
                    additional_headers={"Authorization": "Bearer " + key},
                    max_size=16 * 1024 * 1024,
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    await ws.send(json.dumps({
                        "type": "session.update",
                        "session": {
                            "type": "realtime",
                            "model": MODEL,
                            "instructions": instructions,
                            "tools": CORE_TOOLS,
                            "tool_choice": "auto",
                            "output_modalities": ["audio"],
                            "audio": {
                                "input": {
                                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                                    "turn_detection": None,
                                    "transcription": {
                                        "model": "gpt-4o-transcribe",
                                        "language": "en",
                                    },
                                },
                                "output": {
                                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                                    "voice": "echo",
                                },
                            },
                        },
                    }))
                    await receive_until(ws, "session.updated", timeout=15)
                    current = initial_wav
                    turns = 0
                    while turns < args.max_turns and time.monotonic() - opened < args.max_session_seconds:
                        await HEAD.set("thinking")
                        keep_talking = await send_turn(ws, current)
                        if not keep_talking:
                            break
                        turns += 1
                        print(f"[REALTIME] Follow-up window: {args.followup_seconds}s; "
                              "say goodbye to end silently", flush=True)
                        left = min(args.followup_seconds,
                                   max(0, args.max_session_seconds - (time.monotonic()-opened)))
                        if left <= 0:
                            break
                        current = await capture_followup(HEAD, left)
                        if current is None:
                            print("[REALTIME] Conversation expired after silence.", flush=True)
                            break
            except Exception as exc:
                print("[REALTIME] Session ended with error:", repr(exc), flush=True)
            finally:
                await HEAD.set("idle")
            print("[REALTIME] Back to local wake-word idle.", flush=True)
    finally:
        await HEAD.set("idle")
        await HEAD.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experimental Realtime conversation mode")
    parser.add_argument("--core-url", default="https://jarvis-production-110e.up.railway.app")
    parser.add_argument("--followup-seconds", type=int, default=20)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-session-seconds", type=int, default=240)
    a = parser.parse_args()
    if not 5 <= a.followup_seconds <= 60:
        parser.error("Follow-up window must be 5 to 60 seconds")
    if not 1 <= a.max_turns <= 50:
        parser.error("Max turns must be 1 to 50")
    if not 30 <= a.max_session_seconds <= 1800:
        parser.error("Max session seconds must be 30 to 1800")
    try:
        asyncio.run(main(a))
    except KeyboardInterrupt:
        print("\n[REALTIME] Stopped", flush=True)
