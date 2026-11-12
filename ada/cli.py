#!/usr/bin/env python3
"""Ada: a local voice assistant with tools, memory, and a Lovelace personality."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import ollama

from . import tools as tool_mod
from .config import Config
from .events import emit
from .memory import Memory
from .skills import SkillStore

HISTORY_LIMIT = 14

TOOL_HINTS = re.compile(
    r"\b(weather|forecast|temperature|rain|snow|wind|humidity|"
    r"news|headlines?|latest|newest|current|currently|today|tonight|tomorrow|yesterday|now|"
    r"price|prices|cost|stocks?|shares?|market|score|scores?|won|winner|match|game|election|"
    r"release[ds]?|version|update|search|google|look up|find out|online|website|url|link|"
    r"wikipedia|population|exchange rate|how much|how many people|what time|time is it|"
    r"date is it|remember|memorize|memorise|forget|don't forget|keep in mind|commit .*memory|commit .*to memory|save .*to memory|store .*in memory|add .*to memory|note that|"
    r"learn(?:ed|ing)?|skill|skills|save skill|teach you|study|"
    r"upload(?:ed|s)?|document(?:s)?|paper(?:s)?|slide(?:s)?|presentation(?:s)?|pdf|pptx?|docx?|attachment(?:s)?|"
    r"code|coding|program|script|function|class|bug|debug|fix|implement|refactor|"
    r"file|folder|directory|read|write|edit|create|run|execute|command|terminal|shell|"
    r"install|build|test|git|python|javascript|typescript|bash)\b"
    r"|https?://|www\.|[~/][\w./-]+",
    re.IGNORECASE,
)


def needs_tools(text: str) -> bool:
    return bool(TOOL_HINTS.search(text))


LEARN_REQUEST = re.compile(
    r"^\s*(?:hey\s+\w+[,\s]+|hi\s+\w+[,\s]+|okay\s+\w+[,\s]+)?"
    r"(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(?:learn|research|study)\b.*\b(?:about|on)\b\s+(.+)$",
    re.IGNORECASE,
)
LEARN_ANYWHERE = re.compile(
    r"\b(?:learn|research|study)\b.*?\b(?:about|on)\b\s+(.+)$",
    re.IGNORECASE,
)
SAVE_SKILL_REQUEST = re.compile(r"\b(?:save|create|make|add)\b.*\b(?:skill|scale)\b", re.IGNORECASE)

REMEMBER_REQUEST = re.compile(
    r"^\s*(?:hey\s+\w+[,\s]+|hi\s+\w+[,\s]+|okay\s+\w+[,\s]+|ada[,\s]+)?"
    r"(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
    r"(?:remember(?:\s+that)?|memorize|memorise|commit\s+(?:this\s+)?to\s+memory(?:\s+that)?|"
    r"save\s+(?:this\s+)?to\s+memory(?:\s+that)?|store\s+(?:this\s+)?in\s+memory(?:\s+that)?|"
    r"add\s+(?:this\s+)?to\s+memory(?:\s+that)?|keep\s+in\s+mind(?:\s+that)?|note\s+that|don't\s+forget(?:\s+that)?)\s+(.+)$",
    re.IGNORECASE,
)


def extract_remember_fact(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    # avoid confusing "remember how to..." instructions as a fact to store
    if re.match(r"^\s*(?:remember|memorize|memorise)\s+how\b", t, re.IGNORECASE):
        return None
    m = REMEMBER_REQUEST.match(t)
    if not m:
        return None
    fact = m.group(1).strip().strip(".!? ")
    fact = re.sub(r"^(that|this)\s+", "", fact, flags=re.IGNORECASE).strip()
    # require some substance
    if len(fact) < 3:
        return None
    return fact


def extract_learn_topic(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    explicit = bool(re.search(r"\b(everything|all you can|in detail|in-depth|comprehensive|as a skill|save .*skill|create .*skill|new skill|save .*scale|create .*scale)\b", t, re.IGNORECASE))
    wants_skill = bool(SAVE_SKILL_REQUEST.search(t))
    m = LEARN_REQUEST.match(t)
    if not m and (explicit or wants_skill):
        m = LEARN_ANYWHERE.search(t)
    if not m:
        return None
    topic = m.group(1).strip().strip(".!? ")
    if not explicit and len(topic.split()) > 8:
        explicit = True
    if not explicit and wants_skill:
        explicit = True
    if not explicit:
        return None
    topic = re.sub(r"\b(and|then)\s+(save|create|make|add)\b.*$", "", topic, flags=re.IGNORECASE).strip(" ,.-")
    topic = re.sub(r"^(everything|all)\s+(you can\s+)?(about|on)\s+", "", topic, flags=re.IGNORECASE).strip()
    topic = re.sub(r"^(a\s+new\s+(?:skill|scale)\s+(?:and\s+)?|new\s+(?:skill|scale)\s+(?:and\s+)?)", "", topic, flags=re.IGNORECASE).strip()
    return topic or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with Ada.")
    parser.add_argument("--voice", action="store_true", help="push-to-talk microphone input")
    parser.add_argument("--hands-free", action="store_true", help="listen continuously for a wake word")
    parser.add_argument("--any", action="store_true", help="hands-free without a wake word")
    parser.add_argument("--flow", action="store_true", help="hands-free conversational flow (no wake word, interruptible)")
    parser.add_argument("--no-barge-in", action="store_true", help="disable interrupting Ada while speaking")
    parser.add_argument("--no-speak", action="store_true", help="text only, no spoken replies")
    parser.add_argument("--no-tools", action="store_true", help="disable web and memory tools")
    parser.add_argument("--model", help="override the deep model")
    parser.add_argument("--fast-model", help="override the light/fast model")
    parser.add_argument("--light-model", help="override the light model")
    parser.add_argument("--moderate-model", help="override the moderate model")
    parser.add_argument("--deep-model", help="override the deep model")
    parser.add_argument("--warmup", action="store_true", help="preload models and speech recognition, then exit")
    parser.add_argument("--no-web", action="store_true", help="disable the local web dashboard")
    parser.add_argument("--web-port", type=int, help="override the dashboard port")
    parser.add_argument("--web-host", help="override the dashboard host")
    return parser.parse_args()


def load_persona(config: Config) -> str:
    text = Path(config.persona_file).read_text(encoding="utf-8")
    return (
        text.replace("{{user_name}}", config.user_name)
        .replace("{{sensitive_actions_note}}", config.sensitive_note)
    )


def build_system_prompt(config: Config, memory: Memory, tools_enabled: bool) -> str:
    prompt = load_persona(config)
    prompt += f"\n\n## Current Context\nToday is {datetime.now():%A, %B %d, %Y}.\n"
    prompt += (
        "Keep conversational replies short and natural for speech: one to three sentences, "
        "under about sixty words, unless the user explicitly asks for detail. Never use lists, "
        "headings, or markdown in spoken replies.\n"
    )
    if tools_enabled:
        prompt += "\n## Tools\n"
        prompt += "You have these tools:\n"
        for tool in tool_mod.TOOLS:
            fn = tool["function"]
            prompt += f"- {fn['name']}: {fn['description']}\n"
        cwd = Path.cwd().resolve()
        prompt += (
            f"Current working directory: {cwd}\n"
            "Use tools proactively when needed for current information, actions, memory, skills, files, coding, or system tasks. "
            "For weather call get_weather. For exact time call current_time. "
            "You can read, write, edit, list, search, and run commands on the user's system. "
            "When asked to create, make, or build something (a script, app, project, config, folder, etc.), do it on the system: choose a sensible path in the current workspace unless the user specifies one, create directories as needed, write/edit the actual files, and run relevant setup/build/test commands. "
            "Do not only describe or show code when the user expects it created—actually create it. "
            "When asked to create or write a program/script, you MUST call write_file to create the file(s) before running or compiling them. After writing, use run_command to compile/run/test when appropriate and report the actual result. "
            "When asked to improve, fix, or modify yourself (Ada), you may and should modify your own project files when that is what the user wants: use ada_info/workspace_info to locate paths, inspect existing code/config/skills/persona, then edit_file/write_file/run_command as needed, validate changes when possible (e.g. syntax checks/tests), and clearly explain what you changed. Preserve working behavior unless asked otherwise. "
            "Prefer inspecting existing files/directories and following existing project conventions before changing things. "
            "Do not read URLs aloud; name the source briefly. "
            "If the user asks you to remember, memorize, save/commit/store something to memory, or keep something in mind, "
            "you MUST call the remember tool with the exact fact (choose an appropriate category when obvious) and confirm briefly. "
            "If the user asks to forget something, you MUST call forget. "
            "When you learn a lasting fact or preference unprompted, you may call remember.\n"
        )
        prompt += (
            "IMPORTANT: Call tools when the latest message needs them (current info, memory, skills, files, coding, commands, self-improvement, creating things). "
            "Do not use tools for simple greetings, thanks, or small talk. Do not repeat a tool call from an earlier turn "
            "unless the new message asks for it. If a fetch or command fails, try a reasonable alternative instead of repeating the same failing call.\n"
        )
        skills = SkillStore(config.skills_dir)
        prompt += "\n## Skills\n"
        if len(skills):
            prompt += (
                "You have these saved skills. When the user asks you to use a skill, or a task "
                "matches one, call read_skill with the skill's exact name. Do not create a new "
                "skill for that.\n"
            )
            prompt += skills.index() + "\n"
        else:
            prompt += "You have no saved skills yet.\n"
        prompt += (
            "When the user asks you to learn, save, add, or update a skill: (1) if you need info, call web_search and web_fetch to gather reliable facts first, "
            "(2) synthesize what you learned, then (3) call save_skill with detailed, concrete content (key concepts, how it works, steps/procedures, examples, applications, limitations/pitfalls). "
            "Create a NEW skill with an appropriate name for the topic unless the user explicitly asks to update an existing one. "
            "Do NOT call save_skill with vague instructions like 'research basics', 'use web_search', or 'stay updated'. "
            "Before updating an existing skill, read it first. save_skill appends by default; set replace=true only when the user explicitly asks to replace the whole skill. "
            "A skill is a reusable note or procedure, not a change to your underlying model.\n"
        )
    if len(memory):
        prompt += f"\n## What You Remember About {config.user_name}\n{memory.prompt()}\n"
    return prompt


def _tool_call_to_dict(call) -> dict:
    fn = call["function"] if isinstance(call, dict) else call.function
    name = fn["name"] if isinstance(fn, dict) else fn.name
    arguments = fn["arguments"] if isinstance(fn, dict) else fn.arguments
    return {"function": {"name": name, "arguments": arguments or {}}}


def _extract_json_array(text: str):
    if not text:
        return None
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else None
    except Exception:
        pass
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except Exception:
        return None


def auto_remember_from_turn(config: Config, history: list[dict], memory: Memory, assistant_reply: str) -> None:
    """Best-effort: extract durable, useful memories from recent conversation."""
    if not getattr(config, "auto_memory", False):
        return
    if not assistant_reply or len(assistant_reply.strip()) < 2:
        return
    # collect recent conversational turns (skip system/tool internals)
    recent = []
    for msg in history[-8:]:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        # skip very long blobs
        if len(content) > 1200:
            content = content[:1200] + "…"
        recent.append({"role": role, "content": content})
    if not recent:
        return

    existing = memory.all() if hasattr(memory, "all") else []
    existing_lines = []
    for item in existing[-40:]:
        if isinstance(item, dict):
            existing_lines.append(f"- [{item.get('category','other')}] {item.get('text','')}")
    existing_text = "\n".join(existing_lines) if existing_lines else "(none)"

    model = getattr(config, "light_model", None) or getattr(config, "fast_model", None) or config.model
    prompt = (
        "Extract durable memories worth saving from this conversation.\n"
        "Return ONLY a JSON array (no markdown) of objects: "
        '{"text":"...", "category":"preference|person|home|project|routine|other"}.\n'
        "Rules:\n"
        "- Save only stable, useful facts: user preferences, personal details the user shared, routines, home/project context, important decisions or corrections.\n"
        "- Do NOT save: greetings/small talk, transient requests, one-off questions, tool/output noise, secrets/passwords, or anything uncertain.\n"
        "- Do NOT duplicate existing memories.\n"
        f"- Max {int(getattr(config, 'auto_memory_max_items', 3) or 3)} items. If nothing worth saving, return [].\n\n"
        f"Existing memories:\n{existing_text}\n\n"
        f"Recent conversation (JSON):\n{json.dumps(recent, ensure_ascii=False)}\n"
    )
    try:
        chat_kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 300, "num_ctx": min(getattr(config, 'num_ctx', 4096), 4096)},
            keep_alive=getattr(config, "keep_alive", None),
        )
        if "qwen3" in (model or "").lower():
            chat_kwargs["think"] = False
        resp = ollama.chat(**chat_kwargs)
        msg = resp.get("message", {}) if isinstance(resp, dict) else getattr(resp, "message", {})
        content = (msg.get("content") or "") if isinstance(msg, dict) else (getattr(msg, "content", "") or "")
        items = _extract_json_array(content) or []
        allowed = {"preference", "person", "home", "project", "routine", "other"}
        added = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            text = " ".join(str(it.get("text", "")).split()).strip()
            if not text or len(text) < 4 or len(text) > 240:
                continue
            cat = str(it.get("category", "other")).strip().lower() or "other"
            if cat not in allowed:
                cat = "other"
            if memory.add(text, cat):
                added += 1
            if added >= int(getattr(config, "auto_memory_max_items", 3) or 3):
                break
        if added:
            emit("memory", action="auto", added=added, count=len(memory.items) if hasattr(memory, "items") else None)
    except Exception as err:
        emit("error", message=f"auto_memory: {type(err).__name__}: {err}")


def maybe_auto_remember(config: Config, history: list[dict], memory: Memory, assistant_reply: str) -> None:
    if not getattr(config, "auto_memory", False):
        return
    try:
        t = threading.Thread(target=auto_remember_from_turn, args=(config, list(history), memory, assistant_reply), daemon=True)
        t.start()
    except Exception:
        pass


def stream_reply(config: Config, history: list[dict], memory: Memory, model: str,
                 tools_enabled: bool, voice_out) -> str:
    options = {
        "temperature": config.temperature,
        "num_ctx": config.num_ctx,
        "num_predict": config.max_tokens_for(model) if hasattr(config, "max_tokens_for") else (
            config.quick_max_tokens if model == config.fast_model else config.deep_max_tokens
        ),
    }
    tools = tool_mod.TOOLS if tools_enabled else None

    for _round in range(6):
        content_parts: list[str] = []
        calls: list = []
        splitter = None
        if voice_out:
            from .voice import SentenceSplitter

            splitter = SentenceSplitter()

        emit("state", state="thinking", detail=f"{config.model_label(model)} · {model}")
        print("[thinking...]", end="\r", flush=True)
        chat_kwargs = dict(
            model=model,
            messages=history,
            tools=tools,
            stream=True,
            options=options,
            keep_alive=config.keep_alive,
        )
        if "qwen3" in (model or "").lower():
            chat_kwargs["think"] = False
        stream = ollama.chat(**chat_kwargs)
        printing = False
        for chunk in stream:
            message = chunk["message"]
            piece = message.get("content") or ""
            if piece:
                if not printing:
                    print(" " * 16, end="\r")
                    print("Ada: ", end="", flush=True)
                    printing = True
                content_parts.append(piece)
                emit("token", text=piece)
                print(piece, end="", flush=True)
                if splitter:
                    for sentence in splitter.add(piece):
                        voice_out.feed(sentence)
            if message.get("tool_calls"):
                calls.extend(message["tool_calls"])

        if printing:
            print()
        content = "".join(content_parts).strip()
        if not content and not calls:
            # fallback: some reasoning models may return text in thinking
            try:
                thinking = message.get("thinking") or ""
            except Exception:
                thinking = ""
            if isinstance(thinking, str) and thinking.strip():
                content = thinking.strip()

        if splitter:
            for sentence in splitter.flush():
                voice_out.feed(sentence)

        if not calls:
            if content:
                maybe_auto_remember(config, history, memory, content)
            return content

        normalized = [_tool_call_to_dict(call) for call in calls]
        history.append({"role": "assistant", "content": content, "tool_calls": normalized})

        for call in normalized:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            emit("tool", name=name, args=args, status="start")
            print(f"[tool] {name} {args}", flush=True)
            try:
                result = tool_mod.run_tool(name, args, memory, config)
            except Exception as err:
                emit("tool", name=name, args=args, status="error", result=str(err))
                raise
            preview = result if len(result) < 300 else result[:300] + "…"
            emit("tool", name=name, args=args, status="done", result=preview)
            print(f"[tool] -> {preview}", flush=True)
            history.append({"role": "tool", "content": result, "tool_name": name})

    return "I am sorry, I could not finish that request."


def trim_history(history: list[dict]) -> None:
    if len(history) > HISTORY_LIMIT + 1:
        del history[1 : len(history) - HISTORY_LIMIT]
    while len(history) > 1 and history[1].get("role") != "user":
        del history[1]


def warm_model(config: Config, memory: Memory, tools_enabled: bool = True) -> bool:
    """Load the model and prime its prompt cache with the real system prompt."""
    warm = getattr(config, "light_model", None) or config.fast_model
    emit("state", state="warming", detail=warm)
    try:
        warm_kwargs = dict(
            model=warm,
            messages=[
                {"role": "system", "content": build_system_prompt(config, memory, tools_enabled)},
                {"role": "user", "content": "Hello"},
            ],
            tools=tool_mod.TOOLS if tools_enabled else None,
            options={"num_predict": 1, "num_ctx": config.num_ctx},
            keep_alive=config.keep_alive,
        )
        if "qwen3" in (warm or "").lower():
            warm_kwargs["think"] = False
        ollama.chat(**warm_kwargs)
        emit("state", state="idle", detail="model ready")
        return True
    except Exception as err:
        emit("state", state="idle", detail="model unavailable")
        emit("error", message=f"model unavailable: {type(err).__name__}: {err}")
        return False


def make_voice(config: Config):
    if not config.speak:
        return None, None
    try:
        from .voice import Speaker, VoiceOutput

        speaker = Speaker(
            config.voice,
            config.output_device,
            length_scale=getattr(config, "voice_length_scale", None),
            noise_scale=getattr(config, "voice_noise_scale", None),
            noise_w=getattr(config, "voice_noise_w", None),
            sentence_silence=getattr(config, "voice_sentence_silence", 0.15),
        )
        return speaker, VoiceOutput(speaker)
    except Exception as err:
        print(f"[voice] OFF - {type(err).__name__}: {err}")
        return None, None


def make_listener(config: Config, load: bool = False):
    if not config.stt_enabled:
        return None
    try:
        from .stt import Listener

        listener = Listener(
            config.whisper_model,
            config.input_device,
            beam_size=getattr(config, "stt_beam_size", 5),
            vad_filter=getattr(config, "stt_vad_filter", True),
        )
        if load:
            print(f"[stt] loading {config.whisper_model}…", flush=True)
            listener.load()
            print("[stt] ready")
        return listener
    except Exception as err:
        print(f"[stt] OFF - {type(err).__name__}: {err}")
        return None


def listen_text(listener, config: Config) -> str | None:
    if listener is None:
        print("[stt] speech input is unavailable.")
        return None
    emit("state", state="listening", detail="microphone")
    print("[mic] speak now; I stop when you pause…", flush=True)
    try:
        audio = listener.record_phrase(
            max_seconds=getattr(config, "stt_max_seconds", 20.0),
            silence_seconds=getattr(config, "stt_silence_seconds", 1.2),
            status=lambda state: print(
                f"[mic] {state}…".ljust(24), end="\r", flush=True
            )
        )
    except Exception as err:
        emit("error", message=f"microphone failed: {type(err).__name__}: {err}")
        emit("state", state="idle", detail="microphone failed")
        print(f"\n[mic error] {type(err).__name__}: {err}")
        return None
    if audio is None:
        emit("state", state="idle", detail="no speech detected")
        print("[mic] I did not hear anything." + " " * 20)
        return None
    emit("state", state="transcribing", detail="speech to text")
    print("[stt] transcribing…".ljust(24), end="\r", flush=True)
    try:
        text = listener.transcribe(audio)
    except Exception as err:
        emit("error", message=f"speech to text failed: {type(err).__name__}: {err}")
        emit("state", state="idle", detail="speech to text failed")
        print(f"\n[stt error] {type(err).__name__}: {err}")
        return None
    print(" " * 24, end="\r")
    text = text.strip()
    if not text:
        emit("state", state="idle", detail="no speech detected")
    return text or None


def say(speaker, voice_out, text: str) -> None:
    if speaker is None:
        print("[voice] is off.")
        return
    if voice_out:
        voice_out.wait()
    emit("state", state="speaking", detail="voice test")
    emit("voice", action="start", text=text)
    try:
        speaker.speak(text)
    except Exception as err:
        emit("error", message=f"audio failed: {type(err).__name__}: {err}")
        print(f"[audio error] {type(err).__name__}: {err}")
    finally:
        emit("voice", action="end", text=text)
        emit("state", state="idle", detail="awaiting input")


def respond(user_text: str, config: Config, history: list[dict], memory: Memory,
            voice_out, tools_enabled: bool, forced_model: str | None = None,
            listener=None, allow_barge_in: bool = False) -> bool | str:
    model = forced_model or config.choose_model(user_text)
    use_tools = tools_enabled and (not config.auto_tools or needs_tools(user_text))
    history.append({"role": "user", "content": user_text})
    history[0]["content"] = build_system_prompt(config, memory, use_tools)
    emit("user", text=user_text)
    emit("route", model=model, label=config.model_label(model), tools=use_tools)

    label = config.model_label(model)
    if label == "deep":
        label = "deep, slower"
    elif label == "moderate":
        label = "moderate"
    else:
        label = "light"
    print(f"[{label}] {model}{'' if use_tools else ' (no tools)'}", flush=True)
    tried_fallback = False
    try:
        reply = stream_reply(config, history, memory, model, use_tools, voice_out)
    except Exception as err:
        # fallback chain: deep -> moderate -> light
        chain = [getattr(config, "deep_model", config.model), getattr(config, "moderate_model", config.fast_model), getattr(config, "light_model", config.fast_model)]
        fallback = None
        if model in chain:
            idx = chain.index(model)
            if idx + 1 < len(chain):
                fallback = chain[idx + 1]
        if fallback is None:
            fallback = getattr(config, "light_model", config.fast_model)
        if model != fallback and not tried_fallback:
            tried_fallback = True
            emit("error", message=f"{model} unavailable, falling back to {fallback}: {type(err).__name__}: {err}")
            print(f"\n[model] {model} unavailable, falling back to {fallback}", flush=True)
            model = fallback
            use_tools = tools_enabled and (not config.auto_tools or needs_tools(user_text))
            history[0]["content"] = build_system_prompt(config, memory, use_tools)
            try:
                reply = stream_reply(config, history, memory, model, use_tools, voice_out)
            except Exception as err2:
                err = err2
            else:
                err = None
        if err is not None:
            emit("error", message=f"{type(err).__name__}: {err}")
            emit("state", state="idle", detail="model failed")
            print(f"\n[ollama error] {type(err).__name__}: {err}")
            print("Is Ollama running, and is the model downloaded? Try: ./start.sh --check\n")
            while len(history) > 1 and history[-1].get("role") != "user":
                history.pop()
            if len(history) > 1:
                history.pop()
            return False

    if reply:
        history.append({"role": "assistant", "content": reply})
        emit("assistant", text=reply)
        if voice_out:
            emit("state", state="speaking", detail=config.voice)
            interrupted_text = None
            if allow_barge_in and listener is not None and config.barge_in:
                interrupted_text = None
                try:
                    audio = listener.listen_for_barge_in(
                        lambda: not (voice_out.speaking or not voice_out._queue.empty()),
                        max_wait=120.0,
                        silence_seconds=0.7,
                    )
                except Exception as err:
                    emit("error", message=f"barge-in listen failed: {type(err).__name__}: {err}")
                    audio = None
                if audio is not None:
                    voice_out.interrupt()
                    try:
                        interrupted_text = listener.transcribe(audio).strip()
                    except Exception:
                        interrupted_text = None
                if interrupted_text:
                    emit("state", state="idle", detail="interrupted")
                    trim_history(history)
                    return interrupted_text
                voice_out.wait()
            else:
                voice_out.wait()
    emit("state", state="idle", detail="awaiting input")
    trim_history(history)
    return True


def _extract_urls(search_text: str) -> list[str]:
    urls = []
    for line in search_text.splitlines():
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            urls.append(line)
    return urls


def learn_skill(topic: str, config: Config, voice_out=None) -> str:
    """Programmatically research and save a detailed skill."""
    topic = topic.strip()
    if not topic:
        return "ERROR: no topic provided."
    depth = (getattr(config, "learn_depth", "deep") or "deep").strip().lower()
    quick = depth == "quick"
    emit("state", state="thinking", detail=f"learning ({depth}): {topic}")
    print(f"[learn] researching ({depth}): {topic}", flush=True)

    if quick:
        queries = [topic, f"{topic} key concepts how it works examples"]
        fetch_count = 2
        material_limit = 10000
        predict = 1100
    else:
        queries = [
            topic,
            f"{topic} explained key concepts how it works",
            f"{topic} practical guide examples commands",
            f"{topic} pitfalls limitations best practices",
        ]
        fetch_count = 5
        material_limit = 22000
        predict = 2200

    search_blocks = []
    seen = set()
    urls = []
    for q in queries:
        emit("tool", name="web_search", args={"query": q}, status="start")
        res = tool_mod.web_search(q, max_results=max(config.search_results, 5 if not quick else 3))
        emit("tool", name="web_search", args={"query": q}, status="done", result=(res[:300] + "…") if len(res) > 300 else res)
        search_blocks.append(f"## Search: {q}\n{res}")
        for url in _extract_urls(res):
            if url not in seen:
                seen.add(url)
                urls.append(url)

    source_urls = []
    source_pages = []
    for url in urls[:fetch_count]:
        emit("tool", name="web_fetch", args={"url": url}, status="start")
        page = tool_mod.web_fetch(url, max_chars=6000 if not quick else 4500)
        emit("tool", name="web_fetch", args={"url": url}, status="done", result=(page[:300] + "…") if len(page) > 300 else page)
        if not page.startswith("ERROR:"):
            source_pages.append(page)
            source_urls.append(url)

    material = "\n\n".join(search_blocks + source_pages)
    if len(material) > material_limit:
        material = material[:material_limit] + "\n[truncated]"
    if len(material) > 18000:
        material = material[:18000] + "\n[truncated]"
    if len(material.strip()) < 200:
        emit("state", state="idle", detail="learning failed")
        return "ERROR: could not gather enough source material to learn this topic."

    prompt = (
        f"Create a detailed, reusable skill about: {topic}\n\n"
        "Use ONLY the source material below. Write the actual knowledge (not instructions to research).\n"
        "Return EXACTLY this format:\n"
        "NAME: <short specific skill name>\n"
        "DESCRIPTION: <one-line description>\n"
        "INSTRUCTIONS:\n"
        "<detailed markdown instructions>\n\n"
        "The INSTRUCTIONS must be substantial and practical: key concepts/definitions, how it works, "
        "important components/protocols/commands/APIs or steps as relevant, concrete examples, common use cases, "
        "limitations/pitfalls, and best practices. Use headings and bullet points where helpful.\n\n"
        f"SOURCE MATERIAL:\n{material}"
    )
    if quick:
        model = getattr(config, "moderate_model", config.fast_model)
    else:
        model = getattr(config, "deep_model", config.model)
    try:
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_ctx": max(config.num_ctx, 8192), "num_predict": predict},
            keep_alive=config.keep_alive,
        )
    except Exception as err:
        fallbacks = [getattr(config, "moderate_model", None), getattr(config, "light_model", None), config.fast_model]
        resp = None
        for fb in fallbacks:
            if not fb or fb == model:
                continue
            try:
                resp = ollama.chat(
                    model=fb,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2, "num_ctx": config.num_ctx, "num_predict": min(predict, 1400)},
                    keep_alive=config.keep_alive,
                )
                model = fb
                break
            except Exception:
                continue
        if resp is None:
            emit("state", state="idle", detail="learning failed")
            return f"ERROR: learning failed ({type(err).__name__}: {err})."

    text = (resp.get("message", {}) or {}).get("content", "").strip()
    name = topic.title()
    description = f"Knowledge and practical guidance about {topic}."
    instructions = text
    m_name = re.search(r"^NAME:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    m_desc = re.search(r"^DESCRIPTION:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    m_inst = re.search(r"^INSTRUCTIONS:\s*\n([\s\S]+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    if m_name:
        name = m_name.group(1).strip().strip('"')
    if m_desc:
        description = m_desc.group(1).strip().strip('"')
    if m_inst:
        instructions = m_inst.group(1).strip()

    # ensure substantial content; if model didn't follow format well, keep full text but clean
    if len(instructions) < 300 and len(text) >= 300:
        instructions = re.sub(r"^(NAME|DESCRIPTION):.*$", "", text, flags=re.MULTILINE | re.IGNORECASE).strip()
        instructions = re.sub(r"^INSTRUCTIONS:\s*", "", instructions, flags=re.MULTILINE | re.IGNORECASE).strip()

    sources = source_urls
    try:
        result = SkillStore(config.skills_dir).save(name, description, instructions, replace=True, sources=sources)
        emit("skill_saved", name=name, description=description, sources=sources)
        emit("state", state="idle", detail="skill saved")
        return f"{result} ({name}) based on {len(sources)} source(s)."
    except Exception as err:
        # last resort: save with best-effort cleaned content if validator complains
        if "too vague" in str(err).lower() and len(instructions) >= 180:
            try:
                padded = instructions + "\n\n## Notes\n- Review and expand with more sources as needed for depth and accuracy."
                result = SkillStore(config.skills_dir).save(name, description, padded, replace=True, sources=sources)
                emit("skill_saved", name=name, description=description, sources=sources)
                emit("state", state="idle", detail="skill saved")
                return f"{result} ({name}) based on {len(sources)} source(s)."
            except Exception:
                pass
        emit("state", state="idle", detail="learning failed")
        return f"ERROR: could not save skill ({type(err).__name__}: {err})."


def print_help(config: Config, tools_enabled: bool) -> None:
    light = getattr(config, "light_model", config.fast_model)
    mod = getattr(config, "moderate_model", config.fast_model)
    deep = getattr(config, "deep_model", config.model)
    print(
        f"""Commands:
  /listen            speak instead of typing
  /remember <fact>   save something to memory
  /memories          list memories
  /forget <words>    remove matching memories
  /skills            list saved skills
  /skill <name>      show a saved skill
  /learn <topic>     research and save a new skill
  /say <text>        test the voice
  /light <text>      force light model ({light})
  /moderate <text>   force moderate model ({mod})
  /deep <text>       force deep model ({deep})
  /fast <text>       alias for /light
  /model             show routing status
  /help              this list
  /quit              exit
