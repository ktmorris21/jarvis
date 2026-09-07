# Jarvis PiCar hardware state

Current physical state:

- Raspberry Pi 4 body controller
- PiCar-X drive + steering
- camera pan/tilt
- camera
- USB audio input/output
- LiDAR physically mounted, not yet integrated
- ultrasonic sensor removed

## Code implications

The PiCar body no longer calls `Picarx.get_distance()` and no longer assumes
an ultrasonic sensor exists.

Forward/backward movement remains locally bounded by:

- maximum speed
- maximum move duration
- steering-angle limits
- stop in `finally`

There is now a generic `obstacle_provider` seam in `PiCarAbilities`. It is
unused today. When LiDAR work begins, a local LiDAR safety component can plug
into that seam without changing Core's movement semantics.

Core continues to request:

```text
move(direction, speed, duration_ms, steering_deg)
```

The body remains the final authority on how/if that request is executed.
