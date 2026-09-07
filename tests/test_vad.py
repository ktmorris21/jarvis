import math
import struct

from body_services.picar.vad import EnergyVad


def pcm_constant(value: int, count: int = 480) -> bytes:
    return struct.pack("<" + "h" * count, *([value] * count))


def test_rms_zero():
    assert EnergyVad.rms16(pcm_constant(0)) == 0


def test_rms_constant_signal():
    value = 1200
    rms = EnergyVad.rms16(pcm_constant(value))
    assert math.isclose(rms, value, rel_tol=0.001)


def test_wav_packaging_has_riff_header():
    vad = EnergyVad("mock")
    wav = vad._wav_bytes([pcm_constant(100), pcm_constant(200)])
    assert wav[:4] == b"RIFF"
    assert b"WAVE" in wav[:16]
