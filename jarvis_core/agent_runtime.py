"""Phase A: one Core-owned agent with read-only, bounded retrieval tools."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone

from .config import settings
from .abilities import tool_schemas, execute_tool
from .identity import identity_instructions, current_identity_profile
from .memory import memory
from .persistence.repository import repository
from .state import state

log = logging.getLogger(__name__)
_turn_lock = asyncio.Lock()
_pending_status: dict[str, asyncio.Future] = {}
_session = None
# Fresh SDK session; the old session is explicitly cleared once below.
# Jarvis's long-term memories and operational state are separate from this session.
PREVIOUS_SESSION_ID = "jarvis-primary-after-20261031-reset"
SESSION_ID = "jarvis-primary-after-20261105-status-reset"
SESSION_RESET_MARKER = "jarvis:agent_sdk_history_cleared_20261105"


# Only deliberate actions and targeted retrieval belong in the model's tool list.
# Operational telemetry is supplied in context, not exposed as query tools.
AGENT_TOOL_NAMES = frozenset({
    "search_memories",
    "set_audio_level",
    "set_lidar_service",
    "reboot_pi",
    "explore",
    "stop_exploring",
    "exploration_status",
    "inspect_environment",
    "set_identity_profile",
    "get_identity_profile",
})


def baseline_context(*, robot_status_context: dict | None = None) -> str:
    """Compose the per-turn identity, goals, and authoritative world snapshot."""
    goals = repository.goals("active")[:settings.context_goal_limit]
    snapshot = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "core_state": {
            "social_drive": round(state.social_drive, 2),
            "boredom": round(state.boredom, 2),
            "curiosity": round(state.curiosity, 2),
        },
        "active_goals": [
            {"kind": g.get("kind"), "description": g.get("description")}
            for g in goals
        ],
        "active_identity_profile": current_identity_profile(),
        "robot_status": robot_status_context or {
            "available": False,
            "reason": "Current ROS status unavailable",
        },
    }
    guidance = Path(__file__).with_name("operational_instructions.md").read_text(
        encoding="utf-8"
    ).strip()
    if not guidance:
        raise ValueError("Core operational instructions are empty")
    return (
        identity_instructions()
        + "\\n\\n"
        + guidance
        + "\\nCurrent world snapshot:\\n"
        + json.dumps(snapshot, default=str)
    )


def deliver_status_result(event_data: dict) -> None:
    """Called by Core's existing COMMAND_RESULT event handler."""
    command_id = event_data.get("command_id")
    future = _pending_status.get(command_id)
    if future and not future.done():
        future.set_result(event_data)


async def get_robot_status_data() -> dict:
    """Request a fresh status result, matched to its command ID with a timeout."""
    from .executive import send_command
    from .models import Command

    command = Command(target="picar-ros", ability="get_robot_status")
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending_status[command.command_id] = future
    try:
        sent, route = await send_command(command)
        if not sent:
            return {"available": False, "reason": route}
        try:
            event = await asyncio.wait_for(future, timeout=settings.agent_status_timeout_seconds)
        except asyncio.TimeoutError:
            return {"available": False, "reason": "Robot status request timed out"}
        if event.get("status") != "complete" or not isinstance(event.get("result"), dict):
            return {"available": False, "reason": event.get("error") or "Status request failed"}
        return {"available": True, "status": event["result"]}
    finally:
        _pending_status.pop(command.command_id, None)


async def pi_control_data(ability: str, data: dict) -> dict:
    """Route an allowlisted Pi operation through Core's authenticated command bus."""
    from .executive import send_command
    from .models import Command

    command = Command(target="picar-control", ability=ability, data=data)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending_status[command.command_id] = future
    try:
        sent, route = await send_command(command)
        if not sent:
            return {"available": False, "reason": route}
        try:
            event = await asyncio.wait_for(future, timeout=35)
        except asyncio.TimeoutError:
            return {"available": False, "reason": "Pi control command timed out"}
        if event.get("status") != "complete" or not isinstance(event.get("result"), dict):
            return {"available": False, "reason": event.get("error") or "Pi operation failed"}
        return {"available": True, **event["result"]}
    finally:
        _pending_status.pop(command.command_id, None)


