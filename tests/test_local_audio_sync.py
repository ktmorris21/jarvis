"""Offline local-audio cache validation; no microphone or network required."""
import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "voice"))
from local_audio import LOCAL_REPLIES, cache_file, valid_wav, wav_is_valid_bytes

def make_wav(rate=16000, channels=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b"\x00\x00" * rate * channels)
    return out.getvalue()

class LocalAudioSyncTests(unittest.TestCase):
    def test_wake_phrase_and_fixed_diagnostics_are_in_cache(self):
        self.assertIn("I'm here.", LOCAL_REPLIES)
        self.assertIn("Diagnostics uploaded.", LOCAL_REPLIES)
        self.assertNotIn("Diagnostics uploaded. Report abc123.", LOCAL_REPLIES)

    def test_invalid_audio_rejected(self):
        self.assertFalse(wav_is_valid_bytes(b"not a wav"))
        self.assertFalse(wav_is_valid_bytes(make_wav(rate=44100)))
        self.assertTrue(wav_is_valid_bytes(make_wav()))

    def test_cache_path_is_fixed_and_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict("os.environ", {"JARVIS_LOCAL_AUDIO_CACHE": temp}):
                target = cache_file("I'm here.")
                self.assertTrue(str(target).startswith(temp))
                self.assertIsNone(cache_file("arbitrary generated speech"))
                target.write_bytes(make_wav())
                self.assertTrue(valid_wav(target))
                target.write_bytes(b"invalid")
                self.assertFalse(valid_wav(target))

if __name__ == "__main__":
    unittest.main()
