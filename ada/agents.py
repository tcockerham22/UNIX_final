"""Sub-agents: delegated, self-contained task runners for Ada.

A sub-agent gets its own system prompt, message history and Ollama tool loop.
It borrows Ada's tools (by default a read-only subset), runs in its own thread,
and returns a single text result to the caller. Agents cannot spawn agents.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import ollama

from . import tools as tool_mod
from .config import Config
from .events import emit, quiet_events

# Safe default: research/read-only tools. Writing files, running commands,
# changing reminders/Home Assistant, etc. require an explicit agent_tools override.
DEFAULT_AGENT_TOOLS = (
    "web_search", "web_fetch", "get_weather", "current_time",
    "list_memories", "read_skill", "list_skills", "list_uploads", "read_upload",
    "read_file", "list_directory", "search_files", "workspace_info", "project_tasks",
    "ada_info",
)

# Never let an agent spawn another agent (depth limit 1).
SPAWN_TOOLS = {"spawn_agent", "spawn_agents"}

TIERS = ("light", "moderate", "deep")


def _tool_call_to_dict(call) -> dict:
    fn = call["function"] if isinstance(call, dict) else call.function
    name = fn["name"] if isinstance(fn, dict) else fn.name
    arguments = fn["arguments"] if isinstance(fn, dict) else fn.arguments
    return {"function": {"name": name, "arguments": arguments or {}}}


def _message_text(message) -> tuple[str, list]:
    if isinstance(message, dict):
        content = message.get("content") or ""
        calls = message.get("tool_calls") or []
    else:
        content = getattr(message, "content", "") or ""
        calls = getattr(message, "tool_calls", None) or []
    if not content:
        thinking = message.get("thinking", "") if isinstance(message, dict) else getattr(message, "thinking", "")
        content = thinking if isinstance(thinking, str) else ""
    return str(content).strip(), [_tool_call_to_dict(c) for c in calls]


def _resolve_model(config: Config, tier: str | None) -> str:
    tier = (tier or "").strip().lower() if isinstance(tier, str) else ""
    if tier in TIERS:
        return getattr(config, f"{tier}_model", None) or config.light_model
    configured = (getattr(config, "agent_model", "") or "").strip()
    if configured in TIERS:
        return getattr(config, f"{configured}_model", None) or config.light_model
    return configured or config.light_model


def _tool_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[\s,]+", value)
    return [str(v).strip() for v in value if str(v).strip()]


def _resolve_tools(config: Config, tools=None) -> tuple[list[dict], list[str]]:
    names = _tool_names(tools)
    if not names:
        names = _tool_names(getattr(config, "agent_tools", None))
    if not names:
        names = list(DEFAULT_AGENT_TOOLS)
    names = [name for name in names if name not in SPAWN_TOOLS]
    by_name = {tool["function"]["name"]: tool for tool in tool_mod.TOOLS}
    schemas = [by_name[name] for name in names if name in by_name]
    return schemas, [tool["function"]["name"] for tool in schemas]


def _system_prompt(task: str, config: Config, tool_names: list[str]) -> str:
    return (
        "You are a sub-agent working for Ada, a local personal assistant. "
        "Complete exactly one delegated task, then stop.\n\n"
        "Rules:\n"
        "- Work autonomously. Do not ask the user questions.\n"
        "- Use your tools to gather facts or do the work. Trust tool results over memory or guesses.\n"
        "- Return ONLY the final result: concise, concrete, and self-contained. No preamble, "
        "no 'I have completed the task', no narration of your steps. Use plain text unless the "
        "task explicitly asks for a document or code.\n"
        "- If you cannot finish, say so plainly and explain what blocked you. Never claim a "
        "tool action succeeded if it failed.\n"
        "- You cannot delegate further; you have no agent-spawning tool.\n\n"
        f"Today is {datetime.now():%A, %B %d, %Y}.\n"
        f"User: {config.user_name}\n"
        f"Tools: {', '.join(tool_names) if tool_names else '(none)'}\n\n"
        f"TASK:\n{task}\n"
    )


def run_subagent(task: str, config: Config, memory, *, model_tier: str | None = None,
                 tools=None, max_rounds: int | None = None, timeout_s: float | None = None,
                 agent_id: str | None = None) -> str:
    """Run one delegated task in the current thread and return its final text result."""
    task = (task or "").strip() if isinstance(task, str) else ""
    if not task:
        return "ERROR: no task provided to sub-agent."
    if not getattr(config, "agents_enabled", True):
        return "ERROR: sub-agents are disabled (agents_enabled=false)."

    agent_id = agent_id or f"a{int(time.time() * 1000)}"
    model = _resolve_model(config, model_tier)
    schemas, names = _resolve_tools(config, tools)
    try:
        max_rounds = max(1, int(max_rounds or getattr(config, "agent_max_rounds", 6) or 6))
    except (TypeError, ValueError):
        max_rounds = 6
    try:
        timeout_s = float(timeout_s or getattr(config, "agent_timeout_s", 120) or 120)
    except (TypeError, ValueError):
        timeout_s = 120.0
    try:
        max_tokens = int(getattr(config, "agent_max_tokens", 2048) or 2048)
    except (TypeError, ValueError):
        max_tokens = 2048

    messages = [
        {"role": "system", "content": _system_prompt(task, config, names)},
        {"role": "user", "content": task},
    ]
    options = {
        "temperature": 0.3,
        "num_ctx": min(getattr(config, "num_ctx", 4096), 8192),
        "num_predict": max_tokens,
    }

    emit("agent", id=agent_id, task=task[:300], model=model, tools=names,
         status="start", force=True)
    started = time.monotonic()
    final = ""
    status = "error"

    try:
        with quiet_events():
            for _round in range(max_rounds):
                elapsed = time.monotonic() - started
                if elapsed >= timeout_s:
                    final = f"ERROR: sub-agent timed out after {int(elapsed)}s."
                    return final

                chat_kwargs = dict(
                    model=model,
                    messages=messages,
                    tools=schemas or None,
                    options=options,
                    keep_alive=config.keep_alive,
                )
                if "qwen3" in (model or "").lower():
                    chat_kwargs["think"] = False
                response = ollama.chat(**chat_kwargs)
                message = response.get("message", {}) if isinstance(response, dict) else getattr(response, "message", {})
                content, calls = _message_text(message)

                if not calls:
                    final = content or "ERROR: sub-agent returned no result."
                    status = "done" if not final.startswith("ERROR:") else "error"
                    return final

                messages.append({"role": "assistant", "content": content, "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    name = str(fn.get("name", ""))
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (TypeError, ValueError):
                            args = {}
                    if not isinstance(args, dict):
                        args = {}
                    result = tool_mod.run_tool(name, args, memory, config)
                    messages.append({"role": "tool", "content": result, "tool_name": name})

            final = f"ERROR: sub-agent reached the step limit ({max_rounds}) without finishing."
            return final
    except Exception as err:
        final = f"ERROR: sub-agent failed ({type(err).__name__}: {err})."
        return final
    finally:
        preview = final if len(final) < 400 else final[:400] + "…"
        emit("agent", id=agent_id, task=task[:300], model=model, status=status,
             result=preview, elapsed_s=round(time.monotonic() - started, 2), force=True)


def run_agents(tasks, config: Config, memory, *, model_tier: str | None = None,
               tools=None, max_workers: int | None = None) -> str:
    """Run several independent tasks in parallel; return results labelled in input order."""
    items = [str(t).strip() for t in (tasks or []) if str(t).strip()]
    if not items:
        return "ERROR: no tasks provided to sub-agents."
    if not getattr(config, "agents_enabled", True):
        return "ERROR: sub-agents are disabled (agents_enabled=false)."
    try:
        workers = int(max_workers or getattr(config, "agent_max_workers", 3) or 3)
    except (TypeError, ValueError):
        workers = 3
    workers = max(1, min(workers, len(items), 8))

    results: list[str | None] = [None] * len(items)
    stamp = int(time.time() * 1000)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                run_subagent, task, config, memory,
                model_tier=model_tier, tools=tools,
                agent_id=f"a{stamp}-{index}",
            ): index
            for index, task in enumerate(items)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as err:
                results[index] = f"ERROR: sub-agent failed ({type(err).__name__}: {err})."

    blocks = []
    for index, (task, result) in enumerate(zip(items, results), 1):
        blocks.append(f"Agent {index} — {task}\n{result}")
    return "\n\n".join(blocks)