async def exploration_command_data(ability: str) -> dict:
    """Send a bounded start/stop/status request to the Pi's existing ROS bridge.

    The ROS service returns immediately; the long-running exploration loop is
    owned by ROS, not by a Core tool call or an LLM inference.
    """
    from .executive import send_command
    from .models import Command

    command = Command(target="picar-ros", ability=ability)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending_status[command.command_id] = future
    try:
        sent, route = await send_command(command)
        if not sent:
            return {"available": False, "success": False, "reason": route}
        try:
            event = await asyncio.wait_for(future, timeout=9.0)
        except asyncio.TimeoutError:
            return {"available": False, "success": False, "reason": "ROS exploration command timed out"}
        result = event.get("result")
        if event.get("status") != "complete" or not isinstance(result, dict):
            return {"available": True, "success": False,
                    "reason": event.get("error") or "Exploration command failed"}
        return {"available": True, "success": bool(result.get("success")),
                "message": str(result.get("message", ""))}
    finally:
        _pending_status.pop(command.command_id, None)


async def inspect_environment_data(question: str) -> dict:
    """Capture fresh two-view images through the Pi voice interface and interpret.

    The JPEG payload exists only in the Core command future during inference.
    No image is added to the SDK conversation or permanent Jarvis memory.
    """
    from .executive import send_command
    from .models import Command

    command = Command(target="picar-voice", ability="capture_environment")
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending_status[command.command_id] = future
    try:
        sent, route = await send_command(command)
        if not sent:
            return {"available": False, "reason": route}
        try:
            event = await asyncio.wait_for(future, timeout=70)
        except asyncio.TimeoutError:
            return {"available": False, "reason": "Camera capture timed out"}
        result = event.get("result") or {}
        if event.get("status") != "complete" or not isinstance(result.get("images"), list):
            return {"available": False, "reason": event.get("error") or "Camera capture failed"}
        # Core validates JPEG encodings, sizes, and views before interpretation.
        return await execute_tool(
            "inspect_environment", {"question": question, "_capture_images": result["images"]}
        )
    finally:
        _pending_status.pop(command.command_id, None)


def search_memory_data(query: str) -> list[dict]:
    results = memory.retrieve(query[:500], limit=5)
    return [{"id": m["id"], "type": m["memory_type"], "content": m["content"],
             "created_at": m.get("created_at")} for m in results]


def _agent_session_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    if url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
        return url
    raise ValueError("Agent session requires PostgreSQL or SQLite database")


def _session_instance():
    global _session
    if _session is None:
        from agents.extensions.memory import SQLAlchemySession
        _session = SQLAlchemySession.from_url(
            SESSION_ID, url=_agent_session_url(), create_tables=True
        )
    return _session


async def _clear_previous_agent_history_once() -> None:
    """One-time deletion of only the previous Agents SDK conversation.

    Rotating the active session also prevents old messages entering the
    model's input while this cleanup is being performed.
    """
    if repository.get_state(SESSION_RESET_MARKER):
        return
    from agents.extensions.memory import SQLAlchemySession
    previous = SQLAlchemySession.from_url(
        PREVIOUS_SESSION_ID, url=_agent_session_url(), create_tables=True
    )
    await previous.clear_session()
    repository.upsert_state(
        SESSION_RESET_MARKER,
        "jarvis_setting",
        {"cleared_session_id": PREVIOUS_SESSION_ID,
         "replacement_session_id": SESSION_ID,
         "cleared_at": datetime.now(timezone.utc).isoformat()},
    )
    log.warning("[AGENT SESSION] cleared previous Agents SDK conversation history; new session active")



