"""Core-owned, shared tool schemas and execution for text and voice models."""
import asyncio
from fastapi import HTTPException
from .config import settings

CORE_TOOLS = {
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
