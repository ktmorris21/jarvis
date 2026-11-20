"""Persistent ROS 2 Trigger client for Pi-local operational voice stop.

Run once as /usr/bin/python3 from the ROS environment. stdin/stdout implement
a fixed, line-delimited protocol; no shell input, Core/Agent, or motor arming.
The frontend owns subprocess lifetime. ROS logs go to stderr/systemd.
"""
import json
import sys
import threading
import time

import rclpy
from std_srvs.srv import Trigger

STOP_SERVICE = "/jarvis/motion/stop"


def emit(**data):
    sys.stdout.write(json.dumps(data, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    rclpy.init()
    node = rclpy.create_node("jarvis_voice_stop_client")
    client = node.create_client(Trigger, STOP_SERVICE)
    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()
    try:
        # Discover once at voice startup, instead of per-stop ROS CLI startup.
        ready = False
        for _ in range(10):
            if client.wait_for_service(timeout_sec=1.0):
                ready = True
                break
        if not ready:
            emit(type="error", reason="stop_service_unavailable")
            return 2
        emit(type="ready", service=STOP_SERVICE)
        for raw in sys.stdin:
            if raw.strip() != "STOP":
                emit(type="result", success=False, reason="invalid_command")
                continue
            started = time.monotonic()
            if not client.service_is_ready():
                emit(type="result", success=False, reason="stop_service_unavailable")
                continue
            done = threading.Event()
            try:
                future = client.call_async(Trigger.Request())
                future.add_done_callback(lambda _: done.set())
                if not done.wait(timeout=2.0):
                    emit(type="result", success=False, reason="stop_service_timeout",
                         elapsed_ms=round((time.monotonic() - started) * 1000))
                    continue
                result = future.result()
                emit(type="result", success=bool(result.success),
                     reason=result.message[:240],
                     elapsed_ms=round((time.monotonic() - started) * 1000))
            except Exception as exc:
                emit(type="result", success=False,
                     reason="stop_service_" + type(exc).__name__,
                     elapsed_ms=round((time.monotonic() - started) * 1000))
        return 0
    finally:
        rclpy.shutdown()
        spinner.join(timeout=1.0)
        node.destroy_node()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        emit(type="error", reason="startup_" + type(exc).__name__)
        raise
