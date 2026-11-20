#!/usr/bin/env python3
"""Manual, local-only object detection viewer for Jarvis's existing camera socket.

This diagnostic does not send events to Core, control servos, or move the robot.
Open the viewer via an SSH tunnel; the HTTP listener defaults to localhost.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Jarvis vision diagnostic</title>
<style>body{background:#15191e;color:#e8edf2;font:16px system-ui;margin:24px}
img{max-width:100%;height:auto;border-radius:12px;background:#30363c}
pre{white-space:pre-wrap}small{color:#9da8b3}</style></head><body>
<h2>Jarvis — Local Object Detection</h2>
<p><small>Manual diagnostic only. No Core calls or autonomous actions.</small></p>
<img id="frame" alt="Waiting for camera frame"><pre id="status">Starting…</pre>
<script>
async function update(){
 try{
  const r=await fetch('/detections.json',{cache:'no-store'});
  const d=await r.json();
  document.getElementById('status').textContent=JSON.stringify(d,null,2);
  if(d.frames) document.getElementById('frame').src='/frame.jpg?t='+Date.now();
 }catch(e){document.getElementById('status').textContent=String(e)}
}
setInterval(update,1500); update();
</script></body></html>"""

def request_jpeg(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(20)
        s.connect(path)
        s.sendall(b'{"command":"capture"}\n')
        buffer = bytearray()
        while not buffer.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                raise RuntimeError("Camera socket closed unexpectedly")
            buffer.extend(chunk)
            if len(buffer) > 4_000_000:
                raise RuntimeError("Camera response exceeded size limit")
    response = json.loads(buffer)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Camera capture failed"))
    return base64.b64decode(response["jpeg_base64"], validate=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--socket", default="/run/jarvis-camera/camera.sock")
    p.add_argument("--model", default="yolo26n.pt",
                   help="Ultralytics weights or exported NCNN model directory")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--imgsz", type=int, default=416)
    p.add_argument("--confidence", type=float, default=0.35)
    args = p.parse_args()
    if args.interval < 0.2:
        p.error("--interval must be at least 0.2 seconds")

    import cv2
    import numpy as np
    from ultralytics import YOLO

    model = YOLO(args.model)
    state = {"frames": 0, "detections": [], "inference_ms": None,
             "total_cycle_ms": None, "error": None, "last_frame_at": None}
    lock = threading.Lock()
    latest = None

    def worker():
        nonlocal latest
        while True:
            started = time.monotonic()
            try:
                raw = request_jpeg(args.socket)
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise RuntimeError("Could not decode JPEG")
                t0 = time.perf_counter()
                result = model.predict(frame, imgsz=args.imgsz,
                                       conf=args.confidence, verbose=False)[0]
                infer_ms = round((time.perf_counter() - t0) * 1000, 1)
                boxes = []
                for b in result.boxes:
                    cls = int(b.cls.item())
                    boxes.append({
                        "label": result.names[cls],
                        "confidence": round(float(b.conf.item()), 3),
                        "box_xyxy": [round(float(n), 1) for n in b.xyxy[0].tolist()],
                    })
                annotated = result.plot()
                ok, jpg = cv2.imencode(".jpg", annotated,
                                       [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    raise RuntimeError("Could not encode annotated frame")
                elapsed = round((time.monotonic() - started) * 1000, 1)
                with lock:
                    latest = jpg.tobytes()
                    state.update(frames=state["frames"] + 1,
                                 detections=boxes, inference_ms=infer_ms,
                                 total_cycle_ms=elapsed,
                                 last_frame_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                                 error=None)
                print(f"[VISION] frame={state['frames']} objects={len(boxes)} "
                      f"inference_ms={infer_ms} cycle_ms={elapsed}", flush=True)
            except Exception as exc:
                with lock:
                    state["error"] = f"{type(exc).__name__}: {exc}"
                print(f"[VISION] error={exc}", flush=True)
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with lock:
                data = latest
                metadata = dict(state)
            if self.path.startswith("/frame.jpg") and data is not None:
                payload, mime, code = data, "image/jpeg", 200
            elif self.path.startswith("/detections.json"):
                payload, mime, code = json.dumps(metadata).encode(), "application/json", 200
            elif self.path == "/":
                payload, mime, code = HTML.encode(), "text/html; charset=utf-8", 200
            else:
                payload, mime, code = b"Not found", "text/plain", 404
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *values):
            return

    threading.Thread(target=worker, daemon=True).start()
    print(f"[VISION] Viewer http://{args.host}:{args.port}/ model={args.model}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
