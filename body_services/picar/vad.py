from __future__ import annotations

import asyncio
import collections
import math
import struct
import time
import wave
from dataclasses import dataclass
from io import BytesIO


@dataclass
class VadConfig:
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    frame_ms: int = 30
    pre_roll_ms: int = 300
    end_silence_ms: int = 750
    max_utterance_seconds: float = 12.0
    calibration_seconds: float = 1.5
    threshold_multiplier: float = 3.0
    minimum_threshold: int = 350


class EnergyVad:
    """Tiny local voice activity detector.

    It does not recognize speech. It only detects a sustained rise in microphone
    energy and packages the resulting PCM frames into a WAV utterance.
    """

    def __init__(self, input_device: str, config: VadConfig | None = None):
        self.input_device = input_device
        self.config = config or VadConfig()
        self._proc = None
        self._threshold = self.config.minimum_threshold

    @property
    def frame_bytes(self) -> int:
        samples = int(self.config.sample_rate * self.config.frame_ms / 1000)
        return samples * self.config.sample_width * self.config.channels

    @staticmethod
    def rms16(pcm: bytes) -> float:
        if not pcm:
            return 0.0
        count = len(pcm) // 2
        samples = struct.unpack("<" + "h" * count, pcm[: count * 2])
        if not samples:
            return 0.0
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    async def _start_capture(self):
        self._proc = await asyncio.create_subprocess_exec(
            "arecord",
            "-q",
            "-D", self.input_device,
            "-f", "S16_LE",
            "-r", str(self.config.sample_rate),
            "-c", str(self.config.channels),
            "-t", "raw",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _read_frame(self) -> bytes:
        assert self._proc and self._proc.stdout
        data = await self._proc.stdout.readexactly(self.frame_bytes)
        return data

    async def calibrate(self):
        if self._proc is None:
            await self._start_capture()

        frame_count = max(
            1,
            int(self.config.calibration_seconds * 1000 / self.config.frame_ms)
        )
        levels = []
        for _ in range(frame_count):
            frame = await self._read_frame()
            levels.append(self.rms16(frame))

        # Median-like robust baseline without importing statistics-heavy helpers.
        levels.sort()
        baseline = levels[len(levels) // 2] if levels else 0.0
        self._threshold = max(
            self.config.minimum_threshold,
            int(baseline * self.config.threshold_multiplier),
        )
        return {
            "baseline_rms": round(baseline, 1),
            "threshold_rms": self._threshold,
        }

    def _wav_bytes(self, frames: list[bytes]) -> bytes:
        out = BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(self.config.sample_width)
            wf.setframerate(self.config.sample_rate)
            wf.writeframes(b"".join(frames))
        return out.getvalue()

    async def utterances(self):
        if self._proc is None:
            await self._start_capture()
        calibration = await self.calibrate()
        yield {"type": "calibration", **calibration}

        pre_roll_frames = max(1, int(self.config.pre_roll_ms / self.config.frame_ms))
        end_silence_frames = max(1, int(self.config.end_silence_ms / self.config.frame_ms))
        max_frames = max(1, int(self.config.max_utterance_seconds * 1000 / self.config.frame_ms))

        pre_roll = collections.deque(maxlen=pre_roll_frames)
        in_speech = False
        utterance: list[bytes] = []
        silent_frames = 0

        while True:
            frame = await self._read_frame()
            level = self.rms16(frame)

            if not in_speech:
                pre_roll.append(frame)
                if level >= self._threshold:
                    in_speech = True
                    utterance = list(pre_roll)
                    silent_frames = 0
                continue

            utterance.append(frame)

            if level < self._threshold:
                silent_frames += 1
            else:
                silent_frames = 0

            hit_silence = silent_frames >= end_silence_frames
            hit_max = len(utterance) >= max_frames

            if hit_silence or hit_max:
                # Keep the trailing silence. It helps transcription slightly and is tiny.
                wav = self._wav_bytes(utterance)
                duration = len(utterance) * self.config.frame_ms / 1000.0
                yield {
                    "type": "utterance",
                    "wav": wav,
                    "duration_seconds": round(duration, 2),
                    "ended_by": "silence" if hit_silence else "max_duration",
                }
                in_speech = False
                utterance = []
                silent_frames = 0
                pre_roll.clear()

    async def close(self):
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None
