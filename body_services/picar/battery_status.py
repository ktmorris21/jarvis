"""Read PiCar-X Robot HAT battery voltage, without initializing PiCarx or motors.

Run with the system Python on the Pi. A4 has an onboard battery-voltage divider.
Voltage-based charge percent is approximate, especially under load. The ADC does
not measure current direction; charging/drawing status remains unknown.
"""
import json
from datetime import datetime, timezone


def read_battery():
    observed_at = datetime.now(timezone.utc).isoformat()
    result = {
        "available": False,
        "observed_at": observed_at,
        "voltage_v": None,
        "estimated_percent": None,
        "estimate_method": "battery voltage (6.6–8.4 V linear approximation)",
        "power_flow": "unknown",
        "charging": None,
        "drawing_from_battery": None,
        "power_flow_note": "Battery voltage alone cannot distinguish charging from battery discharge. A charging-status pin or current sensor is required.",
    }
    try:
        # Import only the ADC interface: creating Picarx can reset steering.
        from robot_hat import ADC
        raw = ADC("A4").read()
        if not isinstance(raw, (int, float)) or not 0 <= raw <= 4095:
            raise ValueError("ADC A4 reading out of range")
        voltage = float(raw) * 3.3 / 4095 * 3
        if not 5.0 <= voltage <= 10.0:
            raise ValueError("Battery voltage outside expected measurement range")
        result.update({
            "available": True,
            "voltage_v": round(voltage, 3),
            "estimated_percent": round(max(0, min(100, (voltage - 6.6) / 1.8 * 100))),
        })
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


if __name__ == "__main__":
    print(json.dumps(read_battery(), allow_nan=False))
