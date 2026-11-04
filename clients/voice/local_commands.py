"""Offline, deliberately narrow controls for Jarvis's Pi voice interface.

No Core or Agent requests are made here. Recognition uses a locally installed
Vosk English model and strict full-utterance matching. State is ephemeral:
reboot/shutdown/arming require a fresh second utterance within 20 seconds.

Voice recognition is not authentication. Restrict microphone access and keep
an independent physical motor cutoff.
"""
import asyncio
import json
import os
import re
import subprocess
import time
import wave
from io import BytesIO
from pathlib import Path

DEFAULT_MODEL_PATH = "/home/shadowfax/jarvis/models/vosk-model-small-en-us-0.15"
CONFIRM_SECONDS = 20

def normalize(utterance):
    text = re.sub(r"[^a-z0-9 ]", " ", utterance.lower().replace("’", "'"))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:hey )?jarvis\s+", "", text)
    return re.sub(r"\s+(?:please)$", "", text).strip()

COMMANDS = {
    "arm motors": "arm",
    "arm the motors": "arm",
    "disarm motors": "disarm",
    "disarm the motors": "disarm",
    "reboot": "reboot",
    "reboot jarvis": "reboot",
    "restart jarvis": "reboot",
    "power down": "poweroff",
    "power down jarvis": "poweroff",
    "shut down": "poweroff",
    "shut down jarvis": "poweroff",
}
PROMPTS = {
    "arm": ("Say confirm arm motors.", "confirm arm motors"),
    "reboot": ("Say confirm reboot.", "confirm reboot"),
    "poweroff": ("Say confirm power down.", "confirm power down"),
}
# Disarm is intentionally a single utterance for rapid operator control.

# Vosk's unrestricted recognizer has misheard 'Hey Jarvis, arm motors'
# as 'he drove his arm motors'. Its small language model performs much better
# with a narrow task grammar. [unk] permits unrelated speech to be rejected
# rather than forced into a command phrase.
LOCAL_PHRASES = tuple(COMMANDS) + tuple(prompt[1] for prompt in PROMPTS.values())
LOCAL_GRAMMAR = sorted(set(
    variant
    for phrase in LOCAL_PHRASES
    for variant in (phrase, "jarvis " + phrase, "hey jarvis " + phrase)
)) + ["[unk]"]

# Explicit end-of-conversation phrases recognized locally, without Core.
# Exact full-utterance matches only: never cut off a longer spoken question.
# Vosk often emits expanded forms ("that will" rather than "that'll").
CLOSING_PHRASES = (
    "thank you",
    "thanks",
    "thanks jarvis",
    "thank you jarvis",
    "that's all",
    "that's all thank you",
    "that is all",
    "that is all thank you",
    "that'll be all",
    "that'll be all thank you",
    "that will be all",
    "that will be all thank you",
    "that be all",
    "thank you that's all",
    "thank you that will be all",
    "goodbye",
    "goodbye jarvis",
    "good night jarvis",
    "stop listening",
    "end conversation",
)
# Vosk grammar entries need plain spoken words, not apostrophe-normalized
# tokens. Add explicit expanded equivalents for contracted phrases.
CLOSING_GRAMMAR = sorted(set(CLOSING_PHRASES) |
    {"that ll be all", "that ll be all thank you",
     "that s all", "that s all thank you"}) + ["[unk]"]
CLOSING_NORMALIZED = frozenset(normalize(phrase) for phrase in CLOSING_PHRASES) | {
    "that ll be all", "that ll be all thank you",
    "that s all", "that s all thank you",
}