async def agent_reply(text: str) -> str:
    """Run a bounded agent turn; caller owns speech output; no fallback cognition."""
    from agents import Agent, Runner, FunctionTool, ModelSettings, RunHooks
    from openai.types.shared import Reasoning

    class ModelTimingHooks(RunHooks):
        def __init__(self):
            self.calls = 0
            self.started = None
            self.total = 0.0

        async def on_llm_start(self, context, agent, system_prompt, input_items):
            self.calls += 1
            self.started = time.perf_counter()
            log.warning("[VOICE PROFILE] llm_call=%d started model=%s", self.calls, agent.model)

        async def on_llm_end(self, context, agent, response):
            if self.started is not None:
                elapsed = time.perf_counter() - self.started
                self.total += elapsed
                log.warning("[VOICE PROFILE] llm_call=%d duration=%.3fs", self.calls, elapsed)
                self.started = None


    def make_tool(spec):
        name = spec["name"]

        async def invoke(ctx, raw_arguments):
            tool_started = time.perf_counter()
            try:
                arguments = json.loads(raw_arguments or "{}")
                if name == "inspect_environment":
                    question = arguments.get("question")
                    if (set(arguments) != {"question"} or not isinstance(question, str)
                            or not 1 <= len(question.strip()) <= 500):
                        raise ValueError("inspect_environment requires a question of 1-500 characters")
                    result = await inspect_environment_data(question)
                else:
                    result = await execute_tool(name, arguments)
                return json.dumps(result, default=str)
            except Exception as exc:
                log.warning("Core tool %s failed: %s", name, type(exc).__name__)
                return json.dumps({"available": False, "error": str(exc)})
            finally:
                log.warning("[VOICE PROFILE] tool=%s duration=%.3fs", name, time.perf_counter() - tool_started)

        return FunctionTool(name=name, description=spec["description"],
                            params_json_schema=spec["parameters"],
                            on_invoke_tool=invoke, strict_json_schema=False)

    if settings.agent_reasoning_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Unsupported JARVIS_AGENT_REASONING_EFFORT")
    log.warning("[VOICE PROFILE] model=%s reasoning_effort=%s", settings.agent_model, settings.agent_reasoning_effort)
    robot_status_context = None
    if "picar-ros" in state.interfaces:
        prefetch_start = time.perf_counter()
        try:
            status_result = await asyncio.wait_for(get_robot_status_data(), timeout=2.0)
            if status_result.get("available") and isinstance(status_result.get("status"), dict):
                robot_status_context = {
                    "available": True,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "age_seconds": round(time.perf_counter() - prefetch_start, 3),
                    "status": status_result["status"],
                }
            else:
                log.warning("[VOICE PROFILE] status_prefetch unavailable=%s", status_result.get("reason"))
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("[VOICE PROFILE] status_prefetch failed=%s", type(exc).__name__)
        finally:
            log.warning("[VOICE PROFILE] status_prefetch=%.3fs available=%s",
                        time.perf_counter() - prefetch_start, robot_status_context is not None)
    log.warning("[VOICE PROFILE] status_snapshot_keys=%s", list((robot_status_context or {}).get("status", {}).keys()))
    if robot_status_context:
        readings = robot_status_context["status"]
        log.warning(
            "[ROBOT STATUS] lidar_active=%s scan_age=%s "
            "mapping_available=%s map_recent=%s map_age=%s "
            "pose_available=%s battery_available=%s battery_error=%s "
            "exploration_available=%s exploration_mode=%s",
            readings.get("lidar", {}).get("active"),
            readings.get("lidar", {}).get("last_scan_age_seconds"),
            readings.get("mapping", {}).get("available"),
            readings.get("mapping", {}).get("recent_update"),
            readings.get("mapping", {}).get("last_map_age_seconds"),
            readings.get("pose", {}).get("available"),
            readings.get("battery", {}).get("available"),
            readings.get("battery", {}).get("error"),
            readings.get("exploration", {}).get("available"),
            readings.get("exploration", {}).get("mode"),
        )
    # All interfaces share one continuing conversation; serialize runs to avoid
    # racing updates to the session or concurrent Core reasoning.
    hooks = ModelTimingHooks()
    queued_at = time.perf_counter()
    async with _turn_lock:
        # Perform the one-time database cleanup before any new agent turn.
        await _clear_previous_agent_history_once()
        run_started = time.perf_counter()
        log.warning("[VOICE PROFILE] agent_queue=%.3fs", run_started - queued_at)
        agent = Agent(
            name="Jarvis",
            model=settings.agent_model,
            instructions=baseline_context(robot_status_context=robot_status_context),
            tools=[make_tool(spec) for spec in tool_schemas()
                   if spec["name"] in AGENT_TOOL_NAMES],
            model_settings=ModelSettings(
                parallel_tool_calls=False,
                reasoning=Reasoning(effort=settings.agent_reasoning_effort),
            ),
        )
        try:
            result = await asyncio.wait_for(
                Runner.run(agent, text, session=_session_instance(), hooks=hooks,
                           max_turns=settings.agent_max_turns),
                timeout=settings.agent_timeout_seconds,
            )
        finally:
            log.warning("[VOICE PROFILE] agent_run=%.3fs (includes tool calls); llm_calls=%d llm_total=%.3fs", time.perf_counter() - run_started, hooks.calls, hooks.total)
    speech = str(result.final_output or "").strip()
    if not speech:
        raise RuntimeError("Agent produced an empty response")
    usage = result.context_wrapper.usage
    log.info("agent turn: requests=%s input=%s output=%s",
             usage.requests, usage.input_tokens, usage.output_tokens)
    return speech
