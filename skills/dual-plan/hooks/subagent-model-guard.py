#!/usr/bin/env python3
"""PreToolUse hook for the Agent tool: only allow subagents pinned to a non-Opus model,
and cap how many sonnet-worker subagents one session may spawn.

A subagent type is allowed when ~/.claude/agents/<type>.md exists and its frontmatter
sets `model:` to something other than Opus or `inherit`. Built-ins (Explore, Plan,
general-purpose) and plugin agents have no such file, so they are blocked: they would
otherwise inherit the main session's model.

sonnet-worker is limited to SONNET_MAX_PER_SESSION spawns per session (counted in
~/.claude/hooks/state/). haiku-worker is only for work Codex can't do: its brief must
mention the browser, screenshots/visual checks, computer use, the simulator, an MCP
connector or artifact, or say Codex failed. Everything else goes to Codex.
Fails closed: any error blocks the call.
"""
import fcntl
import json
import os
import re
import sys
import time

AGENTS_DIR = os.path.expanduser("~/.claude/agents")
STATE_DIR = os.path.expanduser("~/.claude/hooks/state")
CAPPED_TYPE = "sonnet-worker"
SONNET_MAX_PER_SESSION = 3
HAIKU_TYPE = "haiku-worker"
CLAUDE_ONLY = re.compile(
    r"browser|screenshot|visual|chrome|computer[ -]use|simulator|\bmcp\b|connector|artifact|"
    r"codex (failed|fail|errored|is down|unavailable)", re.I)
CODEX_HINT = ("Delegate it to Codex instead (dual-plan skill, scripts/codex_worker.py): --model strong for UI "
              "implementation, hard debugging and diff review, --model fast for everything else. haiku-worker is only for browser/visual checks, "
              "computer use, the simulator, MCP connectors, artifacts, or when Codex failed (say so in the brief).")
HINT = ("Use Codex (dual-plan skill) for research and implementation, or subagent_type haiku-worker for "
        "browser/visual/MCP work.")


def block(reason, hint=HINT):
    print(f"Blocked by subagent-model-guard: {reason} {hint}", file=sys.stderr)
    sys.exit(2)


def pinned_model(agent_type):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", agent_type):
        return None
    path = os.path.join(AGENTS_DIR, agent_type + ".md")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip().strip("'\"").lower()
    return None


def take_sonnet_slot(session_id):
    """Atomically increment this session's sonnet-worker count; return the new count."""
    os.makedirs(STATE_DIR, exist_ok=True)
    cutoff = time.time() - 7 * 86400
    for name in os.listdir(STATE_DIR):
        p = os.path.join(STATE_DIR, name)
        if os.path.getmtime(p) < cutoff:
            os.remove(p)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    with open(os.path.join(STATE_DIR, f"sonnet-{safe}.count"), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        n = int(f.read().strip() or 0)
        if n >= SONNET_MAX_PER_SESSION:
            return n + 1
        f.seek(0)
        f.truncate()
        f.write(str(n + 1))
        return n + 1


def main():
    try:
        data = json.load(sys.stdin)
        agent_type = (data.get("tool_input") or {}).get("subagent_type") or "general-purpose"
        model = pinned_model(agent_type)
    except Exception as e:  # fail closed
        block(f"hook error ({e}).")
    if not model:
        block(f"'{agent_type}' has no pinned model in ~/.claude/agents, so it would run on the main session's model.")
    if "opus" in model or "fable" in model or model == "inherit":
        block(f"'{agent_type}' is pinned to {model}.")
    if agent_type == HAIKU_TYPE:
        inp = data.get("tool_input") or {}
        if not CLAUDE_ONLY.search(f"{inp.get('description') or ''} {inp.get('prompt') or ''}"):
            block("this brief doesn't need Claude-only tools (browser, visual check, MCP).", CODEX_HINT)
    if agent_type == CAPPED_TYPE:
        try:
            n = take_sonnet_slot(data.get("session_id") or "unknown")
        except Exception as e:  # fail closed
            block(f"could not track the sonnet-worker budget ({e}).")
        if n > SONNET_MAX_PER_SESSION:
            block(
                f"this session already used its {SONNET_MAX_PER_SESSION} sonnet-worker spawns.",
                "Use haiku-worker instead (split the task smaller if needed), or do the judgment step yourself.",
            )
    sys.exit(0)


main()