class LocalCommands:
    def __init__(self, model_path=None):
        self.pending = None
        self.pending_until = 0.0
        self._recognizer_model = None
        self.model_path = Path(model_path or os.environ.get("JARVIS_VOSK_MODEL", DEFAULT_MODEL_PATH))
        if self.model_path.is_dir():
            try:
                from vosk import Model, SetLogLevel
                SetLogLevel(-1)
                self._recognizer_model = Model(str(self.model_path))
                print("[LOCAL] Offline Vosk command recognition enabled", flush=True)
            except Exception as exc:
                print(f"[LOCAL] Vosk unavailable: {exc!r}", flush=True)
        else:
            print("[LOCAL] Offline command model missing: " + str(self.model_path), flush=True)

    @property
    def available(self):
        return self._recognizer_model is not None

    def transcribe(self, wav, grammar=LOCAL_GRAMMAR):
        """Use the narrow safety-command grammar by default.

        Passing None explicitly selects unrestricted recognition, exclusively
        for the conversational sign-off fallback.
        """
        from vosk import KaldiRecognizer
        with wave.open(BytesIO(wav), "rb") as wf:
            if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                raise ValueError("Expected 16 kHz mono 16-bit PCM")
            grammar_json = json.dumps(grammar) if grammar is not None else None
            rec = (KaldiRecognizer(self._recognizer_model, 16000, grammar_json)
                   if grammar_json is not None
                   else KaldiRecognizer(self._recognizer_model, 16000))
            while True:
                block = wf.readframes(4000)
                if not block:
                    break
                rec.AcceptWaveform(block)
        result = json.loads(rec.FinalResult())
        return result.get("text", "")

    async def is_closing_phrase(self, wav):
        """Match exact full-utterance closers; never send recognized closers to Core."""
        if not self.available:
            return False
        narrow = await asyncio.to_thread(self.transcribe, wav, CLOSING_GRAMMAR)
        closing = normalize(narrow) in CLOSING_NORMALIZED
        if not closing:
            # Restricted Vosk may classify real short phrases as [unk].
            # Try the unrestricted transcript too, but keep strict exact matching.
            free = await asyncio.to_thread(self.transcribe, wav, None)
            closing = normalize(free) in CLOSING_NORMALIZED
            print(f"[FOLLOWUP] Closer recognition narrow={narrow!r} free={free!r} matched={closing}", flush=True)
        else:
            print(f"[FOLLOWUP] Closing phrase recognized: {narrow!r}", flush=True)
        return closing

    async def _ros_armed(self, armed):
        # Restrict to fixed trusted service and fixed boolean request.
        code = "true" if armed else "false"
        args = [
            "/bin/bash", "-c",
            "source /opt/ros/jazzy/setup.bash && "
            "source /home/shadowfax/ros2_ws/install/setup.bash && "
            'exec ros2 service call /jarvis_drive/set_armed std_srvs/srv/SetBool "{data: ' + code + '}"',
        ]
        return await self._run(args, timeout=12)

    async def _run(self, argv, timeout=12):
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("Local control timed out")
        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        if proc.returncode != 0 or "success=False" in output or "success: false" in output:
            raise RuntimeError(output.strip()[-250:] or "Local control failed")
        return output

    async def _execute(self, action):
        if action in ("arm", "disarm"):
            await self._ros_armed(action == "arm")
            return "Motors armed." if action == "arm" else "Motors disarmed."
        if action in ("reboot", "poweroff"):
            # Arrange the operation after the acknowledgement is played.
            return "Rebooting Jarvis." if action == "reboot" else "Powering down Jarvis."
        raise ValueError("Unexpected local command")

    async def act(self, audio):
        """Return (handled, spoken_reply, deferred_system_action).

        For unmatched speech, returns (False, None, None); caller passes the
        original wav unchanged to Core. Awaiting confirmation intercepts only
        the exact confirmation; anything else cancels and returns to Core.
        """
        if not self.available:
            return False, None, None
        transcript = await asyncio.to_thread(self.transcribe, audio)
        normalized = normalize(transcript)
        print(f"[LOCAL] Grammar transcript={normalized!r} (raw={transcript!r})", flush=True)

        if self.pending and time.monotonic() > self.pending_until:
            self.pending = None
        if self.pending is not None:
            action = self.pending
            self.pending = None
            if normalized == PROMPTS[action][1]:
                if action in ("reboot", "poweroff"):
                    return True, await self._execute(action), action
                try:
                    return True, await self._execute(action), None
                except Exception as exc:
                    print("[LOCAL] Arm failed:", repr(exc), flush=True)
                    return True, "I couldn't arm the motors. Check the drive service.", None
            # A different recognized command may still be handled normally.
        action = COMMANDS.get(normalized)
        if action is None:
            return False, None, None
        if action == "disarm":
            try:
                return True, await self._execute(action), None
            except Exception as exc:
                print("[LOCAL] Disarm failed:", repr(exc), flush=True)
                return True, "Motor disarm failed. Use the physical power switch.", None
        if action in PROMPTS:
            self.pending = action
            self.pending_until = time.monotonic() + CONFIRM_SECONDS
            return True, PROMPTS[action][0], None
        return True, await self._execute(action), None

    async def system_action(self, action):
        if action not in ("reboot", "poweroff"):
            raise ValueError("Invalid power action")
        # Never use a shell or accept untrusted arguments.
        await self._run(["/usr/bin/sudo", "-n", "/usr/bin/systemctl", action], timeout=8)
