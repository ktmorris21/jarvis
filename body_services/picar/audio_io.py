import asyncio
import base64
import os
import tempfile


class AudioIO:
    def __init__(self, input_device: str, output_device: str, record_seconds: int = 5):
        self.input_device = input_device
        self.output_device = output_device
        self.record_seconds = record_seconds

    async def record_once(self) -> bytes:
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                "arecord", "-q",
                "-D", self.input_device,
                "-f", "S16_LE",
                "-r", "16000",
                "-c", "1",
                "-d", str(self.record_seconds),
                path,
            )
            rc = await proc.wait()
            if rc != 0:
                raise RuntimeError(f"arecord exited with status {rc}")
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    async def play_wav_base64(self, encoded: str) -> None:
        data = base64.b64decode(encoded)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(data)
            proc = await asyncio.create_subprocess_exec(
                "aplay", "-q", "-D", self.output_device, path
            )
            rc = await proc.wait()
            if rc != 0:
                raise RuntimeError(f"aplay exited with status {rc}")
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
