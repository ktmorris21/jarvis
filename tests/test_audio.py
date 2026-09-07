import asyncio
import base64

from body_services.picar.abilities import PiCarAbilities


class FakeHardware:
    def stop(self): pass


class FakeAudio:
    def __init__(self): self.played = None
    async def play_wav_base64(self, encoded):
        self.played = base64.b64decode(encoded)


def test_speaker_ability_plays_audio():
    async def run():
        audio = FakeAudio()
        abilities = PiCarAbilities(FakeHardware(), audio)
        result = await abilities.execute("speaker", {
            "audio_wav_base64": base64.b64encode(b"RIFFfake").decode(),
            "text": "hello",
        })
        assert audio.played == b"RIFFfake"
        assert result["played"] is True
    asyncio.run(run())
