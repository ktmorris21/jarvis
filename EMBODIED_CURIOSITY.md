# Jarvis — Embodied Curiosity POC

This phase gives Jarvis a very small self-initiated physical behavior loop.

## Core curiosity

Curiosity is a persistent Core drive, just like the existing social/boredom signals.

Defaults:

```text
initial curiosity        0.20
trigger                  0.75
increment / heartbeat    0.01
heartbeat                2 seconds
cooldown                 45 seconds
```

At the defaults, idle curiosity takes roughly two minutes to cross the trigger.

Any active goal suppresses idle curiosity. Goal-directed behavior outranks wandering.

A successful exploratory action resets curiosity to `0.18`.

User speech and new visual observations also reduce curiosity somewhat.

## What Jarvis does

When curiosity crosses threshold, Core finds any connected interface whose type is:

```text
mobile_body
```

and whose capabilities include `look_around` or `move`.

It alternates between:

```text
look_around
```

and, when available:

```text
move forward
speed 18
duration 350 ms
```

Core is not hard-coded to the PiCar-X or `picar-main`.

## Look-around

The body locally performs:

```text
pan -28°
pan +28°
center 0°
```

Because event-driven vision is already active, moving the camera should naturally
produce scene-change triggers and new semantic visual observations.

## Local ultrasonic collision handling

The stock PiCar-X front ultrasonic sensor is read through the SunFounder library's:

```python
Picarx.get_distance()
```

The body checks distance:

1. before forward motion;
2. about every 50 ms while moving.

Default collision threshold:

```text
22 cm
```

Run with a different threshold:

```bash
--collision-distance-cm 30
```

If the ultrasonic reading is unavailable or invalid, forward motion is refused/stopped.

Backward motion is not blocked by the front sensor.

## Deploy / run

Deploy the complete repository to Railway as usual.

The Pi command remains your existing one:

```bash
python3 -m body_services.picar.main   --url https://jarvis-production-110e.up.railway.app   --token YOUR_TOKEN   --audio-input plughw:5,0   --audio-output plughw:5,0   --vad   --auto-vision
```

The new `look_around` capability is advertised automatically.

## Fast curiosity test

For testing only, set Railway:

```text
JARVIS_CURIOSITY_TRIGGER=0.30
JARVIS_CURIOSITY_INCREMENT=0.05
JARVIS_CURIOSITY_COOLDOWN_SECONDS=10
```

Jarvis should begin an exploratory action quickly.

After validating it, return to:

```text
JARVIS_CURIOSITY_TRIGGER=0.75
JARVIS_CURIOSITY_INCREMENT=0.01
JARVIS_CURIOSITY_COOLDOWN_SECONDS=45
```

## Inspect

`GET /state` exposes:

```text
curiosity
last_curiosity_ability
last_curiosity_action_at
```

`GET /actions` records the Core-originated action and the body result.

This is deliberately not navigation, SLAM, or planning. It proves only that
Jarvis can become curious, act through a body without being asked, visually
observe the consequences, and locally avoid driving straight into an obstacle.
