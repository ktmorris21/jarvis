"""Core-owned, shared tool schemas and execution for text and voice models."""
import asyncio
from fastapi import HTTPException
from .config import settings

CORE_TOOLS = {
    "get_audio_levels": {
        "type": "function", "name": "get_audio_levels",
        "description": "Read Jarvis Pi speaker output and microphone capture gain settings, in percent.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "set_audio_level": {
        "type": "function", "name": "set_audio_level",
        "description": "Set Jarvis Pi speaker playback volume or microphone capture gain. Use a precise 0-100 percent value. Never change unless the user asks.",
        "parameters": {"type": "object", "properties": {
            "device": {"type": "string", "enum": ["speaker", "microphone"]},
            "percent": {"type": "integer", "minimum": 0, "maximum": 100},
        }, "required": ["device", "percent"], "additionalProperties": False},
    },
    "get_lidar_service": {
        "type": "function", "name": "get_lidar_service",
        "description": "Read running state of Jarvis's ROS mapping systemd service (which includes the LiDAR driver). This does not prove LiDAR scan freshness.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "set_lidar_service": {
        "type": "function", "name": "set_lidar_service",
        "description": "Start or stop the Pi's ROS mapping stack, INCLUDING the LiDAR driver. This stops mapping/localization as well as LiDAR; only do so when explicitly requested by the user.",
        "parameters": {"type": "object", "properties": {
            "running": {"type": "boolean"},
        }, "required": ["running"], "additionalProperties": False},
    },
    "reboot_pi": {
        "type": "function", "name": "reboot_pi",
        "description": "Reboot the Jarvis Raspberry Pi. WARNING: disrupts all robot services and conversation. Use ONLY after user explicitly confirms reboot NOW. Requires local administrator enablement. Pass exact confirmation phrase REBOOT JARVIS NOW.",
        "parameters": {"type": "object", "properties": {
            "confirmation": {"type": "string", "enum": ["REBOOT JARVIS NOW"]},
        }, "required": ["confirmation"], "additionalProperties": False},
    },
    "get_robot_status": {
        "type": "function", "name": "get_robot_status",
        "description": "Get current robot, ROS, LiDAR and map health.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "turtle_status": {
        "type": "function", "name": "turtle_status",
        "description": "Check how the imaginary experimental turtle is doing. This intentionally takes approximately ten seconds. Call this when the user asks about the turtle, its mood, or turtle status.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "inspect_environment": {
        "type": "function", "name": "inspect_environment",
        "description": "Use my onboard camera to inspect what I currently see. Choose this for questions about visible objects, scenes, signs, text or visual surroundings; requires taking new photos.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "Specific visual question to answer from new photographs"}
        }, "required": ["question"], "additionalProperties": False},
    },
    "search_memories": {
        "type": "function", "name": "search_memories",
        "description": "Search Jarvis Core's persistent memories.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words or question to search for"}
        }, "required": ["query"], "additionalProperties": False},
    },
}


def tool_schemas():
    return list(CORE_TOOLS.values())


async def execute_tool(name: str, args: dict):
    """Execute one allowlisted tool, never arbitrary model-supplied code."""
    if name not in CORE_TOOLS:
        raise HTTPException(404, "Unknown or disallowed tool")
    if not isinstance(args, dict):
        raise HTTPException(400, "Tool arguments must be an object")
    from .agent_runtime import get_robot_status_data, search_memory_data
    if name in {"get_audio_levels", "set_audio_level", "get_lidar_service",
                "set_lidar_service", "reboot_pi"}:
        # Exact argument validation applies for both Agents SDK and Realtime.
        if name in {"get_audio_levels", "get_lidar_service"} and args:
            raise HTTPException(400, "This tool accepts no arguments")
        if name == "set_audio_level":
            if (set(args) != {"device", "percent"}
                    or args["device"] not in {"speaker", "microphone"}
                    or type(args["percent"]) is not int
                    or not 0 <= args["percent"] <= 100):
                raise HTTPException(400, "Expected valid device and integer percent 0-100")
        if name == "set_lidar_service" and (
                set(args) != {"running"} or type(args["running"]) is not bool):
            raise HTTPException(400, "Expected boolean running")
        if name == "reboot_pi" and (
                set(args) != {"confirmation"}
                or args["confirmation"] != "REBOOT JARVIS NOW"):
            raise HTTPException(400, "Explicit reboot confirmation required")
        from .agent_runtime import pi_control_data
        return await pi_control_data(name, args)

    if name == "inspect_environment" and not args.get("_capture_images"):
        return {"available": False, "reason":
                "Fresh camera capture is unavailable from this interface; "
                "Pi remote camera transport is not yet configured."}
    if name == "inspect_environment":
        question = args.get("question")
        photos = args.get("_capture_images")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            raise HTTPException(400, "question must contain 1–500 characters")
        if not isinstance(photos, list) or len(photos) != 3:
            raise HTTPException(400, "Expected three freshly captured JPEG images")
        import base64
        import httpx
        views = []
        for entry in photos:
            if not isinstance(entry, dict) or entry.get("view") not in ("left", "center", "right"):
                raise HTTPException(400, "Invalid camera view")
            encoded = entry.get("jpeg_base64")
            if not isinstance(encoded, str) or len(encoded) > 2_100_000:
                raise HTTPException(400, "Image missing or too large")
            try:
                blob = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error):
                raise HTTPException(400, "Invalid JPEG encoding")
            if len(blob) > 1_500_000 or not blob.startswith(bytes.fromhex("ffd8")):
                raise HTTPException(400, "Expected JPEG up to 1.5 MB")
            views.append((entry["view"], encoded))
        if len({name for name, _ in views}) != 3:
            raise HTTPException(400, "Expected distinct left, center, right views")
        if not settings.openai_api_key:
            raise HTTPException(503, "Vision model not configured")
        content = [{"type": "input_text", "text":
                    "You are Jarvis's visual perception subsystem. Analyze only these fresh camera "
                    "images. Describe evidence accurately, explicitly note ambiguity and unreadable "
                    "text, and do not invent objects. Answer the question: " + question}]
        for view, encoded in views:
            content.append({"type": "input_text", "text": "Camera view: " + view})
            content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + encoded,
                            "detail": "high"})
        try:
            async with httpx.AsyncClient(timeout=75) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": "Bearer " + settings.openai_api_key},
                    json={"model": settings.vision_model,
                          "input": [{"role": "user", "content": content}],
                          "max_output_tokens": 500},
                )
                response.raise_for_status()
                answer = response.json()
            findings = answer.get("output_text") or " ".join(
                item.get("text", "")
                for output in answer.get("output", [])
                for item in output.get("content", [])
                if item.get("type") == "output_text"
            ).strip()
            if not findings:
                raise ValueError("Vision model returned no text")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Vision analysis failed")
        return {"available": True, "question": question,
                "views": [name for name, _ in views], "findings": findings}
    if name == "turtle_status":
        if args:
            raise HTTPException(400, "turtle_status takes no arguments")
        await asyncio.sleep(10)
        return {"status": "The turtle is happy.", "delay_seconds": 10}
    if name == "get_robot_status":
        if args:
            raise HTTPException(400, "get_robot_status takes no arguments")
        return await get_robot_status_data()
    if name == "search_memories":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise HTTPException(400, "query must be nonempty, max 500 characters")
        return {"memories": search_memory_data(query)}
    raise HTTPException(404, "Unknown or disallowed tool")
