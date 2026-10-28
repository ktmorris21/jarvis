#!/usr/bin/env python3
"""Jarvis primary Realtime voice: wake word, follow-ups, and silent dismissal.

Run under jarvis-realtime.service on the Pi; never run alongside the
legacy jarvis-voice.service or a second microphone-owning voice process.
Core supplies identity, tools, and short-lived OpenAI credentials.
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
from pathlib import Path
from uuid import uuid4

import numpy as np
import websockets

from openwakeword.model import Model
from environment_camera import capture_environment
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
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Permit common polite lead-ins and trailing conversational particles.
    cleaned = re.sub(r"^(?:okay|ok|alright|well|so|right)\s+", "", cleaned)
    cleaned = re.sub(r"\s+(?:please|for now|then)$", "", cleaned)
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


# Only Pi-local controls are registered here. Core owns all other schemas.
LOCAL_TOOLS = [
    {"type": "function", "name": "finish_conversation",
     "description": "End the voice session silently when the user is clearly dismissing you or saying they are done; call this instead of speaking any farewell.",
     "parameters": {"type": "object", "properties": {}}}
]

async def core_call(url, token, path, payload=None, timeout=25):
    async with httpx.AsyncClient(timeout=timeout) as client:
        if payload is None:
            response = await client.get(url.rstrip("/") + path, headers={"X-Jarvis-Token":token})
        else:
            response = await client.post(url.rstrip("/") + path, headers={"X-Jarvis-Token":token}, json=payload)
        response.raise_for_status()
        return response.json()


async def restore_recent_dialogue(ws, turns):
    """Seed the new Realtime conversation with prior text messages in chronological order.

    These messages are historical context, never synthetic current audio. Wait for
    the server to acknowledge every item before capturing the current utterance.
    """
    messages = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("text")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        messages.append((role, content))

    # The dismissal is an interaction boundary, not the topic we need to resume.
    while messages and messages[-1][0] == "user" and is_dismissal(messages[-1][1]):
        messages.pop()

    if not messages:
        print("[REALTIME] No historical dialogue to restore", flush=True)
        return

    for role, content in messages:
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": role, "content": [
                {"type": "input_text" if role == "user" else "output_text",
                 "text": content}
            ]},
        }))

    confirmed = 0
    deadline = time.monotonic() + 15
    while confirmed < len(messages):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Only {confirmed}/{len(messages)} historical messages acknowledged")
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        kind = event.get("type")
        if kind == "error":
            raise RuntimeError("Realtime rejected historical context: " + str(event.get("error")))
        if kind == "conversation.item.done":
            confirmed += 1
    print(f"[REALTIME] Restored {confirmed} historical dialogue messages", flush=True)


async def capture_transcript(role, transcript):
    """Best-effort durable Core capture; never interrupt the spoken exchange."""
    text = (transcript or "").strip()
    if not text:
        return
    try:
        await core_call(CORE_URL, CORE_TOKEN, "/realtime/transcript", {
            "session_id": SESSION_ID,
            "turn_id": uuid4().hex,
            "role": role,
            "text": text[:12000],
        }, timeout=8)
    except Exception as exc:
        print("[REALTIME] Transcript persistence failed:", repr(exc), flush=True)


async def speak_turn(ws, head):
    first = True
    audio_proc = None
    started_at = time.monotonic()
    await ws.send(json.dumps({"type": "response.create"}))
    calls = []
    spoken_transcript = ""
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
                spoken_transcript += event.get("transcript", "") or ""
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
    await capture_transcript("assistant", spoken_transcript)
    if calls:
        for call in calls:
            if call.get("name") == "finish_conversation":
                print("[REALTIME] Dismissal requested by model.", flush=True)
                return False
            try:
                arguments = json.loads(call.get("arguments") or "{}")
                if call["name"] == "inspect_environment":
                    print("[REALTIME] Capturing three camera views...", flush=True)
                    arguments["_capture_images"] = await capture_environment(head)
                result = await core_call(CORE_URL, CORE_TOKEN, "/realtime/tool",
                                         {"name": call["name"], "arguments": arguments},
                                         timeout=(90 if call["name"] == "inspect_environment" else
                                                  45 if call["name"] in {"set_lidar_service", "reboot_pi"}
                                                  else 25))
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
    await capture_transcript("user", transcript)
    if is_dismissal(transcript):
        print("[REALTIME] Dismissed: close silently.", flush=True)
        return False
    return await speak_turn(ws, HEAD)


# A boot announcement is deliberately not a conversation: no user input,
# no tools, no transcript persistence and no follow-up listening window.
BOOT_ID_FILE = Path("/proc/sys/kernel/random/boot_id")
BOOT_ANNOUNCED_FILE = Path("/tmp/jarvis-realtime-announced-boot-id")
BOOT_GREETING = "Jarvis online and ready."


def needs_boot_announcement():
    """Only advertise readiness once per physical Pi boot."""
    boot_id = BOOT_ID_FILE.read_text(encoding="ascii").strip()
    if not boot_id:
        raise RuntimeError("Kernel boot ID is unavailable")
    try:
        announced = BOOT_ANNOUNCED_FILE.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        announced = None
    return boot_id if announced != boot_id else None


async def speak_boot_announcement(head, core_url, core_token):
    """Produce one isolated, no-follow-up Realtime speech response."""
    boot_id = needs_boot_announcement()
    if boot_id is None:
        print("[REALTIME] Boot greeting already played for this boot", flush=True)
        return

    credential = await core_call(core_url, core_token, "/realtime/client-secret", {})
    proc = None
    played_bytes = 0
    await head.set("speaking")
    try:
        async with websockets.connect(
            REALTIME_URL,
            additional_headers={"Authorization": "Bearer " + credential["value"]},
            max_size=16 * 1024 * 1024,
            open_timeout=15,
        ) as ws:
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime", "model": MODEL,
                    "instructions": (
                        "You are Jarvis. This is an automatic boot-ready notice, "
                        "not an interactive conversation. Speak exactly: "
                        + BOOT_GREETING
                        + " Do not ask a question or invite a response."
                    ),
                    "tools": [],
                    "output_modalities": ["audio"],
                    "audio": {"output": {
                        "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                        "voice": "ash",
                    }},
                },
            }))
            await receive_until(ws, "session.updated", timeout=15)
            await ws.send(json.dumps({
                "type": "response.create",
                "response": {"instructions": (
                    "Say only: " + BOOT_GREETING + " Then stop speaking."
                )},
            }))
            completed = False
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                kind = event.get("type")
                if kind == "error":
                    raise RuntimeError(str(event.get("error")))
                if kind == "response.output_audio.delta":
                    if proc is None:
                        proc = await asyncio.create_subprocess_exec(
                            "aplay", "-q", "-D", DEVICE, "-t", "raw",
                            "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                            "-c", "1", stdin=asyncio.subprocess.PIPE,
                        )
                    block = base64.b64decode(event["delta"])
                    played_bytes += len(block)
                    proc.stdin.write(block)
                    await proc.stdin.drain()
                elif kind == "response.done":
                    completed = event.get("response", {}).get("status") == "completed"
                    break

            if not completed or not played_bytes:
                raise RuntimeError("Boot greeting produced no completed audio")
        if proc is None:
            raise RuntimeError("Boot greeting audio process did not start")
        proc.stdin.close()
        await asyncio.wait_for(proc.wait(), timeout=30)
        if proc.returncode != 0:
            raise RuntimeError("Boot greeting audio playback failed")
        BOOT_ANNOUNCED_FILE.write_text(boot_id + "\n", encoding="ascii")
        print("[REALTIME] Boot greeting played; voice ready", flush=True)
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        await head.set("idle")


async def main(args):
    global HEAD, CORE_URL, CORE_TOKEN, SESSION_ID
    CORE_URL = args.core_url
    CORE_TOKEN = os.environ.get("JARVIS_INTERFACE_TOKEN") or getpass.getpass("Jarvis Core token: ")
    # Session mechanics stay in code; vocal delivery is edited on Core.
    session_rules = (
        "\nVoice session operating rules:\n"
        "- If the user clearly ends the conversation, call finish_conversation "
        "without another spoken response.\n"
        "- Request live status through get_robot_status and relevant prior "
        "experiences through search_memories; never guess sensor data.\n"
        "- Do not narrate stage directions.\n"
    )

    wake = Model(wakeword_models=["hey jarvis"], inference_framework="onnx")
    HEAD = HeadExpressions()
    await HEAD.start()
    try:
        # No wake word is needed for this one-time boot readiness notice.
        try:
            await speak_boot_announcement(HEAD, CORE_URL, CORE_TOKEN)
        except Exception as exc:
            print("[REALTIME] Boot greeting unavailable:", repr(exc), flush=True)
        while True:
            await HEAD.set("idle")
            initial_wav = await listen_for_command(wake, HEAD)
            await HEAD.set("thinking")
            opened = time.monotonic()
            SESSION_ID = uuid4().hex
            try:
                context = await core_call(CORE_URL, CORE_TOKEN, "/realtime/context")
                instructions = (context["instructions"] + "\n\n" +
                                context["voice_instructions"] + session_rules)
                # Fetch reference dialogue before opening a fresh Realtime session.
                # Restore it as actual conversation items after session.updated.
                recent_turns = []
                try:
                    recent = await core_call(CORE_URL, CORE_TOKEN,
                                             "/realtime/recent-conversation", timeout=8)
                    recent_turns = recent.get("turns", [])
                    print(f"[REALTIME] Fetched {len(recent_turns)} historical dialogue turns",
                          flush=True)
                except Exception as exc:
                    print("[REALTIME] Recent context unavailable:", repr(exc), flush=True)
                core_tools = context["tools"]
                if not isinstance(core_tools, list) or not all(
                    isinstance(t, dict) and isinstance(t.get("name"), str)
                    for t in core_tools
                ):
                    raise ValueError("Core returned invalid Realtime tool definitions")
                names = [t["name"] for t in core_tools]
                if "finish_conversation" in names or len(names) != len(set(names)):
                    raise ValueError("Core tool names conflict with local session controls")
                session_tools = core_tools + LOCAL_TOOLS
                credential = await core_call(CORE_URL, CORE_TOKEN, "/realtime/client-secret", {})
                print("[REALTIME] Credential received from Core.", flush=True)
                async with websockets.connect(
                    REALTIME_URL,
                    additional_headers={"Authorization": "Bearer " + credential["value"]},
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
                            "tools": session_tools,
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
                                    "voice": "ash",
                                },
                            },
                        },
                    }))
                    await receive_until(ws, "session.updated", timeout=15)
                    try:
                        await restore_recent_dialogue(ws, recent_turns)
                    except Exception as exc:
                        print("[REALTIME] History restoration failed:", repr(exc), flush=True)
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
