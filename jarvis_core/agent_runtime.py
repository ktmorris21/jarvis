"""Phase A: one Core-owned agent with read-only, bounded retrieval tools."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from .config import settings
from .abilities import tool_schemas, execute_tool
from .identity import identity_instructions
from .memory import memory
from .persistence.repository import repository
from .state import state

log = logging.getLogger(__name__)
_turn_lock = asyncio.Lock()
_pending_status: dict[str, asyncio.Future] = {}
_session = None
# Session ID was rotated to reset conversational history; long-term memory is preserved.
SESSION_ID = "jarvis-primary-after-20261031-reset"


# Only deliberate actions and targeted retrieval belong in the model's tool list.
# Operational telemetry is supplied in context, not exposed as query tools.
AGENT_TOOL_NAMES = frozenset({
    "search_memories",
    "set_audio_level",
    "set_lidar_service",
    "reboot_pi",
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
        "robot_status": robot_status_context or {
            "available": False,
            "reason": "Current ROS status unavailable",
        },
    }
    guidance = (
        "World state: use the timestamped robot_status snapshot for current "
        "robot-health questions. It takes precedence over old conversation and "
        "memories. If a requested reading is missing or unavailable, say so "
        "without guessing. This snapshot does not authorize navigation safety decisions. "
        "Use tools only for explicitly requested actions or information absent "
        "from the supplied context; search memories for historical information."
    )
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


def search_memory_data(query: str) -> list[dict]:
    results = memory.retrieve(query[:500], limit=5)
    return [{"id": m["id"], "type": m["memory_type"], "content": m["content"],
             "created_at": m.get("created_at")} for m in results]


def _session_instance():
    global _session
    if _session is None:
        from agents.extensions.memory import SQLAlchemySession

        url = settings.database_url
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        elif url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("sqlite:///"):
            url = "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
        elif not (url.startswith("postgresql+asyncpg://") or
                  url.startswith("sqlite+aiosqlite://")):
            raise ValueError("Agent session requires PostgreSQL or SQLite database")
        _session = SQLAlchemySession.from_url(SESSION_ID, url=url, create_tables=True)
    return _session


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
    # All interfaces share one continuing conversation; serialize runs to avoid
    # racing updates to the session or concurrent Core reasoning.
    hooks = ModelTimingHooks()
    queued_at = time.perf_counter()
    async with _turn_lock:
        run_started = time.perf_counter()
        log.warning("[VOICE PROFILE] agent_queue=%.3fs", run_started - queued_at)
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
