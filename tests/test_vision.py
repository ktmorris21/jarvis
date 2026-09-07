from jarvis_core.vision import VisionObservation


def test_vision_observation_schema():
    obs = VisionObservation(
        summary="A desk and chair are visible.",
        notable=["A chair is in front of the desk."],
        people_visible=False,
        person_count_estimate=0,
        attention_hint="routine",
    )
    assert obs.people_visible is False
    assert obs.attention_hint == "routine"


def test_vision_observation_rejects_bad_attention_hint():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VisionObservation(summary="test", attention_hint="panic")
