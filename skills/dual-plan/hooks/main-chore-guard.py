#!/usr/bin/env python3
"""Main-session chore guard: push file dumps, builds and browser checks out of Opus.

PreToolUse (Bash|Read|mcp__Claude_Browser__.*), main session only. Calls from a
subagent carry `agent_id` and always pass.
  - Bash that dumps a file (cat/less/more over MAX_DUMP_LINES, head/tail/sed -n
    asking for more than that) is blocked. `cmd | tail -40` is fine.
  - Read of a file over MAX_READ_LINES without offset/limit is blocked.
  - Builds/tests/runs and browser-pane calls are chores: the first CHORE_BUDGET per
    user message run inline, later ones are blocked with a delegation hint.
UserPromptSubmit resets the chore count (state in ~/.claude/hooks/state/).

Set CHORE_GUARD_OFF=1 to disable. Fails open: any error allows the call.
"""
import json
import os
import re
import shlex
import sys

STATE_DIR = os.path.expanduser("~/.claude/hooks/state")
CHORE_BUDGET = 2
MAX_READ_LINES = 400
MAX_DUMP_LINES = 100

CHORE_CMD = re.compile(
    r"\b(npm|pnpm|yarn|bun)\s+(run|test|build|dev|start|exec)\b|\bnpx\b|\b(tsc|vite|next|webpack|jest|vitest|pytest|"
    r"mocha|xcodebuild|xcrun|cargo|swift|gradle|make|tauri|playwright|go\s+(test|build|run))\b")
CODEX = re.compile(r"\bcodex\b")
DUMPERS = {"cat", "less", "more", "head", "tail", "sed"}


def block(reason):
    print(f"Blocked by main-chore-guard: {reason}", file=sys.stderr)
    sys.exit(2)


def count_lines(path, cap):
    n = 0
    with open(path, "rb") as f:
        while n <= cap:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            n += chunk.count(b"\n")
    return n


def requested_lines(argv):
    """Lines a head/tail/sed -n call asks for; None if it isn't a bounded slice."""
    cmd, args = argv[0], argv[1:]
    if cmd in ("head", "tail"):
        if "-f" in args or "-F" in args:
            return MAX_DUMP_LINES + 1
        for i, a in enumerate(args):
            m = re.fullmatch(r"-n?\+?(\d+)", a) or (a == "-n" and i + 1 < len(args) and re.fullmatch(r"\+?(\d+)", args[i + 1]))
            if m:
                return int(m.group(1))
        return 10
    if cmd == "sed" and "-n" in args:
        for a in args:
            m = re.fullmatch(r"(\d+),(\d+)p", a)
            if m:
                return int(m.group(2)) - int(m.group(1)) + 1
            if re.fullmatch(r"\d+p", a):
                return 1
        return MAX_DUMP_LINES + 1
    return None


def dump_reason(command):
    # only look at commands that start a pipeline: `x | tail -40` is the good pattern
    for seg in re.split(r"&&|\|\||;|\n", command):
        first = seg.split("|")[0].strip()
        if not first or "<<" in first or re.search(r"(^|\s)>{1,2}", first):
            continue
        try:
            argv = shlex.split(first)
        except ValueError:
            continue
        if not argv or argv[0] not in DUMPERS:
            continue
        if argv[0] == "sed" and "-n" not in argv:
            continue
        files = [a for a in argv[1:] if not a.startswith("-") and os.path.isfile(os.path.expanduser(a))]
        if not files:
            continue
        asked = requested_lines(argv)
        if asked is None:  # cat/less/more: size of what would be printed
            asked = sum(count_lines(os.path.expanduser(f), MAX_DUMP_LINES + 1) for f in files)
        if asked > MAX_DUMP_LINES:
            return (f"`{argv[0]}` would print over {MAX_DUMP_LINES} lines into the main context. "
                    "Use `grep -n` with a few lines of context, or Read with offset/limit.")
    return None


def chore_count(session, bump=False, reset=False):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"chores-{re.sub(r'[^A-Za-z0-9_-]', '', session) or 'none'}.count")
    n = 0
    if not reset and os.path.exists(path):
        try:
            n = int(open(path).read().strip() or 0)
        except ValueError:
            n = 0
    if bump:
        n += 1
    if bump or reset:
        with open(path, "w") as f:
            f.write(str(n))
    return n


def main():
    if os.environ.get("CHORE_GUARD_OFF") == "1":
        return
    data = json.load(sys.stdin)
    session = str(data.get("session_id") or "")
    if data.get("hook_event_name") == "UserPromptSubmit":
        chore_count(session, reset=True)
        return
    if data.get("agent_id"):
        return  # subagents do the chores; that's the point
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}

    if tool == "Read":
        path = os.path.expanduser(inp.get("file_path") or "")
        binary = path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb"))
        if "limit" not in inp and "offset" not in inp and not binary and os.path.isfile(path):
            if count_lines(path, MAX_READ_LINES + 1) > MAX_READ_LINES:
                block(f"this file is over {MAX_READ_LINES} lines. Read it with offset/limit, or `grep -n` for the part you need.")
        return

    if tool == "Bash":
        command = inp.get("command") or ""
        if CODEX.search(command):
            return
        reason = dump_reason(command)
        if reason:
            block(reason)
        if not CHORE_CMD.search(command):
            return
        target = "Codex (scripts/codex_worker.py)"
    elif tool.startswith("mcp__Claude_Browser__"):
        target = "haiku-worker (Codex can't use the browser pane)"
    else:
        return

    if chore_count(session) >= CHORE_BUDGET:
        block(f"this is chore #{CHORE_BUDGET + 1}+ since the user's last message. Delegate the remaining "
              f"chores in one batch to {target} and ask for a report under 300 words.")
    chore_count(session, bump=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass  # fail open: a broken guard must never stop work