Tools are {'ON' if tools_enabled else 'OFF'}: web search, page reader, weather, memory, files, commands.
"""
    )


def chat_loop(config: Config, history: list[dict], memory: Memory, speaker,
              voice_out, listener, tools_enabled: bool) -> None:
    print_help(config, tools_enabled)
    prompt = (
        f"{config.user_name} (Enter to speak): "
        if config.voice_input
        else f"{config.user_name}: "
    )

    while True:
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            if config.voice_input:
                heard = listen_text(listener, config)
                if not heard:
                    continue
                print(f"{config.user_name}: {heard}")
                line = heard
            else:
                continue

        if line in {"/quit", "/exit"}:
            break
        if line in {"/help", "/?"}:
            print_help(config, tools_enabled)
            continue
        if line == "/memories":
            print(memory.prompt() or "(no memories yet)")
            continue
        if line == "/skills":
            skills = SkillStore(config.skills_dir)
            print(skills.index() or "(no skills yet; ask me to learn one)")
            continue
        if line == "/skill" or line.startswith("/skill "):
            name = line[len("/skill"):].strip()
            if not name:
                print("Usage: /skill <name>")
                continue
            found = SkillStore(config.skills_dir).get(name)
            if not found:
                print("No skill by that name. Try /skills.")
            else:
                title, body = found
                print(body if body.lstrip().startswith("#") else f"# {title}\n\n{body}")
            continue
        if line == "/learn" or line.startswith("/learn "):
            topic = line[len("/learn"):].strip()
            if not topic:
                print("Usage: /learn <topic>")
                continue
            emit("user", text=line)
            result = learn_skill(topic, config, voice_out)
            print(f"Ada: {result}")
            emit("assistant", text=result)
            continue
        if line == "/model":
            light = getattr(config, "light_model", config.fast_model)
            mod = getattr(config, "moderate_model", config.fast_model)
            deep = getattr(config, "deep_model", config.model)
            if config.auto_route:
                print(f"light: {light}  moderate: {mod}  deep: {deep}  (auto)")
            else:
                print(f"light: {light}  moderate: {mod}  deep: {deep}  (manual hints/commands)")
            continue
        if line == "/remember" or line.startswith("/remember "):
            fact = re.sub(r"^(that|about)\s+", "", line[len("/remember"):].strip(), flags=re.I)
            if not fact:
                print("Usage: /remember <fact>")
                continue
            cat = memory.suggest_category(fact) if hasattr(memory, "suggest_category") else "other"
            print(f"Noted [{cat}]." if memory.add(fact, cat) else "I already remember that.")
            continue
        if line == "/forget" or line.startswith("/forget "):
            query = re.sub(r"^(that|about)\s+", "", line[len("/forget"):].strip(), flags=re.I)
            if not query:
                print("Usage: /forget <words>")
                continue
            removed = memory.forget(query)
            print("Forgot: " + "; ".join(removed) if removed else "No matching memory.")
            continue
        if line == "/say" or line.startswith("/say "):
            say(speaker, voice_out, line[len("/say"):].strip() or "Good evening. I am Ada.")
            continue
        if line == "/listen":
            heard = listen_text(listener, config)
            if not heard:
                continue
            print(f"{config.user_name}: {heard}")
            line = heard
        if line == "/deep" or line.startswith("/deep "):
            text = line[len("/deep"):].strip()
            if not text:
                print("Usage: /deep <text>")
                continue
            respond(text, config, history, memory, voice_out, tools_enabled, getattr(config, "deep_model", config.model))
            continue
        if line in {"/moderate", "/mid"} or line.startswith("/moderate ") or line.startswith("/mid "):
            prefix = "/moderate" if line.startswith("/moderate") else "/mid"
            text = line[len(prefix):].strip()
            if not text:
                print("Usage: /moderate <text>")
                continue
            respond(text, config, history, memory, voice_out, tools_enabled, getattr(config, "moderate_model", config.fast_model))
            continue
        if line == "/light" or line.startswith("/light "):
            text = line[len("/light"):].strip()
            if not text:
                print("Usage: /light <text>")
                continue
            respond(text, config, history, memory, voice_out, tools_enabled, getattr(config, "light_model", config.fast_model))
            continue
        if line == "/fast" or line.startswith("/fast "):
            text = line[len("/fast"):].strip()
            if not text:
                print("Usage: /fast <text>")
                continue
            respond(text, config, history, memory, voice_out, tools_enabled, getattr(config, "light_model", config.fast_model))
            continue

        remember_fact = extract_remember_fact(line)
        if remember_fact:
            emit("user", text=line)
            cat = memory.suggest_category(remember_fact) if hasattr(memory, "suggest_category") else "other"
            saved = memory.add(remember_fact, cat)
            result_msg = f"Saved to memory [{cat}]: {remember_fact}" if saved else f"I already have that in memory: {remember_fact}"
            print(f"Ada: {result_msg}")
            emit("assistant", text=result_msg)
            if voice_out and config.speak:
                say(speaker, voice_out, "Saved to memory." if saved else "I already remember that.")
            continue

        learn_topic = extract_learn_topic(line)
        if learn_topic and ("skill" in line.lower() or re.search(r"\b(everything|all you can|in detail|in-depth|comprehensive)\b", line, re.IGNORECASE)):
            emit("user", text=line)
            result_msg = learn_skill(learn_topic, config, voice_out)
            print(f"Ada: {result_msg}")
            emit("assistant", text=result_msg)
            if voice_out and config.speak:
                say(speaker, voice_out, result_msg if len(result_msg) < 400 else "I researched the topic and saved a detailed skill.")
            continue
        respond(line, config, history, memory, voice_out, tools_enabled)


def hands_free_loop(config: Config, history: list[dict], memory: Memory, speaker,
                    voice_out, listener, tools_enabled: bool) -> None:
    if listener is None:
        print("[stt] hands-free mode needs speech recognition, which is unavailable.")
        return

    wake_words = [word for word in config.wake_words if word.strip()] or ["ada"]
    def make_wake_pattern(words):
        return re.compile(
            r"\b(?:"
            + "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
            + r")\b",
            re.IGNORECASE,
        )
    wake_pattern = make_wake_pattern(wake_words)
    if config.flow_mode:
        print("Flow mode: speak naturally without a wake word. I can be interrupted while speaking. Ctrl+C to stop.")
    elif config.require_wake_word:
        names = ", ".join(f'"{word.title()}"' for word in wake_words)
        print(f"Hands-free: say {names} followed by your request. Ctrl+C to stop.")
    else:
        print("Hands-free: just speak. Ctrl+C to stop.")

    while True:
        try:
            # in flow mode, allow shorter pauses after assistant replies feel natural
            silence = 0.9 if config.flow_mode else getattr(config, "stt_silence_seconds", 1.2)
            audio = listener.record_phrase(
                silence_seconds=silence,
                status=lambda state: print(
                    f"[mic] {state}…".ljust(28), end="\r", flush=True
                )
            )
            if audio is None:
                continue
            print("[stt] transcribing…".ljust(28), end="\r", flush=True)
            text = listener.transcribe(audio)
            print(" " * 28, end="\r")
            if not text:
                continue

            if config.require_wake_word:
                wake_words = [word for word in config.wake_words if word.strip()] or ["ada"]
                wake_pattern = make_wake_pattern(wake_words)
                match = wake_pattern.search(text)
                if not match:
                    continue
                text = text[match.end():].lstrip(" ,.!?-")

            if not text:
                say(speaker, voice_out, "Yes?")
                continue

            cmd = text.strip().lower().rstrip(".!?")
            # tolerate wake word prefix in commands (e.g. "hey ada, enter flow mode")
            for _w in sorted([w for w in config.wake_words if w.strip()] or ["ada"], key=len, reverse=True):
                _wlow = _w.lower()
                if cmd == _wlow:
                    cmd = ""
                    break
                if cmd.startswith(_wlow + " "):
                    cmd = cmd[len(_wlow):].lstrip(" ,.!?-")
                    break
                if cmd.startswith(_wlow + ","):
                    cmd = cmd[len(_wlow)+1:].lstrip(" ,.!?-")
                    break
            enter_flow = cmd in {"enter flow mode", "start flow mode", "enable flow mode", "go into flow mode", "flow mode on"}
            exit_flow = cmd in {"exit flow mode", "stop flow mode", "disable flow mode", "leave flow mode", "flow mode off", "end flow mode"}
            if enter_flow:
                config.flow_mode = True
                config.require_wake_word = False
                config.barge_in = bool(speaker) and config.speak
                emit("state", state="idle", detail="flow mode on")
                print("[flow] enabled (no wake word, barge-in on)" if config.barge_in else "[flow] enabled (no wake word)")
                if speaker and voice_out:
                    say(speaker, voice_out, "Flow mode on. You can speak freely.")
                continue
            if exit_flow:
                config.flow_mode = False
                config.require_wake_word = True
                emit("state", state="idle", detail="flow mode off")
                print("[flow] disabled (wake word required)")
                if speaker and voice_out:
                    say(speaker, voice_out, "Flow mode off. Wake word required.")
                continue

            print(f"{config.user_name}: {text}")
            remember_fact = extract_remember_fact(text)
            if remember_fact:
                emit("user", text=text)
                cat = memory.suggest_category(remember_fact) if hasattr(memory, "suggest_category") else "other"
                saved = memory.add(remember_fact, cat)
                result_msg = f"Saved to memory [{cat}]: {remember_fact}" if saved else f"I already have that in memory: {remember_fact}"
                print(f"Ada: {result_msg}")
                emit("assistant", text=result_msg)
                if voice_out and config.speak:
                    say(speaker, voice_out, "Saved to memory." if saved else "I already remember that.")
                result = True
            else:
                learn_topic = extract_learn_topic(text)
                if learn_topic:
                    emit("user", text=text)
                    result_msg = learn_skill(learn_topic, config, voice_out)
                    print(f"Ada: {result_msg}")
                    emit("assistant", text=result_msg)
                    if voice_out and config.speak:
                        say(speaker, voice_out, result_msg if len(result_msg) < 400 else "I researched the topic and saved a detailed skill.")
                    result = True
                else:
                    allow_barge = bool(config.barge_in and speaker and voice_out and listener)
                    result = respond(
                        text, config, history, memory, voice_out, tools_enabled,
                        listener=listener, allow_barge_in=allow_barge,
                    )
            # if interrupted, immediately handle captured speech
            while isinstance(result, str) and result.strip():
                print(f"{config.user_name}: {result}")
                result = respond(
                    result, config, history, memory, voice_out, tools_enabled,
                    listener=listener, allow_barge_in=allow_barge,
                )
            time.sleep(0.15 if config.flow_mode else 0.2)
        except KeyboardInterrupt:
            print()
            break
        except Exception as err:
            print(f"\n[mic error] {type(err).__name__}: {err}")
            time.sleep(1)


def main() -> None:
    args = parse_args()
    config = Config.load()
    if args.model:
        config.model = args.model
        config.deep_model = args.model
    if args.fast_model:
        config.fast_model = args.fast_model
        config.light_model = args.fast_model
    if getattr(args, "light_model", None):
        config.light_model = args.light_model
        config.fast_model = args.light_model
    if getattr(args, "moderate_model", None):
        config.moderate_model = args.moderate_model
    if getattr(args, "deep_model", None):
        config.deep_model = args.deep_model
        config.model = args.deep_model
    if args.no_speak:
        config.speak = False
    if args.no_web:
        config.web_enabled = False
    if args.web_port is not None:
        config.web_port = args.web_port
    if args.web_host:
        config.web_host = args.web_host
    if args.voice:
        config.voice_input = True
    if args.hands_free:
        config.hands_free = True
        config.voice_input = True
        if args.any:
            config.require_wake_word = False
    if args.flow:
        config.flow_mode = True
        config.hands_free = True
        config.voice_input = True
        config.require_wake_word = False
    if args.no_barge_in:
        config.barge_in = False

    memory = Memory(config.memory_file)
    try:
        tool_mod.ensure_reminders(config)
    except Exception:
        pass
    history: list[dict] = [{"role": "system", "content": ""}]
    tools_enabled = not args.no_tools

    if args.warmup:
        warm = getattr(config, "light_model", config.fast_model)
        print(f"[warm] loading {warm}…")
        if warm_model(config, memory, tools_enabled):
            print("[warm] model ready")
        else:
            print("[warm] model unavailable; run ./start.sh --check")
        listener = make_listener(config, load=True)
        if listener:
            print("[warm] speech recognition ready")
        return

    dashboard = None
    if config.web_enabled:
        try:
            from .web import start_dashboard

            dashboard = start_dashboard(config)
            print(f"[web] dashboard {dashboard.url}")
        except OSError as err:
            print(f"[web] OFF - {type(err).__name__}: {err}")

    if dashboard:
        try:
            skills_info = SkillStore(config.skills_dir).list_info()
        except Exception:
            skills_info = []
        try:
            mem_items = memory.all() if hasattr(memory, "all") else list(memory)
        except Exception:
            mem_items = []
        light = getattr(config, "light_model", config.fast_model)
        mod = getattr(config, "moderate_model", config.fast_model)
        deep = getattr(config, "deep_model", config.model)
        emit(
            "session",
            user=config.user_name,
            light=light,
            moderate=mod,
            deep=deep,
            quick=light,
            voice=config.voice if config.speak else None,
            input=(
                "flow"
                if config.flow_mode
                else "hands-free"
                if config.hands_free
                else "voice"
                if config.voice_input
                else "text"
            ),
            tools=tools_enabled,
            memories=len(mem_items),
            skills=len(skills_info),
            skills_list=skills_info,
            memory_items=mem_items,
            workspace=getattr(config, "workspace", None),
        )

    speaker, voice_out = make_voice(config)
    listener = None
    if config.hands_free or config.voice_input:
        listener = make_listener(config, load=True)

    light = getattr(config, "light_model", config.fast_model)
    mod = getattr(config, "moderate_model", config.fast_model)
    deep = getattr(config, "deep_model", config.model)
    print(f"[models] light={light}  moderate={mod}  deep={deep}  "
          f"routing={'auto' if config.auto_route else 'off'}")
    print(f"[voice] {'ON — ' + speaker.name if speaker else 'OFF (text only)'}")
    input_mode = "flow" if config.flow_mode else ("hands-free" if config.hands_free else ("push-to-talk" if config.voice_input else "text"))
    print(f"[input] {input_mode}{' (barge-in)' if config.flow_mode and config.barge_in and speaker else ''}")
    print(f"[tools] {'ON' if tools_enabled else 'OFF'}")
    print(f"[memory] {len(memory)} item(s)\n")

    threading.Thread(
        target=warm_model, args=(config, memory, tools_enabled), daemon=True
    ).start()

    if config.hands_free:
        hands_free_loop(config, history, memory, speaker, voice_out, listener, tools_enabled)
    else:
        chat_loop(config, history, memory, speaker, voice_out, listener, tools_enabled)

    if voice_out:
        voice_out.wait()

