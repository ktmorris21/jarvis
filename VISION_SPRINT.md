# Jarvis Realtime: first visual inspection sprint

## Conversation flow

1. Realtime receives a spoken visual question and selects Core-advertised `inspect_environment(question)`.
2. The Pi's Realtime client moves the **camera head only**, using its existing `head_expressions.py` subprocess (left/center/right), and captures three 1280×960 JPEGs with `rpicam-still` or `libcamera-still`.
3. The Pi uploads the images and question over its authenticated HTTPS Core tool call.
4. Railway Core sends all three images and the question in one Responses API request using `JARVIS_VISION_MODEL` (default in `jarvis_core/config.py`).
5. Core returns concise model findings. Realtime voices them.

This prototype intentionally blocks the voice turn until analysis completes, just like the turtle-delay experiment. Wheels do not move. The photo data is transient and is not intentionally written to disk or stored in the memory database.

## Deploy and test

Wait for Railway to redeploy. Update the Pi because its client now implements the camera-capture part:

```bash
cd ~/jarvis
git pull --ff-only
command -v rpicam-still || command -v libcamera-still
sudo systemctl restart jarvis-realtime.service
sudo journalctl -u jarvis-realtime.service -f
```

Optional one-image hardware test (run with the Realtime service stopped, to avoid camera conflicts):

```bash
sudo systemctl stop jarvis-realtime.service
rpicam-still --nopreview --timeout 750 --width 1280 --height 960 --encoding jpg --quality 80 -o /tmp/jarvis-camera-test.jpg
file /tmp/jarvis-camera-test.jpg
sudo systemctl start jarvis-realtime.service
```

If `rpicam-still` is unavailable, use `libcamera-still` in the one-image test. Verify the camera can capture with the same service-user permissions, if needed.

Speak: "Hey Jarvis, what do you see?" Then try "Can you read the writing on that poster?"

## Limitations

- This version supports Pi cameras usable via rpicam-still/libcamera-still CLI, **not** every USB camera device. If capture fails, check whether the camera is CSI or USB and adapt the utility.
- Camera/head expressions must be enabled. The three captures hold one servo orientation at a time; no body movement.
- Core HTTP wait for vision is extended to 90 seconds. Voice interaction is not full-duplex while the tool runs.
- Output is only as reliable as the images. The tool should report uncertainty if something isn't legible.
- Vision model usage is billed separately from Realtime. Images are sent to OpenAI for processing.
